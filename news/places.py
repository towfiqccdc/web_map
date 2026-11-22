"""Official Bangladesh places (64 districts with borders, 495 upazilas, ~4,400 unions) and the checks built on them.

The idea is one general rule instead of fixing stories one by one:
    1. Find EVERY place the story names (district, upazila, union, known neighbourhood).
    2. Work out which district each pin is really in (point-in-polygon on the official border).
    3. A pin must lie in (or right beside) a district the story names. If it does not, it is not used.
"""
import json
import os
import re
from math import cos, radians

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "places.json")
BN = re.compile(r"[ঀ-৿]")
BN_PLACE_SUFFIX = re.compile(r"^(?:ে|তে|য়|য়ে|-এ|-তে|\u09DF|\u09AF\u09BC)")
BORDER_KM = 8          # a pin this close to a named district's border still counts as inside it
# Names that are real places but also ordinary words, or too generic to trust on their own
SKIP_NAMES = {"sadar", "paschim", "purba", "uttar", "dakshin", "north", "south", "east", "west", "bazar", "bazaar", "union", "pourashava",
              "town", "city", "road", "ward", "char", "chor", "para"}
ALT_EN = {"n'ganj": "Narayanganj", "b'baria": "Brahmanbaria", "ctg": "Chattogram", "bagherhat": "Bagerhat", "jhalokati": "Jhalokathi", "chhatak": None,"chittagong": "Chattogram", "comilla": "Cumilla", "barisal": "Barishal", "jessore": "Jashore", "bogra": "Bogura",
          "chapai nawabganj": "Chapainawabganj", "maulvibazar": "Moulvibazar", "jhalakathi": "Jhalokathi", "netrakona": "Netrokona"}


# Bangla spelling varies a lot (ী/ি, শ/ষ/স, ঙ্গ/ঙ, ড়/ড+়): compare words in a "folded" form
_FOLD = str.maketrans({"ী": "ি", "ূ": "ু", "ণ": "ন", "শ": "স", "ষ": "স", "ৈ": "ই", "ৌ": "ঔ"})
_ZW = {"\u200c", "\u200d"}


def fold_word(w):
    return fold_text(w)[0]


_FCACHE = {}


def fold_text(text):
    """(folded, idx) — idx[i] is the position in the original text of folded character i."""
    hit = _FCACHE.get(text)
    if hit:
        return hit
    import unicodedata
    out, idx = [], []
    for i, ch in enumerate(text):
        if ch in _ZW:
            continue
        for c in unicodedata.normalize("NFD", ch):
            c = c.translate(_FOLD)
            if c == "গ" and len(out) >= 2 and out[-1] == "্" and out[-2] == "ঙ":     # ঙ্গ -> ঙ
                out.pop()
                continue
            out.append(c)
            idx.append(i)
    res = ("".join(out), idx)
    if len(_FCACHE) > 500:
        _FCACHE.clear()
    _FCACHE[text] = res
    return res


def bn_find(text, word, start=0):
    """First (start, end) of a Bangla word in the text, ignoring spelling variants; None if absent."""
    ft, idx = fold_text(text)
    fw = fold_word(word)
    i = ft.find(fw, start)
    while i >= 0:
        if i == 0 or not BN.match(ft[i - 1]):
            return idx[i], idx[i + len(fw) - 1] + 1
        i = ft.find(fw, i + 1)
    return None


def _km(lat1, lng1, lat2, lng2):
    kx = 111.0 * cos(radians((lat1 + lat2) / 2))
    return (((lng2 - lng1) * kx) ** 2 + ((lat2 - lat1) * 111.0) ** 2) ** 0.5


