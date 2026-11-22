"""Builds news/data/places.json from the open-data repo https://github.com/nuhil/bangladesh-geocode (MIT licence).

    git clone --depth 1 https://github.com/nuhil/bangladesh-geocode.git /tmp/bdgeo
    python3 news/build_places.py /tmp/bdgeo

It keeps: 64 districts (name, Bangla name, centre, simplified border), 495 upazilas and ~4,500 unions
(name, Bangla name, parent, centre). The news job uses them to check that every pin is inside the
district the story talks about."""
import json
import sys
import os

CANON = {"Barisal": "Barishal", "Bogra": "Bogura", "Brahamanbaria": "Brahmanbaria", "Chittagong": "Chattogram", "Comilla": "Cumilla",
         "Jessore": "Jashore", "Jhalokati": "Jhalokathi", "Maulvibazar": "Moulvibazar", "Nawabganj": "Chapainawabganj",
         "Netrakona": "Netrokona", "Chapainababganj": "Chapainawabganj"}


def table(path):
    return [x for x in json.load(open(path, encoding="utf-8")) if x.get("type") == "table"][0]["data"]


def rdp(points, eps):
    """Douglas-Peucker line simplification (iterative)."""
    if len(points) < 4:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
        far, fi = 0.0, None
        for i in range(a + 1, b):
            d = abs(dy * (points[i][0] - x1) - dx * (points[i][1] - y1)) / norm
            if d > far:
                far, fi = d, i
        if fi is not None and far > eps:
            keep[fi] = True
            stack += [(a, fi), (fi, b)]
    return [p for p, k in zip(points, keep) if k]


def main(src):
    geo = json.load(open(os.path.join(src, "geojson", "districts.geojson"), encoding="utf-8"))
    dists = table(os.path.join(src, "districts", "districts.json"))
    by_name = {CANON.get(d["name"], d["name"]): d for d in dists}
    id_to_name = {d["id"]: CANON.get(d["name"], d["name"]) for d in dists}
    out = {"districts": [], "upazilas": [], "unions": []}
    for f in geo["features"]:
        name = CANON.get(f["properties"]["ADM2_EN"], f["properties"]["ADM2_EN"])
        polys = f["geometry"]["coordinates"] if f["geometry"]["type"] == "MultiPolygon" else [f["geometry"]["coordinates"]]
        rings = []
        for poly in polys:
            pts = [(x, y) for x, y in poly[0]]                          # outer ring only
            mid = len(pts) // 2                                         # a closed ring starts and ends at one point: simplify in two halves
            ring = rdp(pts[:mid + 1], 0.004)[:-1] + rdp(pts[mid:], 0.004)   # ~400 m accuracy
            if len(ring) >= 4:
                rings.append([[round(x, 3), round(y, 3)] for x, y in ring])
        d = by_name[name]
        out["districts"].append({"n": name, "b": d["bn_name"], "c": [float(d["lat"]), float(d["lon"])], "rings": rings})
    up_name = {}
    for u in table(os.path.join(src, "upazilas", "upazilas.json")):
        up_name[u["id"]] = u["name"]
        if u.get("lat") and u.get("lon"):
            out["upazilas"].append({"n": u["name"], "b": u["bn_name"], "d": id_to_name[u["district_id"]], "c": [round(float(u["lat"]), 4), round(float(u["lon"]), 4)]})
    up_dist = {u["id"]: id_to_name[u["district_id"]] for u in table(os.path.join(src, "upazilas", "upazilas.json"))}
    for u in table(os.path.join(src, "unions", "unions.json")):
        if u.get("lat") and u.get("lon") and u["upazilla_id"] in up_dist:
            out["unions"].append({"n": u["name"], "b": u["bn_name"], "d": up_dist[u["upazilla_id"]], "c": [round(float(u["lat"]), 4), round(float(u["lon"]), 4)]})
    dst = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "places.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
    print({k: len(v) for k, v in out.items()}, os.path.getsize(dst) // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1])
