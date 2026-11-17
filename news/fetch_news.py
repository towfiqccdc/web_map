#!/usr/bin/env python3
"""
Daily news job: find road accidents / road violence in English Bangladeshi news
and add them to Supabase as PENDING risk areas for you to approve in admin.html.

Nothing found here ever affects a route until you approve it.

Needs only Python 3.9+ (no extra packages).
Environment variables (set as GitHub "Secrets"):
    SUPABASE_URL           e.g. https://abcdxyz.supabase.co
    SUPABASE_SERVICE_KEY   the SECRET service_role key (never put it in the website)
Optional:
    NEWS_EXPIRY_DAYS       how long an approved news risk keeps counting (default 30)
    NEWS_MAX_AGE_DAYS      ignore articles older than this (default 2)

Try it without touching the database:
    python3 news/fetch_news.py --dry-run
"""
import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
USER_AGENT = "web_map-road-safety/1.0 (+https://github.com/towfiqccdc/web_map)"
BBOX = (20.5, 26.7, 88.0, 92.8)          # lat_min, lat_max, lng_min, lng_max  (Bangladesh)
MAX_FEED_BYTES = 3_000_000
MAX_GEOCODES_PER_RUN = 60

# ------------------------------------------------------------------ keywords
ROAD_CONTEXT = re.compile(
    r"\b(road|roads|highway|expressway|bypass|flyover|bridge|intersection|crossing|"
    r"bus|buses|truck|lorry|covered van|pickup|microbus|ambulance|cng|auto-?rickshaw|"
    r"easy bike|motorcycle|motorbike|bike|rickshaw|car|train|hit-and-run)\b", re.I)

ACCIDENT = re.compile(
    r"\b(accident|crash|crashed|collision|collided|collide|run over|ran over|hit-and-run|"
    r"overturn|overturned|skid|skidded|plunge|plunged|rammed|ram|mowed down|killed|dead|"
    r"die|dies|died|injured|hurt)\b", re.I)

VIOLENCE = re.compile(
    r"\b(hijack|hijacked|highway robbery|robbery|robbers|robbed|mugging|mugged|dacoit|"
    r"dacoity|bandits?|extortion|mob|clash|clashes|ambush|ambushed|attack|attacked|"
    r"arson|torched|set fire|vandali[sz]ed|stabbed|shot dead|gunfight|crude bombs?)\b", re.I)

CRASH_WORDS = re.compile(r"\b(crash|crashed|collision|collided|run over|ran over|hit-and-run|overturn|overturned|rammed|mowed down)\b", re.I)

NOT_AN_INCIDENT = re.compile(
    r"\b(road safety (week|day|movement)|awareness|campaign|statistics|survey|annual report|"
    r"monthly report|according to a report|report says|report shows|death toll rises to \d{3,}|"
    r"seminar|webinar|workshop|opinion|editorial)\b", re.I)

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
DEATHS = re.compile(
    r"\b(\d{1,3}|" + "|".join(NUMBER_WORDS) + r")\s+(?:people|persons|passengers|others|men|women|"
    r"children|students|youths|labou?rers|workers|bikers|motorcyclists)?\s*"
    r"(?:were\s+|was\s+)?(?:killed|dead|die|died|crushed to death|burnt to death)\b", re.I)

DISTRICTS = [
    "Bagerhat", "Bandarban", "Barguna", "Barishal", "Bhola", "Bogura", "Brahmanbaria", "Chandpur",
    "Chapainawabganj", "Chattogram", "Chuadanga", "Cumilla", "Cox's Bazar", "Dhaka", "Dinajpur",
    "Faridpur", "Feni", "Gaibandha", "Gazipur", "Gopalganj", "Habiganj", "Jamalpur", "Jashore",
    "Jhalokathi", "Jhenaidah", "Joypurhat", "Khagrachhari", "Khulna", "Kishoreganj", "Kurigram",
    "Kushtia", "Lakshmipur", "Lalmonirhat", "Madaripur", "Magura", "Manikganj", "Meherpur",
    "Moulvibazar", "Munshiganj", "Mymensingh", "Naogaon", "Narail", "Narayanganj", "Narsingdi",
    "Natore", "Netrokona", "Nilphamari", "Noakhali", "Pabna", "Panchagarh", "Patuakhali",
    "Pirojpur", "Rajbari", "Rajshahi", "Rangamati", "Rangpur", "Satkhira", "Shariatpur",
    "Sherpur", "Sirajganj", "Sunamganj", "Sylhet", "Tangail", "Thakurgaon",
]

