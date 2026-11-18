#!/usr/bin/env python3
"""
Daily news job: find road accidents, road violence and street security incidents
(cocktail blasts, vehicle arson, road blockades, hijack...) in English AND Bangla news
and add them to Supabase as PENDING risk areas for you to approve on the map (Admin button).

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
    r"easy bike|motorcycle|motorbike|bike|rickshaw|car|train|hit-and-run|vehicle|vehicles|commuters|"
    r"passengers|traffic|railway|rail line)\b", re.I)

ACCIDENT = re.compile(
    r"\b(accident|crash|crashed|collision|collided|collide|run over|ran over|hit-and-run|"
    r"overturn|overturned|skid|skidded|plunge|plunged|rammed|ram|mowed down|killed|dead|"
    r"die|dies|died|injured|hurt)\b", re.I)

VIOLENCE = re.compile(
    r"\b(hijack|hijacked|highway robbery|robbery|robbers|robbed|mugging|mugged|dacoit|"
    r"dacoity|bandits?|extortion|mob|clash|clashes|ambush|ambushed|attack|attacked|"
    r"arson|torched|set fire|set on fire|set ablaze|ablaze|vandali[sz]ed|vandalism|stone-?pelting|pelted|"
    r"stabbed|shot dead|gunfight|crude bombs?|cocktails?|petrol bombs?)\b", re.I)

# Security incidents that matter even when the text has no road word ("cocktail blast in Mohammadpur")
SECURITY_STRONG = re.compile(
    r"\b(cocktails?|crude bombs?|petrol bombs?|bombs?|blasts?|explosions?|exploded|detonated|"
    r"road ?blocks?|roadblock|blockade[sd]?|barricad(?:e|es|ed|ing))\b", re.I)
# ...but not gas / boiler / factory explosions, or blasts abroad-style wording
NOT_SECURITY = re.compile(r"\b(gas|cylinder|boiler|furnace|stove|cooker|mill|factory|garment|chemical|mine|quarry|"
                          r"firecracker|fireworks|cracker|film|movie|serial)\b", re.I)

CRASH_WORDS = re.compile(r"\b(crash|crashed|collision|collided|run over|ran over|hit-and-run|overturn|overturned|rammed|mowed down)\b", re.I)

NOT_AN_INCIDENT = re.compile(
    r"\b(road safety (week|day|movement)|awareness|campaign|statistics|survey|annual report|"
    r"monthly report|according to a report|report says|report shows|death toll rises to \d{3,}|"
    r"seminar|webinar|workshop|opinion|editorial|verdict|sentenced|death sentence|charge[- ]?sheet|trial begins|hearing)\b", re.I)

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

# ------------------------------------------------------------------ Bangla keywords
# Bangla vowel signs are not "word" characters for Python's \b, so Bangla is matched as plain text.
BN_CHARS = re.compile(r"[ঀ-৿]")
BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
BN_NUMBER_WORDS = {"এক": 1, "দুই": 2, "দুজন": 2, "তিন": 3, "চার": 4, "পাঁচ": 5, "ছয়": 6, "সাত": 7, "আট": 8, "নয়": 9, "দশ": 10}
BN_STRONG = ("ককটেল", "ক্রুড বোমা", "বোমা", "বিস্ফোরণ", "সড়ক অবরোধ", "মহাসড়ক অবরোধ", "সড়ক অবরুদ্ধ",
             "মহাসড়ক অবরুদ্ধ", "রাস্তা অবরোধ", "ব্লকেড", "সড়কে অবরোধ")
BN_VEHICLE = ("বাস", "ট্রাক", "লরি", "গাড়ি", "গাড়ী", "কভার্ড ভ্যান", "পিকআপ", "অটোরিকশা", "অটোরিক্সা", "সিএনজি", "মোটরসাইকেল",
              "রিকশা", "ট্রেন", "সড়ক", "মহাসড়ক", "সেতু", "ফ্লাইওভার", "মোড়", "যানবাহন", "অ্যাম্বুলেন্স")
BN_FIRE = ("আগুন", "অগ্নিসংযোগ", "পুড়িয়ে", "ভাঙচুর", "ইটপাটকেল")
BN_VIOLENCE = ("ডাকাতি", "ছিনতাই", "হামলা", "সংঘর্ষ", "গুলি", "ছুরিকাঘাত", "চাঁদাবাজি", "হাইজ্যাক", "ককটেল")
BN_ACCIDENT = ("দুর্ঘটনা", "নিহত", "চাপা", "উল্টে", "ধাক্কা", "আহত", "মুখোমুখি")
BN_CRASH = ("দুর্ঘটনা", "চাপা", "উল্টে", "ধাক্কা", "মুখোমুখি")
BN_NOT_INCIDENT = ("মামলার রায়", "রায় ঘোষণা", "দণ্ডাদেশ", "সাজা", "সেমিনার", "কর্মশালা", "সচেতনতা", "সম্পাদকীয়", "মতামত", "প্রতিবেদন প্রকাশ")
BN_NOT_SECURITY = ("গ্যাস", "সিলিন্ডার", "বয়লার", "কারখানা", "চুলা", "আতশবাজি", "সিনেমা")
BN_DEATHS = re.compile(r"([০-৯0-9]+|" + "|".join(BN_NUMBER_WORDS) + r")\s*(?:জন|জনের)?\s*(?:নিহত|মারা|মৃত্যু)")

# ------------------------------------------------------------------ Bangla -> English titles
BN_OUTLETS = {
    "প্রথম আলো": "Prothom Alo", "দৈনিক ইত্তেফাক": "Daily Ittefaq", "ইত্তেফাক": "Daily Ittefaq", "যুগান্তর": "Jugantor",
    "কালের কণ্ঠ": "Kaler Kantho", "সমকাল": "Samakal", "ঢাকা পোস্ট": "Dhaka Post", "বাংলাদেশ প্রতিদিন": "Bangladesh Pratidin",
    "জাগো নিউজ ২৪": "Jago News 24", "জাগোনিউজ২৪.কম": "Jago News 24", "বাংলানিউজ২৪.কম": "Banglanews24", "নয়া দিগন্ত": "Naya Diganta",
    "ইনকিলাব": "Inqilab", "দেশ রূপান্তর": "Desh Rupantor", "মানবজমিন": "Manab Zamin", "বিডিনিউজ ২৪": "bdnews24",
    "বণিক বার্তা": "Bonik Barta", "দৈনিক স্টার": "The Daily Star", "ডেইলি স্টার বাংলা": "The Daily Star (Bangla)",
    "ঢাকা ট্রিবিউন": "Dhaka Tribune", "চ্যানেল আই অনলাইন": "Channel i", "এনটিভি": "NTV", "আরটিভি": "RTV", "সময় নিউজ": "Somoy News",
}
MAX_TRANSLATIONS_PER_RUN = 60


class Translator:
    """Bangla -> English with the free MyMemory service (no key). Best effort: cached, capped per run,
    and anything that looks wrong (quota message, still Bangla) is treated as 'no translation'.
    Set MYMEMORY_EMAIL to raise MyMemory's daily limit (optional)."""
    URL = "https://api.mymemory.translated.net/get"

    def __init__(self, max_calls=MAX_TRANSLATIONS_PER_RUN, sleep=0.4, fetch=None, email=None):
        self.cache, self.calls, self.max_calls, self.sleep = {}, 0, max_calls, sleep
        self.fetch = fetch or http_get
        self.email = (email or "").strip()

    def text(self, bn):
        key = bn.strip()
        if key in self.cache:
            return self.cache[key]
        if self.calls >= self.max_calls:
            return None
        self.calls += 1
        q = {"q": key[:160], "langpair": "bn|en"}
        if self.email:
            q["de"] = self.email
        result = None
        try:
            data = json.loads(self.fetch(f"{self.URL}?{urllib.parse.urlencode(q)}"))
            out = (data.get("responseData") or {}).get("translatedText") or ""
            out = html.unescape(out).strip()
            if (str(data.get("responseStatus")) == "200" and out and "MYMEMORY" not in out.upper()
                    and not BN_CHARS.search(out) and out.lower() != key.lower()):
                result = out
        except Exception as e:
            log(f"   translate failed: {e}")
        self.cache[key] = result
        time.sleep(self.sleep)
        return result

    def title(self, title):
        """Google News titles look like 'Headline - Outlet'. Translate the headline, map the outlet name."""
        head, sep, outlet = title.rpartition(" - ")
        if not sep:
            head, outlet = title, ""
        en = self.text(head)
        if not en:
            return None
        if outlet:
            outlet = BN_OUTLETS.get(outlet.strip()) or (self.text(outlet) if BN_CHARS.search(outlet) else outlet.strip()) or outlet.strip()
            return f"{en} - {outlet}"
        return en