class Places:
    def __init__(self, path=DATA):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        self.districts = {}
        for d in raw["districts"]:
            xs = [p[0] for r in d["rings"] for p in r]
            ys = [p[1] for r in d["rings"] for p in r]
            self.districts[d["n"]] = {"name": d["n"], "bn": d["b"], "c": tuple(d["c"]), "rings": d["rings"],
                                      "bbox": (min(xs), min(ys), max(xs), max(ys))}
        self.by_en, self.by_bn = {}, []          # lowercase name -> [entries]; Bangla list for substring search
        for level, rows in (("district", raw["districts"]), ("upazila", raw["upazilas"]), ("union", raw["unions"])):
            for r in rows:
                name, bn = r["n"], r["b"]
                dist = name if level == "district" else r["d"]
                lat, lng = (r["c"] if level != "district" else self.districts[name]["c"])
                e = {"name": name, "level": level, "district": dist, "lat": lat, "lng": lng}
                key = name.lower()
                if level != "district" and name in self.districts:
                    continue                                          # "Gazipur Sadar" etc. are the district itself
                if len(key) >= 4 and key not in SKIP_NAMES:
                    self.by_en.setdefault(key, []).append(e)
                if bn and len(bn) >= (3 if level != "union" else 4):
                    self.by_bn.append((fold_word(bn), e))
        for key, entries in list(self.by_en.items()):
            for dk, en in (("dakshin ", "south "), ("uttar ", "north "), ("purba ", "east "), ("paschim ", "west "), ("sadar ", "")):
                if key.startswith(dk) and len(key) > len(dk) + 3 and not (dk == "sadar " and False):
                    self.by_en.setdefault(en + key[len(dk):], []).extend(entries)
        for alt, canon in ALT_EN.items():
            if not canon:
                continue
            self.by_en.setdefault(alt, []).append({"name": canon, "level": "district", "district": canon,
                                                   "lat": self.districts[canon]["c"][0], "lng": self.districts[canon]["c"][1]})
        self.by_bn.sort(key=lambda t: -len(t[0]))                       # longest first
        names = sorted(self.by_en, key=len, reverse=True)
        self.re_en = re.compile(r"(?<![\w'])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.I)

    # ---- where is a point?
    def _inside(self, d, lng, lat):
        x0, y0, x1, y1 = d["bbox"]
        if not (x0 <= lng <= x1 and y0 <= lat <= y1):
            return False
        for ring in d["rings"]:
            inside, j = False, len(ring) - 1
            for i in range(len(ring)):
                xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
                if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi:
                    inside = not inside
                j = i
            if inside:
                return True
        return False

    def district_at(self, lat, lng):
        """The district whose border contains the point (nearest centre if the point is on a border gap or the coast)."""
        for d in self.districts.values():
            if self._inside(d, lng, lat):
                return d["name"]
        return min(self.districts.values(), key=lambda d: _km(lat, lng, d["c"][0], d["c"][1]))["name"]

    def km_to_district(self, lat, lng, name):
        """0 if the point is inside the district, else the distance to its border."""
        d = self.districts.get(name)
        if not d:
            return 1e9
        if self._inside(d, lng, lat):
            return 0.0
        best = 1e9
        kx = 111.0 * cos(radians(lat))
        for ring in d["rings"]:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                ax, ay, bx, by = (x1 - lng) * kx, (y1 - lat) * 111.0, (x2 - lng) * kx, (y2 - lat) * 111.0
                dx, dy = bx - ax, by - ay
                t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1e-12)))
                best = min(best, ((ax + t * dx) ** 2 + (ay + t * dy) ** 2) ** 0.5)
        return best

    def fits(self, lat, lng, named):
        """True if the pin is in, or right beside, at least one of the named districts (or nothing is named)."""
        return (not named) or any(self.km_to_district(lat, lng, n) <= BORDER_KM for n in named)

    # ---- what does the text name?
    def mentions(self, text):
        """Every official place named in the text: [{name, level, district, lat, lng, pos, ambiguous:[entries]}]"""
        found = []
        for m in self.re_en.finditer(text):
            entries = self.by_en[m.group(1).lower()]
            found.append((m.start(), m.end(), entries))
        ft, idx = fold_text(text) if BN.search(text) else ("", [])
        for bn, e in self.by_bn:
            i = 0
            while ft:
                i = ft.find(bn, i)
                if i < 0:
                    break
                if i == 0 or not BN.match(ft[i - 1]):                   # not the tail of a longer word
                    found.append((idx[i], idx[i + len(bn) - 1] + 1, [{**e, "bn": True}]))
                i += len(bn)
        found.sort(key=lambda f: (f[0], f[1]))
        merged = {}
        for pos, end, entries in found:                                 # the same words can match several entries (same name, different districts)
            slot = merged.setdefault((pos, end), [])
            for e in entries:
                if (e["name"], e["district"], e["level"]) not in {(x["name"], x["district"], x["level"]) for x in slot}:
                    slot.append(e)
        return [{"pos": p, "end": e_, "entries": ents} for (p, e_), ents in sorted(merged.items())]

    def fuzzy(self, token):
        """A misspelt district/upazila ("Jhalokati", "Barolekha"): the closest official name, or None."""
        import difflib
        if not hasattr(self, "_fz"):
            self._fz = {k: v for k, v in self.by_en.items() if any(e["level"] in ("district", "upazila") for e in v) and len(k) >= 6}
        t = token.lower()
        near = [k for k in self._fz if k[0] == t[0] and abs(len(k) - len(t)) <= 2]
        hit = difflib.get_close_matches(t, near, n=1, cutoff=0.88)
        return [e for e in self._fz[hit[0]] if e["level"] in ("district", "upazila")] if hit else None

    def named_districts(self, text):
        """Districts the text names or clearly implies (a named upazila/union also names its district only when unambiguous)."""
        names, seen = [], set()
        for m in self.mentions(text):
            for e in m["entries"]:
                if e["level"] == "district" and e["district"] not in seen:
                    seen.add(e["district"])
                    names.append(e["district"])
        return names

    def resolve(self, text, named=None):
        """Official upazila/union places the text names, with duplicate names settled by the districts the story names.
        Returns [{name, level, district, lat, lng}] best first (unions before upazilas, earlier before later)."""
        named = self.named_districts(text) if named is None else named
        out = []
        for m in self.mentions(text):
            cands = [e for e in m["entries"] if e["level"] != "district"]
            if not cands:
                continue
            if any(e.get("bn") for e in cands) and not named:           # a Bangla village name alone is too risky unless it reads as a place ("…তে", "…ায়")
                if not BN_PLACE_SUFFIX.match(text[m["end"]:m["end"] + 6]):
                    continue
            ok = [e for e in cands if self.fits(e["lat"], e["lng"], named)] if named else cands
            if named and not ok:
                continue
            if any(e["level"] == "upazila" for e in ok):
                ok = [e for e in ok if e["level"] == "upazila"]
            if len({(e["district"]) for e in ok}) != 1:                  # same name in several districts and nothing to decide: do not guess
                continue
            e = ok[0]
            if e["name"].lower() in {o["name"].lower() for o in out}:
                continue
            out.append({**e, "pos": m["pos"], "end": m["end"]})
        out.sort(key=lambda e: (0 if e["level"] == "union" else 1, e["pos"]))
        return out


_ENGINE = None


def engine():
    global _ENGINE
    if _ENGINE is None and os.path.exists(DATA):
        _ENGINE = Places()
    return _ENGINE