# Words that start sentences or are not places, so they are never place candidates
STOP = {"The", "A", "An", "On", "In", "At", "Police", "Bus", "Truck", "Two", "Three", "Four", "Five",
        "Six", "One", "Man", "Woman", "Child", "Killed", "Injured", "Others", "Road", "Highway",
        "Dhaka Tribune", "The Daily Star", "Daily Star", "Prothom Alo", "Bangladesh", "BRTA",
        "CNG", "Friday", "Saturday", "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday"}

CAP = r"[A-Z][\w'’-]+"
LINEAR = r"(?:[Hh]ighway|[Ee]xpressway|[Bb]ypass|[Rr]oad|[Ss]treet)"
POINT_SUFFIX = r"(?:[Bb]ridge|[Ff]lyover|[Uu]pazila|Bazar|Bazaar|[Ii]ntersection|[Cc]rossing|Chattar|Mor|Bus Stand)"
RE_POINT = re.compile(r"\b(" + CAP + r"(?:[ -]" + CAP + r"){0,2}\s+" + POINT_SUFFIX + r")\b")
RE_LINEAR = re.compile(r"\b(" + CAP + r"(?:[ -]" + CAP + r"){0,2}\s+(?:[Hh]ighway|[Ee]xpressway|[Bb]ypass))\b")
RE_PREP = re.compile(r"\b(?:at|in|near|on|along|outside|beside)\s+(" + CAP + r"(?:\s+" + CAP + r"){0,2})(\s+" + LINEAR + r")?")


# ------------------------------------------------------------------ helpers
def log(*a):
    print(*a, flush=True)