def describe_bn(title, summary, place_text=""):
    """Offline English headline for a Bangla report, used when translation is unavailable.
    Built from the same keywords the classifier uses, so it is always English and always accurate to them."""
    text = f"{title}. {summary}"
    labels = []
    if _has(text, ("ককটেল", "বোমা", "বিস্ফোরণ")):
        labels.append("Cocktail / bomb blast")
    if _has(text, BN_FIRE[:3]) and _has(text, BN_VEHICLE):
        labels.append("Bus set on fire" if "বাস" in text else "Vehicle set on fire")
    if _has(text, ("অবরোধ", "অবরুদ্ধ", "ব্লকেড")):
        labels.append("Road blockade")
    if _has(text, ("ডাকাতি", "ছিনতাই", "হাইজ্যাক")):
        labels.append("Robbery / hijack")
    if _has(text, ("হামলা", "ভাঙচুর", "গুলি", "ছুরিকাঘাত")) or ("সংঘর্ষ" in text and not _has(text, BN_CRASH)):
        labels.append("Attack / clash / vandalism")
    if _has(text, BN_CRASH):
        labels.append("Road accident")
    label = " + ".join(labels[:3]) or "Road incident"
    c = classify_bn(text) or {}
    if c.get("deaths"):
        label += f" ({c['deaths']} killed)"
    where = place_text.split(" (")[0]
    return f"{label}" + (f" — {where}" if where else "") + " (Bangla report)"


