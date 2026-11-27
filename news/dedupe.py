"""One incident, one pin: merge the same event reported by several newspapers (and by earlier runs).

Two reports are the same event when they have the same kind of incident, happened within a day of each other,
sit close together on the map and read alike. The best-verified, most precise report keeps the pin; the others
are listed on it as "Also reported by" so nothing is lost and the map is not stacked with copies.
"""
import datetime as dt
import re
from math import asin, cos, radians, sin, sqrt

STOP = set("""this that with from have been were after over into near their about which while when where there than then they them
also said says police were was will would could amid says three four five two one six seven eight nine ten more most some many
dhaka tribune daily star business standard prothom bdnews24 news times post online bangladesh bangla report reports reported
killed injured held arrested""".split())
RANK = {"high": 2, "medium": 1, "low": 0, None: 1}


def _km(a, b, c, d):
    p = radians
    h = sin(p(c - a) / 2) ** 2 + cos(p(a)) * cos(p(c)) * sin(p(d - b) / 2) ** 2
    return 12742 * asin(sqrt(h))


def tokens(title):
    t = re.sub(r"^[^:]{2,60}:\s+", "", title or "")                       # our own "Place: " prefix
    t = re.sub(r"\s+[-–|]\s+[^-–|]{2,40}$", "", t)                       # outlet suffix
    return {w for w in re.findall(r"[a-z]{4,}", t.lower()) if w not in STOP}


def sim(a, b):
    ta, tb = tokens(a), tokens(b)
    return len(ta & tb) / (len(ta | tb) or 1)


def _day(r):
    try:
        return dt.date.fromisoformat(str(r["happened_on"])[:10])
    except (KeyError, ValueError):
        return None


def same_event(a, b):
    if a["type"] != b["type"]:
        return False
    da, db = _day(a), _day(b)
    if da and db and abs((da - db).days) > 1:
        return False
    km = _km(a["lat"], a["lng"], b["lat"], b["lng"])
    s = sim(a["title"], b["title"])
    if km <= 0.3:
        return True
    if km <= 1.5:
        return s >= 0.2
    if km <= 12:
        return s >= 0.4                                                  # same story, one outlet names the union, the other the upazila
    return False


def quality(r):
    return (RANK.get(r.get("confidence"), 1), bool(r.get("body_read")), -(r.get("radius_m") or 9999))


def _add(also, outlet, url):
    entry = f"{outlet or 'another outlet'}|{url}"
    cur = [x for x in (also or "").split("\n") if x]
    if url and all(url.split("#")[0] not in x for x in cur):
        cur.append(entry)
    return "\n".join(cur) or None


def merge(rows, existing=()):
    """rows: new rows (may carry "_outlet"). existing: rows already stored (id, type, lat, lng, happened_on, title, also_in, source_url).
    Returns (rows_to_insert, [(existing_id, also_in_text)])."""
    patches, extra = {}, {}
    fresh = []
    for r in sorted(rows, key=quality, reverse=True):
        base = r["source_url"].split("#")[0]
        hit = next((e for e in existing if e.get("source_url", "").split("#")[0] != base and same_event(r, e)), None)
        if hit is not None:                                              # an earlier run already shows this event
            cur = extra.get(hit["id"], hit.get("also_in"))
            extra[hit["id"]] = _add(cur, r.get("_outlet"), r["source_url"].split("#")[0])
            continue
        twin = next((k for k in fresh if k["source_url"].split("#")[0] != base and same_event(r, k)), None)
        if twin is not None:                                             # the same event from another outlet in this run
            twin["also_in"] = _add(twin.get("also_in"), r.get("_outlet"), r["source_url"].split("#")[0])
            continue
        fresh.append(r)
    for i, txt in extra.items():
        patches[i] = txt
    return fresh, sorted(patches.items())