def http_get(url, headers=None, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(MAX_FEED_BYTES + 1)


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def read_feed_urls(path):
    urls = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


# ------------------------------------------------------------------ feeds
def parse_feed(xml_bytes):
    """Return a list of {title, link, summary, published(datetime|None)} from RSS/Atom bytes."""
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        def get(*names):
            # NB: never use `a or b` on XML elements — an element with no child tags counts as False
            for name in names:
                for ch in it:
                    if ch.tag.split("}")[-1] == name:
                        return ch
            return None
        title = get("title")
        link = get("link")
        url = ""
        if link is not None:
            url = (link.text or "").strip() or link.attrib.get("href", "")
        summ = get("description", "summary", "content")
        pub = get("pubDate", "published", "updated")
        when = None
        if pub is not None and pub.text:
            try:
                when = parsedate_to_datetime(pub.text.strip())
            except (TypeError, ValueError):
                try:
                    when = dt.datetime.fromisoformat(pub.text.strip().replace("Z", "+00:00"))
                except ValueError:
                    when = None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        items.append({"title": strip_html(title.text if title is not None else ""),
                      "link": url,
                      "summary": strip_html(summ.text if summ is not None else ""),
                      "published": when})
    return items


# ------------------------------------------------------------------ classification
def classify(title, summary):
    """Return None if not a road incident, else {type, severity, deaths}."""
    text = f"{title}. {summary}"
    if NOT_AN_INCIDENT.search(text):
        return None
    if not ROAD_CONTEXT.search(text):
        return None
    has_acc, has_vio = bool(ACCIDENT.search(text)), bool(VIOLENCE.search(text))
    if not (has_acc or has_vio):
        return None
    kind = "accident" if (has_acc and (CRASH_WORDS.search(text) or not has_vio)) else "violence"
    deaths = 0
    for m in DEATHS.finditer(text):
        n = m.group(1).lower()
        deaths = max(deaths, int(n) if n.isdigit() else NUMBER_WORDS.get(n, 0))
    if re.search(r"\b(killed|dead|died|shot dead)\b", text, re.I) and deaths == 0:
        deaths = 1
    severity = 3 if deaths >= 3 else (2 if (deaths >= 1 or kind == "violence") else 1)
    return {"type": kind, "severity": severity, "deaths": deaths}


# ------------------------------------------------------------------ places
DISTRICT_SET = {d.lower() for d in DISTRICTS}


def place_candidates(title, summary):
    """Possible place names, best guess first. Returns [(name, is_district_only)].

    Order: a town/village named after "at/in/near" (most precise), then bridges/bazars/
    crossings, then whole districts (coarse), and highways LAST — a highway can be
    hundreds of km long, so its geocoded point is a poor guess for where it happened."""
    ranked, seen = [], set()
    full = f"{title}. {summary}"

    def add(name, rank):
        name = name.strip(" ,.-")
        if len(name) < 3 or name in STOP or name.lower() in seen:
            return
        seen.add(name.lower())
        ranked.append((rank, len(ranked), name))

    for text in (title, summary):
        for m in RE_PREP.finditer(text):
            if m.group(2):                       # "on Dhaka-Sylhet highway": a road name, not a place
                continue
            add(m.group(1), 2 if m.group(1).lower() in DISTRICT_SET else 0)
        for m in RE_POINT.finditer(text):
            add(m.group(1), 1)
    for d in DISTRICTS:
        if re.search(r"\b" + re.escape(d) + r"\b", full):
            add(d, 2)
    for text in (title, summary):
        for m in RE_LINEAR.finditer(text):
            add(m.group(1), 3)
    ranked.sort()
    return [(name, rank == 2) for rank, _, name in ranked]


class Geocoder:
    """Nominatim, polite: 1 request/second, cached, hard cap per run."""
    URL = "https://nominatim.openstreetmap.org/search"

    def __init__(self, max_calls=MAX_GEOCODES_PER_RUN, sleep=1.1, fetch=None):
        self.cache, self.calls, self.max_calls, self.sleep = {}, 0, max_calls, sleep
        self.fetch = fetch or http_get

    def lookup(self, name):
        key = name.lower()
        if key in self.cache:
            return self.cache[key]
        if self.calls >= self.max_calls:
            return None
        self.calls += 1
        q = urllib.parse.urlencode({"q": f"{name}, Bangladesh", "format": "jsonv2", "limit": 1,
                                    "countrycodes": "bd", "accept-language": "en"})
        result = None
        try:
            rows = json.loads(self.fetch(f"{self.URL}?{q}"))
            if rows:
                lat, lng = float(rows[0]["lat"]), float(rows[0]["lon"])
                if BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lng <= BBOX[3]:
                    result = (lat, lng)
        except Exception as e:                     # network hiccup: just skip this name
            log(f"   geocode failed for {name!r}: {e}")
        self.cache[key] = result
        time.sleep(self.sleep)
        return result


def locate(title, summary, geocoder):
    """Return {lat, lng, place_text, radius_m} or None."""
    for name, district_only in place_candidates(title, summary)[:4]:   # few tries per article: Nominatim allows 1 request/second
        pt = geocoder.lookup(name)
        if pt:
            return {"lat": pt[0], "lng": pt[1],
                    "place_text": name + (" (district only — check location)" if district_only else ""),
                    "radius_m": 8000 if district_only else 2000}
    return None


# ------------------------------------------------------------------ pipeline
def _km(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 12742 * asin(sqrt(h))


def build_rows(items, geocoder, max_age_days, expiry_days, now=None):
    """Turn feed items into rows ready for the risk_areas table. Returns (rows, stats)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stats = {"seen": 0, "too_old": 0, "not_incident": 0, "no_place": 0, "duplicate": 0, "kept": 0}
    rows, seen_urls, seen_keys = [], set(), set()
    for it in items:
        stats["seen"] += 1
        if not it["link"] or it["link"] in seen_urls:
            stats["duplicate"] += 1
            continue
        seen_urls.add(it["link"])
        if it["published"] and (now - it["published"]).days > max_age_days:
            stats["too_old"] += 1
            continue
        c = classify(it["title"], it["summary"])
        if not c:
            stats["not_incident"] += 1
            continue
        loc = locate(it["title"], it["summary"], geocoder)
        if not loc:
            stats["no_place"] += 1
            log(f"   no place found: {it['title'][:90]}")
            continue
        happened = (it["published"] or now).date().isoformat()
        key = (loc["place_text"].lower(), happened, c["type"])      # same story from several outlets
        if key in seen_keys or any(r["type"] == c["type"] and r["happened_on"] == happened and
                                   _km(r["lat"], r["lng"], loc["lat"], loc["lng"]) < 4 for r in rows):
            stats["duplicate"] += 1
            continue
        seen_keys.add(key)
        rows.append({
            "title": it["title"][:200], "type": c["type"], "severity": c["severity"],
            "lat": round(loc["lat"], 6), "lng": round(loc["lng"], 6), "radius_m": loc["radius_m"],
            "source": "news", "source_url": it["link"], "place_text": loc["place_text"][:120],
            "status": "pending", "happened_on": happened,
            "expires_at": (now + dt.timedelta(days=expiry_days)).isoformat(),
        })
        stats["kept"] += 1
    return rows, stats


def supabase_request(method, path, body=None, extra_headers=None):
    base, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "User-Agent": USER_AGENT, **(extra_headers or {})}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def drop_already_stored(rows, request=None):
    """Remove rows whose link, or place+date+type, is already in the database (any status)."""
    request = request or supabase_request
    since = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    existing = request("GET", "/rest/v1/risk_areas?select=source_url,place_text,happened_on,type"
                              f"&created_at=gte.{since}&limit=2000") or []
    urls = {e.get("source_url") for e in existing}
    keys = {((e.get("place_text") or "").lower(), e.get("happened_on"), e.get("type")) for e in existing}
    fresh = [r for r in rows if r["source_url"] not in urls and (r["place_text"].lower(), r["happened_on"], r["type"]) not in keys]
    return fresh


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would be added; do not touch the database")
    ap.add_argument("--feeds", default=os.path.join(HERE, "feeds.txt"))
    args = ap.parse_args(argv)

    max_age = int(os.environ.get("NEWS_MAX_AGE_DAYS", "2"))
    expiry = int(os.environ.get("NEWS_EXPIRY_DAYS", "30"))
    if not args.dry_run and not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        log("ERROR: set SUPABASE_URL and SUPABASE_SERVICE_KEY (or use --dry-run).")
        return 2

    items, ok, failed = [], 0, []
    for url in read_feed_urls(args.feeds):
        try:
            got = parse_feed(http_get(url))
            items.extend(got)
            ok += 1
            log(f"OK    {len(got):3d} items  {url[:100]}")
        except Exception as e:
            failed.append(url)
            log(f"FAIL  {url[:100]}  ({type(e).__name__}: {e})")

    rows, stats = build_rows(items, Geocoder(), max_age, expiry)
    log(f"\nFeeds ok: {ok}, failed: {len(failed)}   |   {stats}")

    if args.dry_run:
        for r in rows:
            log(f" + [{r['type']} sev{r['severity']}] {r['title'][:80]}  @ {r['place_text']} ({r['lat']}, {r['lng']})")
        return 0 if ok else 1

    if rows:
        rows = drop_already_stored(rows)
        if rows:
            supabase_request("POST", "/rest/v1/risk_areas?on_conflict=source_url", rows,
                             {"Prefer": "resolution=ignore-duplicates,return=minimal"})
    log(f"Added {len(rows)} new PENDING risk area(s). Review them in admin.html.")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(f"### Daily news check\n- Feeds ok: **{ok}**, failed: **{len(failed)}**\n"
                    f"- New pending risk areas: **{len(rows)}**\n- Details: `{stats}`\n")
            for u in failed:
                f.write(f"- ⚠️ feed failed: `{u}`\n")
    return 0 if ok else 1          # every feed failed -> mark the run red so you get an email


if __name__ == "__main__":
    sys.exit(main())