# ------------------------------------------------------------------ places we know exactly
# name | other English spellings | Bangla names | lat | lng | "c" = whole city/district (coarse)
# Coordinates are the middle of the neighbourhood/town — good to about a kilometre. The admin
# can drag the pin when reviewing. Focus: Dhaka (head office), Sylhet and Brahmanbaria
# (project areas) and the highways between them.
GAZETTEER_TEXT = """
Mirpur|Mirpur-10|মিরপুর|23.8069|90.3687
Pallabi||পল্লবী|23.8250|90.3640
Mohakhali|Mahakhali|মহাখালী|23.7781|90.4005
Badda||বাড্ডা|23.7806|90.4262
Rampura||রামপুরা|23.7622|90.4222
Mohammadpur||মোহাম্মদপুর|23.7662|90.3586
Jatrabari||যাত্রাবাড়ী|23.7104|90.4344
Shyamoli||শ্যামলী|23.7743|90.3655
Tejgaon||তেজগাঁও|23.7590|90.3925
Uttara||উত্তরা|23.8759|90.3795
Gulshan||গুলশান|23.7925|90.4078
Banani||বনানী|23.7937|90.4066
Motijheel||মতিঝিল|23.7330|90.4172
Paltan||পল্টন|23.7340|90.4120
Shahbagh||শাহবাগ|23.7389|90.3958
Farmgate||ফার্মগেট|23.7571|90.3897
Karwan Bazar|Kawran Bazar|কারওয়ান বাজার|23.7510|90.3925
Malibagh||মালিবাগ|23.7508|90.4122
Moghbazar||মগবাজার|23.7480|90.4050
Khilgaon||খিলগাঁও|23.7476|90.4290
Demra||ডেমরা|23.7160|90.4770
Gabtoli|Gabtali|গাবতলী|23.7786|90.3434
Savar||সাভার|23.8583|90.2667
Ashulia||আশুলিয়া|23.8981|90.2733
Tongi||টঙ্গী|23.8918|90.4058
Kuril||কুড়িল|23.8206|90.4210
Khilkhet||খিলক্ষেত|23.8290|90.4220
Bashundhara||বসুন্ধরা|23.8137|90.4311
Dhanmondi||ধানমন্ডি|23.7461|90.3742
Science Lab||সায়েন্স ল্যাব|23.7391|90.3836
Azimpur||আজিমপুর|23.7285|90.3866
Sayedabad||সায়েদাবাদ|23.7092|90.4250
Kamalapur||কমলাপুর|23.7273|90.4261
Sadarghat||সদরঘাট|23.7089|90.4073
Gulistan||গুলিস্তান|23.7250|90.4120
Postogola||পোস্তগোলা|23.7027|90.4390
Mugda||মুগদা|23.7314|90.4331
Kakrail||কাকরাইল|23.7387|90.4094
Banglamotor||বাংলামোটর|23.7459|90.3935
Hatirjheel||হাতিরঝিল|23.7500|90.4000
Kamrangirchar||কামরাঙ্গীরচর|23.7116|90.3669
Lalbagh||লালবাগ|23.7189|90.3881
Basabo||বাসাবো|23.7413|90.4326
Cantonment||ক্যান্টনমেন্ট|23.8244|90.4056
Old Dhaka|Puran Dhaka|পুরান ঢাকা|23.7104|90.4074
Madhabdi||মাধবদী|23.8583|90.6677
Joydebpur|Joydevpur|জয়দেবপুর|24.0000|90.4200
Ashuganj||আশুগঞ্জ|24.0382|91.0009
Sarail||সরাইল|24.0735|91.1148
Bhairab||ভৈরব|24.0522|90.9764
Akhaura||আখাউড়া|23.8664|91.2000
Dhaka|the capital;capital city;Dhaka city|ঢাকা;রাজধানী;রাজধানীর|23.8103|90.4125|c
Narayanganj||নারায়ণগঞ্জ|23.6238|90.5000|c
Gazipur||গাজীপুর|23.9999|90.4203|c
Narsingdi||নরসিংদী|23.9193|90.7176|c
Sylhet||সিলেট|24.8949|91.8687|c
Habiganj||হবিগঞ্জ|24.3745|91.4155|c
Moulvibazar||মৌলভীবাজার|24.4829|91.7774|c
Sunamganj||সুনামগঞ্জ|25.0715|91.4055|c
Brahmanbaria||ব্রাহ্মণবাড়িয়া|23.9571|91.1115|c
Kishoreganj||কিশোরগঞ্জ|24.4260|90.7766|c
Cumilla|Comilla|কুমিল্লা|23.4607|91.1809|c
Chattogram|Chittagong|চট্টগ্রাম|22.3569|91.7832|c
Tangail||টাঙ্গাইল|24.2513|89.9167|c
"""


def _load_gazetteer(text):
    out = []
    for line in text.strip().splitlines():
        parts = line.split("|")
        name, en_alt, bn = parts[0], parts[1], parts[2]
        lat, lng, coarse = float(parts[3]), float(parts[4]), len(parts) > 5 and parts[5] == "c"
        english = [name] + [a for a in re.split(r"[;,]", en_alt) if a]
        bangla = [b for b in bn.split(";") if b]
        out.append({"name": name, "lat": lat, "lng": lng, "coarse": coarse, "en": english, "bn": bangla})
    return out


GAZETTEER = _load_gazetteer(GAZETTEER_TEXT)

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
def _has(text, words):
    return any(w in text for w in words)


def classify_bn(text):
    """Bangla headline/summary -> same result shape as classify()."""
    if _has(text, BN_NOT_INCIDENT):
        return None
    strong = _has(text, BN_STRONG) and not _has(text, BN_NOT_SECURITY)
    vehicle = _has(text, BN_VEHICLE)
    fire = _has(text, BN_FIRE) and vehicle                  # "বাসে আগুন": fire only counts when a vehicle/road is named
    crash = _has(text, BN_CRASH)
    # "সংঘর্ষ" means both "clash" and "collision": it is violence only when no crash word is present
    violence = _has(text, tuple(w for w in BN_VIOLENCE if w != "সংঘর্ষ")) or ("সংঘর্ষ" in text and not crash)
    accident = _has(text, BN_ACCIDENT) or ("সংঘর্ষ" in text and crash)
    if not (strong or (vehicle and (fire or violence or accident))):
        return None
    kind = "violence" if (strong or fire or violence) else "accident"
    deaths = 0
    for m in BN_DEATHS.finditer(text):
        n = m.group(1)
        v = int(n.translate(BN_DIGITS)) if n.translate(BN_DIGITS).isdigit() else BN_NUMBER_WORDS.get(n, 0)
        deaths = max(deaths, v)
    if "নিহত" in text and deaths == 0:
        deaths = 1
    severity = 3 if deaths >= 3 else (2 if (deaths >= 1 or kind == "violence") else 1)
    return {"type": kind, "severity": severity, "deaths": deaths}


def classify(title, summary):
    """Return None if not a road / street-security incident, else {type, severity, deaths}."""
    text = f"{title}. {summary}"
    if BN_CHARS.search(text):
        return classify_bn(text)
    if NOT_AN_INCIDENT.search(text):
        return None
    strong = bool(SECURITY_STRONG.search(text)) and not NOT_SECURITY.search(text)
    if not strong and not ROAD_CONTEXT.search(text):
        return None
    has_acc, has_vio = bool(ACCIDENT.search(text)), bool(VIOLENCE.search(text)) or strong
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


def find_known_places(title, summary, limit=5):
    """Places from the built-in list (Dhaka areas, Sylhet, Brahmanbaria...), in the order they are
    mentioned. Neighbourhoods/towns win; the whole city/district is used only if nothing finer is named."""
    text = f"{title}. {summary}"
    hits = []
    for g in GAZETTEER:
        pos = None
        for w in g["en"]:
            m = re.search(r"\b" + re.escape(w) + r"\b", text, re.I)
            if m and (pos is None or m.start() < pos):
                pos = m.start()
        for w in g["bn"]:
            i = text.find(w)
            if i >= 0 and (pos is None or i < pos):
                pos = i
        if pos is not None:
            hits.append((pos, g))
    hits.sort(key=lambda h: h[0])
    fine = [g for _, g in hits if not g["coarse"]]
    chosen = fine[:limit] if fine else [g for _, g in hits][:1]
    return [{"lat": g["lat"], "lng": g["lng"], "known": True,
             "place_text": g["name"] + (" (whole city/district — check location)" if g["coarse"] else ""),
             "radius_m": (4000 if g["name"] == "Dhaka" else 8000) if g["coarse"] else 1500} for g in chosen]


def locate_many(title, summary, geocoder):
    """One or more locations for an article. Known places first (no web lookup needed), else the geocoder."""
    known = find_known_places(title, summary)
    if known:
        return known
    if BN_CHARS.search(f"{title}{summary}"):
        return []                                    # the map lookup only understands English names
    one = locate(title, summary, geocoder)
    return [one] if one else []


# ------------------------------------------------------------------ pipeline
def _km(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 12742 * asin(sqrt(h))


def build_rows(items, geocoder, max_age_days, expiry_days, now=None, translator=None):
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
        locs = locate_many(it["title"], it["summary"], geocoder)
        if not locs:
            stats["no_place"] += 1
            log(f"   no place found: {it['title'][:90]}")
            continue
        happened = (it["published"] or now).date().isoformat()
        added = 0
        for loc in locs:
            key = (loc["place_text"].lower(), happened, c["type"])      # same story from several outlets
            if key in seen_keys or (not loc.get("known") and any(
                    r["type"] == c["type"] and r["happened_on"] == happened and
                    _km(r["lat"], r["lng"], loc["lat"], loc["lng"]) < 4 for r in rows)):
                continue
            seen_keys.add(key)
            many = len(locs) > 1
            title_en, original = it["title"], None
            if BN_CHARS.search(title_en):                       # Bangla headline -> English (the boss reads English/Chinese)
                original = it["title"]
                title_en = (translator.title(original) if translator else None) or describe_bn(it["title"], it["summary"], loc["place_text"])
            slug = re.sub(r"[^a-z0-9]+", "-", loc["place_text"].split(" (")[0].lower()).strip("-")
            rows.append({
                "title": ((loc["place_text"].split(" (")[0] + ": ") if many else "") + title_en[:180],
                "title_original": original[:400] if original else None,
                "type": c["type"], "severity": c["severity"],
                "lat": round(loc["lat"], 6), "lng": round(loc["lng"], 6), "radius_m": loc["radius_m"],
                "source": "news", "source_url": it["link"] + ("#" + slug if many else ""),
                "place_text": loc["place_text"][:120],
                "status": "pending", "happened_on": happened,
                "expires_at": (now + dt.timedelta(days=expiry_days)).isoformat(),
            })
            added += 1
        if added:
            stats["kept"] += added
        else:
            stats["duplicate"] += 1
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

    rows, stats = build_rows(items, Geocoder(), max_age, expiry,
                             translator=Translator(email=os.environ.get("MYMEMORY_EMAIL")))
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
    log(f"Added {len(rows)} new PENDING risk area(s). Review them on the map (Admin button).")

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
