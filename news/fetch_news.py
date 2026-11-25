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
    NEWS_MAX_AGE_DAYS      ignore articles older than this (default 4)
    NEWS_KEEP_DAYS         waiting / rejected news older than this is deleted; APPROVED items are never deleted (default 4)

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

try:                                    # run as `python news/fetch_news.py` or imported as news.fetch_news
    from . import places as places_mod, story, verify, article
except ImportError:
    import places as places_mod
    import story
    import verify
    import article

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
    r"road ?blocks?|roadblock|blockade[sd]?|barricad(?:e|es|ed|ing)|"
    r"block(?:ed|ing|s)?\s+(?:the\s+)?(?:\S+\s+){0,3}(?:highway|road|expressway|bypass)|"
    r"(?:highway|road|expressway)\s+(?:was\s+|were\s+|remained\s+)?blocked)\b", re.I)

# A road being blocked counts even for "garment workers" or "factory" stories (those words only rule out gas/boiler blasts)
BLOCKAGE = re.compile(
    r"\b(road ?blocks?|roadblock|blockade[sd]?|barricad(?:e|es|ed|ing)|"
    r"block(?:ed|ing|s)?\s+(?:the\s+)?(?:\S+\s+){0,3}(?:highway|road|expressway|bypass)|"
    r"(?:highway|road|expressway)\s+(?:was\s+|were\s+|remained\s+)?blocked)\b", re.I)

# Announced or threatened disruption (not happening yet): hartal, blockade programme, transport strike...
PLANNED = re.compile(
    r"\b(hartal|blockade programmes?|transport (?:workers'? )?strike|truck(?:ers| owners)'? strike|lorry (?:workers'? )?strike|"
    r"paribahan strike|go(?:es|ing)? on strike|work abstention|ultimatum|"
    r"announce[sd]? (?:a |an )?(?:road |highway )?(?:blockade|hartal|strike)|"
    r"(?:will|to|plan to|plans to|threaten(?:s|ed)? to|vow(?:s|ed)? to|warn(?:s|ed)? (?:of|to))\s+(?:block|blockade|seal off|barricade)\s+(?:the\s+)?(?:\S+\s+){0,2}(?:highway|road|roads|expressway)|"
    r"(?:highway|road) blockade (?:programmes?|call|threat))\b", re.I)
BN_PLANNED = ("হরতাল", "পরিবহন ধর্মঘট", "পরিবহন শ্রমিক ধর্মঘট", "অবরোধের ডাক", "অবরোধ কর্মসূচি", "অবরোধের কর্মসূচি",
              "অবরোধের হুমকি", "আলটিমেটাম", "অবরোধের ঘোষণা", "সড়ক অবরোধের", "মহাসড়ক অবরোধের", "ধর্মঘটের ডাক")
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

DISTRICT_BN = {
    "Bagerhat": "বাগেরহাট", "Bandarban": "বান্দরবান", "Barguna": "বরগুনা", "Barishal": "বরিশাল", "Bhola": "ভোলা",
    "Bogura": "বগুড়া", "Brahmanbaria": "ব্রাহ্মণবাড়িয়া", "Chandpur": "চাঁদপুর", "Chapainawabganj": "চাঁপাইনবাবগঞ্জ",
    "Chattogram": "চট্টগ্রাম", "Chuadanga": "চুয়াডাঙ্গা", "Cumilla": "কুমিল্লা", "Cox's Bazar": "কক্সবাজার", "Dhaka": "ঢাকা",
    "Dinajpur": "দিনাজপুর", "Faridpur": "ফরিদপুর", "Feni": "ফেনী", "Gaibandha": "গাইবান্ধা", "Gazipur": "গাজীপুর",
    "Gopalganj": "গোপালগঞ্জ", "Habiganj": "হবিগঞ্জ", "Jamalpur": "জামালপুর", "Jashore": "যশোর", "Jhalokathi": "ঝালকাঠি",
    "Jhenaidah": "ঝিনাইদহ", "Joypurhat": "জয়পুরহাট", "Khagrachhari": "খাগড়াছড়ি", "Khulna": "খুলনা", "Kishoreganj": "কিশোরগঞ্জ",
    "Kurigram": "কুড়িগ্রাম", "Kushtia": "কুষ্টিয়া", "Lakshmipur": "লক্ষ্মীপুর", "Lalmonirhat": "লালমনিরহাট", "Madaripur": "মাদারীপুর",
    "Magura": "মাগুরা", "Manikganj": "মানিকগঞ্জ", "Meherpur": "মেহেরপুর", "Moulvibazar": "মৌলভীবাজার", "Munshiganj": "মুন্সিগঞ্জ",
    "Mymensingh": "ময়মনসিংহ", "Naogaon": "নওগাঁ", "Narail": "নড়াইল", "Narayanganj": "নারায়ণগঞ্জ", "Narsingdi": "নরসিংদী",
    "Natore": "নাটোর", "Netrokona": "নেত্রকোনা", "Nilphamari": "নীলফামারী", "Noakhali": "নোয়াখালী", "Pabna": "পাবনা",
    "Panchagarh": "পঞ্চগড়", "Patuakhali": "পটুয়াখালী", "Pirojpur": "পিরোজপুর", "Rajbari": "রাজবাড়ী", "Rajshahi": "রাজশাহী",
    "Rangamati": "রাঙামাটি", "Rangpur": "রংপুর", "Satkhira": "সাতক্ষীরা", "Shariatpur": "শরীয়তপুর", "Sherpur": "শেরপুর",
    "Sirajganj": "সিরাজগঞ্জ", "Sunamganj": "সুনামগঞ্জ", "Sylhet": "সিলেট", "Tangail": "টাঙ্গাইল", "Thakurgaon": "ঠাকুরগাঁও",
}
DISTRICT_ALT = {"Chittagong": "Chattogram", "Comilla": "Cumilla", "Barisal": "Barishal", "Jessore": "Jashore", "Bogra": "Bogura",
                "Chapai Nawabganj": "Chapainawabganj", "Maulvibazar": "Moulvibazar", "Brahmanbaria": "Brahmanbaria"}
# Districts that touch each other, so a story naming both is not a contradiction
NEIGHBOURS = {
    "Dhaka": {"Gazipur", "Narayanganj", "Munshiganj", "Manikganj", "Narsingdi"},
    "Gazipur": {"Dhaka", "Narsingdi", "Kishoreganj", "Mymensingh", "Tangail", "Narayanganj", "Manikganj"},
    "Narayanganj": {"Dhaka", "Gazipur", "Munshiganj", "Narsingdi", "Cumilla", "Chandpur"},
    "Narsingdi": {"Gazipur", "Dhaka", "Narayanganj", "Kishoreganj", "Brahmanbaria", "Cumilla"},
    "Brahmanbaria": {"Cumilla", "Habiganj", "Narsingdi", "Kishoreganj", "Sunamganj"},
    "Cumilla": {"Brahmanbaria", "Feni", "Chandpur", "Narayanganj", "Munshiganj", "Noakhali", "Narsingdi", "Lakshmipur"},
    "Feni": {"Cumilla", "Chattogram", "Noakhali"},
    "Chattogram": {"Feni", "Cox's Bazar", "Rangamati", "Khagrachhari", "Bandarban", "Noakhali"},
    "Sylhet": {"Sunamganj", "Moulvibazar", "Habiganj"},
    "Habiganj": {"Sylhet", "Moulvibazar", "Brahmanbaria", "Sunamganj", "Kishoreganj"},
    "Moulvibazar": {"Sylhet", "Habiganj"},
    "Sunamganj": {"Sylhet", "Habiganj", "Netrokona", "Kishoreganj", "Brahmanbaria"},
    "Kishoreganj": {"Gazipur", "Narsingdi", "Brahmanbaria", "Habiganj", "Netrokona", "Mymensingh", "Sunamganj"},
    "Tangail": {"Gazipur", "Manikganj", "Mymensingh", "Jamalpur", "Sirajganj", "Pabna"},
}

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
Sitakunda||সীতাকুণ্ড|22.6190|91.6690
Mirsarai|Mirsharai|মিরসরাই|22.7770|91.5810
Laksam||লাকসাম|23.2480|91.1310
Chandina||চান্দিনা|23.4690|91.0030
Daudkandi||দাউদকান্দি|23.5400|90.7200
Nabinagar||নবীনগর|23.8900|91.2000
Sreemangal|Srimangal|শ্রীমঙ্গল|24.3065|91.7296
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
Feni||ফেনী|23.0159|91.3976|c
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
POINT_SUFFIX = r"(?:[Bb]ridge|[Ff]lyover|[Uu]pazila|Bazar|Bazaar|[Ii]ntersection|[Cc]rossing|Chattar|Mor|Bus Stand|College|University|Medical College|Hospital|School|Madrasa|Institute|Stadium|Airport|Station|Market|Park|Mosque|Mandir|Ghat|Terminal|Cantonment|Jail|Court|Port|Tower|Square|Circle)"
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
    if _has(text, BN_PLANNED):
        return {"type": "other", "severity": 2, "deaths": 0, "planned": True}
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
    if PLANNED.search(text):
        return {"type": "other", "severity": 2, "deaths": 0, "planned": True}
    strong = bool(BLOCKAGE.search(text)) or (bool(SECURITY_STRONG.search(text)) and not NOT_SECURITY.search(text))
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
    """Return {lat, lng, place_text, radius_m} or None.
    If the story names a district ("... in Rajshahi"), every lookup is narrowed to it, so a name that also
    exists elsewhere (a bank head office, a street) cannot land in Dhaka by accident."""
    named = [d for _, d in districts_named(blank_routes(title))] or [d for _, d in districts_named(blank_routes(summary))]
    district = named[0] if named else None
    for name, district_only in place_candidates(title, summary)[:4]:   # few tries per article: Nominatim allows 1 request/second
        if district and name in DISTRICT_SET_CASE:
            continue
        pt = geocoder.lookup(f"{name}, {district}" if district else name)
        if pt:
            return {"lat": pt[0], "lng": pt[1],
                    "place_text": name + (" (district only — check location)" if district_only else ""),
                    "radius_m": 2000 if district_only else 800}
    return None


ROUTE_WORDS = re.compile(
    r"\b(?:to|towards?|for|from|via|bound for)\s+(?:the\s+)?[A-Z][\w'’]+(?:\s+[A-Z][\w'’]+)?"      # "from Dhaka to Feni"
    r"|[A-Z][\w'’]+(?:[-–][A-Z][\w'’]+)+\s+(?i:highway|road|expressway|bypass|route|corridor)"   # "Dhaka-Sylhet highway" (not "Savar-Ashulia")
    r"|[A-Z][\w'’]+[-–]bound")
ROUTE_BN = re.compile(r"[\u0980-\u09FF]+[-–][\u0980-\u09FF]+\s*(?:মহাসড়ক|সড়ক|হাইওয়ে)"          # ঢাকা-সিলেট মহাসড়ক
                      r"|[\u0980-\u09FF]+(?:গামী|মুখী|অভিমুখে)|[\u0980-\u09FF]+\s+থেকে")


def blank_routes(text):
    """Blank out where a vehicle came from / was heading to, and road names: the incident is not there.
    Same length as the input, so positions still line up with the original text."""
    blank = lambda m: " " * len(m.group(0))
    return ROUTE_BN.sub(blank, ROUTE_WORDS.sub(blank, text))


def districts_named(text):
    """[(position, district)] for every district named in the text (English or Bangla)."""
    out = []
    for d in DISTRICTS:
        for w in (d, DISTRICT_BN.get(d, "")) + tuple(a for a, c in DISTRICT_ALT.items() if c == d):
            if not w:
                continue
            m = re.search(r"\b" + re.escape(w) + r"\b", text) if w.isascii() else None
            i = m.start() if m else (text.find(w) if not w.isascii() else -1)
            if i >= 0:
                out.append((i, d))
    return sorted(out)


def home_district(g):
    """The district a known place belongs to: itself if it is a whole city, else the nearest whole city."""
    best, bd = None, 55
    for c in GAZETTEER:
        if c["coarse"] and c["name"] in DISTRICT_SET_CASE:
            d = _km(g["lat"], g["lng"], c["lat"], c["lng"])
            if d < bd:
                best, bd = c["name"], d
    return best


DISTRICT_SET_CASE = set(DISTRICTS)


def region_conflict(title, summary, known_places):
    """If the story clearly names a district that the matched place is NOT in (a "Rajshahi" story that
    mentions "the capital" or a street name that also exists in Dhaka), return that district; else None."""
    if not known_places:
        return None
    homes = {g["home"] for g in known_places if g.get("home")}
    if not homes:
        return None
    ok = set(homes)
    for h in homes:
        ok |= NEIGHBOURS.get(h, set())
    for text in (blank_routes(title), blank_routes(summary)):          # the headline counts first
        for _, d in districts_named(text):
            if d not in ok:
                return d
    return None


# Mirpur is split into numbered sections, about a kilometre apart. "Mirpur-1" must not be drawn at Mirpur-10.
MIRPUR_SECTIONS = {1: (23.7957, 90.3535), 2: (23.8068, 90.3557), 10: (23.8069, 90.3687),
                   11: (23.8190, 90.3655), 12: (23.8283, 90.3637)}
RE_MIRPUR_N = re.compile(r"(?:Mirpur|মিরপুর)[-\s]?([0-9০-৯]{1,2})(?![0-9০-৯])", re.I)


def mirpur_sections(text):
    """Return ([hits], text_with_those_mentions_blanked)."""
    hits = []

    def take(m):
        n = int(m.group(1).translate(BN_DIGITS))
        pt = MIRPUR_SECTIONS.get(n)
        base = {"known": True, "home": "Dhaka", "radius_m": 600 if pt else 1000, "pos": m.start()}
        if pt:
            hits.append({**base, "lat": pt[0], "lng": pt[1], "place_text": f"Mirpur-{n}"})
        else:                                           # section we have no exact point for: say so, do not guess
            hits.append({**base, "lat": 23.8069, "lng": 90.3687, "place_text": f"Mirpur-{n} (exact block not in my list — check location)"})
        return " " * len(m.group(0))
    return hits, RE_MIRPUR_N.sub(take, text)


# ------------------------------------------------------------------ highways
# Approximate centre-lines (lat, lng) of the main highways. A highway is hundreds of km long, so a story that
# says "Dhaka-Mymensingh highway in Gazipur" is pinned where that highway passes through Gazipur.
CORRIDORS = [
    {"name": "Dhaka-Mymensingh highway", "names": {"dhaka", "mymensingh", "gazipur", "tongi", "bhaluka", "joydebpur"},
     "line": [(23.8500, 90.4000), (23.8918, 90.4058), (23.9999, 90.4203), (24.2000, 90.3500), (24.4000, 90.3000), (24.7471, 90.4203)]},
    {"name": "Dhaka-Chattogram highway", "names": {"dhaka", "chattogram", "cumilla", "feni", "daudkandi", "narayanganj", "sitakunda", "mirsarai", "laksam", "chandina"},
     "line": [(23.7104, 90.4344), (23.7000, 90.5000), (23.5400, 90.7200), (23.4690, 91.0030), (23.4607, 91.1809), (23.2480, 91.1310),
              (23.0159, 91.3976), (22.7770, 91.5810), (22.6190, 91.6690), (22.3569, 91.7832)]},
    {"name": "Dhaka-Sylhet highway", "names": {"dhaka", "sylhet", "bhairab", "brahmanbaria", "habiganj", "moulvibazar", "sreemangal", "narsingdi", "madhabdi", "sarail", "ashuganj"},
     "line": [(23.7000, 90.5000), (23.8541, 90.6672), (24.0522, 90.9764), (24.0735, 91.1148), (24.3745, 91.4155),
              (24.3065, 91.7296), (24.4829, 91.7774), (24.8949, 91.8687)]},
    {"name": "Dhaka-Aricha highway", "names": {"dhaka", "aricha", "savar", "ashulia", "manikganj", "gabtoli"},
     "line": [(23.7786, 90.3434), (23.8583, 90.2667), (23.8617, 90.0003), (23.7800, 89.7800)]},
    {"name": "Dhaka-Tangail highway", "names": {"dhaka", "tangail", "gazipur", "joydebpur"},
     "line": [(23.9999, 90.4203), (24.1200, 90.2600), (24.2513, 89.9167)]},
]
ALIASES = {"chittagong": "chattogram", "comilla": "cumilla", "barisal": "barishal", "jessore": "jashore", "joydevpur": "joydebpur"}
BN_TO_EN = {v: k.lower() for k, v in DISTRICT_BN.items()}
BN_TO_EN.update({"জয়দেবপুর": "joydebpur", "টঙ্গী": "tongi", "ভালুকা": "bhaluka", "ভৈরব": "bhairab", "সাভার": "savar", "আরিচা": "aricha"})
RE_HWY_EN = re.compile(r"\b([A-Z][\w']+)\s*[-–/]\s*([A-Z][\w']+)\s+(?:[Hh]ighway|[Rr]oad|[Ee]xpressway|[Bb]ypass|[Mm]ahasarak)\b")
RE_HWY_BN = re.compile(r"([\u0980-\u09FF]+)\s*[-–]\s*([\u0980-\u09FF]+)\s*(?:মহাসড়ক|সড়ক|হাইওয়ে)")


def find_corridor(text):
    """The known highway a story names ("Dhaka-Mymensingh highway"), or None."""
    pairs = [(a.lower(), b.lower()) for a, b in RE_HWY_EN.findall(text)]
    pairs += [(BN_TO_EN.get(a, a), BN_TO_EN.get(b, b)) for a, b in RE_HWY_BN.findall(text)]
    for a, b in pairs:
        a, b = ALIASES.get(a, a), ALIASES.get(b, b)
        for c in CORRIDORS:
            if a in c["names"] and b in c["names"] and a != b:
                return c
    return None


def snap_to_line(lat, lng, line):
    """Nearest point on a polyline. Returns (lat, lng, km)."""
    from math import cos, radians
    best = (lat, lng, 1e9)
    for (a1, o1), (a2, o2) in zip(line, line[1:]):
        kx = 111.0 * cos(radians(lat))
        ax, ay, bx, by = (o1 - lng) * kx, (a1 - lat) * 111.0, (o2 - lng) * kx, (a2 - lat) * 111.0
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, -(ax * dx + ay * dy) / ((dx * dx + dy * dy) or 1)))
        px, py = ax + t * dx, ay + t * dy
        d = (px * px + py * py) ** 0.5
        if d < best[2]:
            best = (lat + py / 111.0, lng + px / kx, d)
    return best


def place_on_corridor(known, corridor):
    """Whole-district hits become a point on the named highway inside that district; exact places stay put."""
    out = []
    for g in known:
        if g.get("place_text", "").endswith("check location)") and "whole city/district" in g["place_text"]:
            la, ln, km = snap_to_line(g["lat"], g["lng"], corridor["line"])
            if km <= 35:
                base = g["place_text"].split(" (")[0]
                g = {**g, "lat": la, "lng": ln, "radius_m": 1000,
                     "place_text": f"{corridor['name']}, {base} (on the highway — approximate, check location)"}
        out.append(g)
    return out


# ------------------------------------------------------------------ stories about other countries
FOREIGN_OUTLETS = re.compile(r"\s[-–|]\s*(UrduPoint|Dawn|Geo News|Express Tribune|The News International|Times of India|Hindustan Times|NDTV|The Hindu|"
                            r"Tribune India|India Today|Indian Express|Dainik Jagran|Dainik Bhaskar|Amar Ujala|Zee News|News18|Gulf News|Khaleej Times|"
                            r"Arab News|Al Jazeera|Anadolu|Xinhua|Kathmandu Post|Colombo Gazette|Daily Mirror Sri Lanka)\b", re.I)
FOREIGN = re.compile(r"\b(Uttar Pradesh|Kannauj|Rajasthan|Gujarat|Bihar|Maharashtra|West Bengal|Kerala|Tamil Nadu|Karnataka|Odisha|Haryana|Madhya Pradesh|"
                     r"Lahore|Karachi|Islamabad|Peshawar|Quetta|Sindh|Balochistan|Khyber|Chak \d+|Iran|Iraq|Syria|Israel|Gaza|Palestin\w*|Lebanon|Yemen|Afghanistan|Pakistan|India|Indian|Nepal|Bhutan|Sri Lanka|Myanmar|"
                     r"Thailand|Malaysia|Indonesia|China|Japan|Korea|Russia|Ukraine|Turkey|Saudi|Egypt|Nigeria|Kenya|Ethiopia|Sudan|Mexico|"
                     r"Brazil|Peru|Philippines|Vietnam|Kolkata|Delhi|Mumbai|Assam|Tripura|Kashmir|Texas|California|Florida|London|Paris|"
                     r"US|U\.S\.|UK|U\.K\.)\b")


def is_foreign_story(title, summary):
    """A story about another country (an Iran bus crash) that names no place in Bangladesh."""
    text = f"{title}. {summary}"
    if not FOREIGN.search(text):
        return False
    if districts_named(text) or find_known_places(title, summary):
        return False
    return True


def find_known_places(title, summary, limit=5):
    """Places from the built-in list (Dhaka areas, Sylhet, Brahmanbaria...), in the order they are
    mentioned. Neighbourhoods/towns win; the whole city/district is used only if nothing finer is named."""
    text = blank_routes(f"{title}. {summary}")
    sections, text = mirpur_sections(text)
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
    if sections:                                        # exact Mirpur sections beat the general "Mirpur" and whole-city hits
        pins = sorted(sections, key=lambda h: h["pos"])[:limit]
        return [{k: v for k, v in h.items() if k != "pos"} for h in pins]
    return [{"lat": g["lat"], "lng": g["lng"], "known": True, "home": home_district(g),
             "place_text": g["name"] + (" (whole city/district — check location)" if g["coarse"] else ""),
             "radius_m": 2000 if g["coarse"] else 800} for g in chosen]


# Score a candidate place. Higher wins. The numbers only need to rank things sensibly:
#   how specific the place is  +  what part it plays in the story  +  where in the story it is named
LEVEL_SCORE = {"area": 40, "union": 34, "upazila": 30, "city": 18, "district": 14}
ROLE_SCORE = {"dateline": 30, "locative": 28, "neutral": 0, "origin": -45}
LEVEL_RADIUS = {"area": 800, "union": 1200, "upazila": 1500, "district": 2000}   # metres: smaller = more honest about how exact the spot is
REFINE_KM = {"district": 45, "upazila": 15, "union": 8}


def known_hits(text):
    """Every place from the built-in list in the text: [{pos,end,name,level,lat,lng,place_text,radius_m}] (Mirpur sections included)."""
    out, text2 = [], text

    def take(m):
        n = int(m.group(1).translate(BN_DIGITS))
        pt = MIRPUR_SECTIONS.get(n)
        txt = f"Mirpur-{n}" if pt else f"Mirpur-{n} (exact block not in my list — check location)"
        out.append({"pos": m.start(), "end": m.end(), "name": f"Mirpur-{n}", "level": "area", "district": "Dhaka",
                    "lat": (pt or (23.8069, 90.3687))[0], "lng": (pt or (23.8069, 90.3687))[1],
                    "place_text": txt, "radius_m": 600 if pt else 1000})
        return " " * len(m.group(0))
    text2 = RE_MIRPUR_N.sub(take, text)
    for g in GAZETTEER:
        best = None
        for w in g["en"]:
            m = re.search(r"\b" + re.escape(w) + r"\b", text2, re.I)
            if m and (best is None or m.start() < best[0]):
                best = (m.start(), m.end())
        for w in g["bn"]:
            hit = places_mod.bn_find(text2, w) if BN_CHARS.search(text2) else None
            if hit and (best is None or hit[0] < best[0]):
                best = hit
        if best:
            coarse = g["coarse"]
            out.append({"pos": best[0], "end": best[1], "name": g["name"], "level": "city" if coarse else "area", "district": None,
                        "lat": g["lat"], "lng": g["lng"], "coarse": coarse,
                        "place_text": g["name"] + (" (whole city/district — check location)" if coarse else ""),
                        "radius_m": 2000 if coarse else 800})
    return out


def _official_text(e):
    if e["level"] == "district":
        return f"{e['name']} (district only — check location)"
    if e["level"] == "upazila":
        return f"{e['name']}, {e['district']} (upazila centre — check exact spot)"
    return f"{e['name']}, {e['district']} (area centre — check exact spot)"


STOPWORDS_FZ = {w.lower() for w in """Police Highway Passenger Several Another Between Dhaka-bound Cocktail Explosion Bangladesh Crossing Station Thursday Wednesday Tuesday
Saturday Sunday Monday Friday Yesterday Morning Evening Afternoon Overnight Madrasa Hospital Medical College University School Market Bazaar Factory""".split()}


def clean_title(title):
    """Google News titles end with the outlet: "Bus torched in Sylhet - Dhaka Post". The outlet is not a place."""
    title = title.replace("’", "'")
    return re.sub(r"\s+[-–|]\s+[^-–|]{3,60}$", "", title) if re.search(r"\s+[-–|]\s+[^-–|]{3,60}$", title) and len(title) > 30 else title


def analyse_story(title, summary, geocoder):
    """Work out where a story happened. Returns (locations, reason); reason is None, "abroad" or "no_place".

    The ways a location is found (all of them are combined and scored, nothing is trusted alone):
      1. built-in neighbourhoods (Dhaka areas, Mirpur sections, corridor towns)       -> exact
      2. official upazilas and unions (every one in Bangladesh), English and Bangla    -> area centre
      3. official district names                                                       -> whole district
      4. the part the place plays: "in X", "X:" at the start, "X police station" = here;
         "resident of X", "hailing from X", "from X to Y" = NOT here
      5. duplicate names (a Rampura in Dhaka and one in Rajshahi) settled by the district the story names
      6. highway + place ("Dhaka-Mymensingh highway in Gazipur") -> point on that highway inside that district
      7. street/market/bridge names found with the map lookup, narrowed to the district
      8. final check: the pin must be inside (or right beside) a district the story names
      9. stories about other countries (expatriates, "died in Saudi Arabia") are dropped
    """
    eng = places_mod.engine()
    if FOREIGN_OUTLETS.search(title):                           # a foreign newspaper: the story is not about Bangladesh
        return [], "abroad"
    title = clean_title(title)
    summary = (summary or "").replace("’", "'")
    full = f"{title}. {summary}"
    text, tl = blank_routes(full), len(title)
    cands = []
    for h in known_hits(text):
        h["source"] = "curated"
        cands.append(h)
    named_all = []                                               # districts the story names, with their role
    if eng:
        for m in eng.mentions(text):
            ents = m["entries"]
            for e in ents:
                if e["level"] == "district":
                    named_all.append({**e, "pos": m["pos"], "end": m["end"], "role": story.role_of(text, m["pos"], m["end"], tl)})
        for m in eng.mentions(text):
            for e in m["entries"]:
                if e["level"] == "district":
                    cands.append({"pos": m["pos"], "end": m["end"], "name": e["name"], "level": "district", "district": e["district"],
                                  "lat": e["lat"], "lng": e["lng"], "place_text": _official_text(e), "radius_m": 2000, "source": "official"})
        target = [d["district"] for d in named_all if d["role"] != "origin"]
        for e in eng.resolve(text, named=target or None):
            cands.append({"pos": e["pos"], "end": e["end"], "name": e["name"], "level": e["level"], "district": e["district"],
                          "lat": e["lat"], "lng": e["lng"], "place_text": _official_text(e), "radius_m": LEVEL_RADIUS[e["level"]], "source": "official"})
    else:
        target = []
    if eng:                                                     # misspelt names after "in/at/near": Jhalokati, Barolekha ...
        covered = [(c["pos"], c["end"]) for c in cands]
        for m in re.finditer(r"\b[A-Z][a-z']{5,}\b", text):
            if any(a_ <= m.start() < b_ for a_, b_ in covered) or m.group(0).lower() in STOPWORDS_FZ:
                continue
            if story.role_of(text, m.start(), m.end(), tl) not in ("locative", "dateline"):
                continue
            ents = eng.fuzzy(m.group(0))
            if ents and len({e["district"] for e in ents}) == 1:
                e = ents[0]
                cands.append({"pos": m.start(), "end": m.end(), "name": e["name"], "level": e["level"], "district": e["district"],
                              "lat": e["lat"], "lng": e["lng"], "place_text": _official_text(e), "radius_m": LEVEL_RADIUS[e["level"]],
                              "source": "official", "fuzzy": True})
    for c in cands:
        c["role"] = story.role_of(text, c["pos"], c["end"], tl)
        if eng and not c.get("district"):
            c["district"] = eng.district_at(c["lat"], c["lng"])

    spans = _sentence_spans(text)
    for c in cands:                                             # does the sentence itself describe an incident?
        a_, b_ = _span_of(spans, c["pos"])
        i_ = next((k for k, (x, y) in enumerate(spans) if x == a_), 0)
        near = " ".join(text[x:y] for x, y in spans[max(0, i_ - 1):i_ + 2])        # a list of places often follows the sentence that says what happened
        c["evown"] = c["pos"] < tl or bool(EVENT_RE.search(text[a_:b_]))
        c["evsent"] = c["evown"] or bool(EVENT_RE.search(near))
        c["_span"] = (a_, b_)
    if eng:                                                     # a place must agree with the district written in ITS OWN sentence
        def clash(c):
            if c["level"] == "district":
                return False
            sd = [d["district"] for d in named_all if c["_span"][0] <= d["pos"] <= c["_span"][1] and d["role"] != "origin"]
            return bool(sd) and not eng.fits(c["lat"], c["lng"], sd)
        cands = [c for c in cands if not clash(c)]

    bd = [{"pos": c["pos"], "end": c["end"], "role": c["role"]} for c in cands]
    if story.is_abroad(full, bd, tl):
        return [], "abroad"

    # Rule 8: keep only pins that sit in a district the story names (the "capital" in a Rajshahi story is not Dhaka)
    if eng and target:
        cands = [c for c in cands if eng.fits(c["lat"], c["lng"], target)]
    good = [c for c in cands if c["role"] != "origin"]
    if cands and not good:
        return [], "no_place"                                      # the only places named are where people come from

    if good:
        for c in good:
            c["score"] = (LEVEL_SCORE[c["level"]] + ROLE_SCORE[c["role"]] + (12 if c["pos"] < tl else 4 if c["pos"] < tl + 250 else 0)
                          + (3 if c["source"] == "curated" else 0) + (16 if c["evown"] else 8 if c["evsent"] else -12 if c["pos"] >= tl else 0))
        good.sort(key=lambda c: (-c["score"], c["pos"]))
        uniq, names = [], set()
        for c in good:                                               # the same place found twice (built-in + official): keep the best
            if c["name"].lower() not in names:
                names.add(c["name"].lower())
                uniq.append(c)
        best, good = uniq[0], uniq
        chosen = [best]
        others = []                                                 # "bomb blast in Dhaka, bus attacked in Cumilla": one pin per place
        seen_d = {best["district"]}
        for c in good[1:]:
            in_title_list = c["pos"] < tl and c["role"] == "neutral" and c["level"] in ("city", "district", "upazila")
            if c["district"] not in seen_d and (c["role"] in ("locative", "dateline") or in_title_list) and (c["evsent"] or in_title_list) and len(others) < 2:
                seen_d.add(c["district"])
                others.append(c)
        if best["level"] in ("area", "union"):                      # a story naming several neighbourhoods gets one pin each
            more = [c for c in good[1:] if c["level"] in ("area", "union") and c["district"] == best["district"] and c["evsent"]]
            chosen = sorted([best] + more, key=lambda c: c["pos"])[:5]
        else:
            chosen = [best]
        chosen = chosen + others
        corridor = find_corridor(full)
        out = []
        for c in chosen:
            loc = {"lat": c["lat"], "lng": c["lng"], "place_text": c["place_text"], "radius_m": c["radius_m"], "known": True, "district": c["district"],
                   "name": c["name"], "level": c["level"], "role": c["role"], "ev": _snippet(full, c["pos"], c["end"]), "evsent": c["evsent"],
                   "source_kind": c["source"]}
            if c["level"] in ("city", "district", "upazila", "union") and not c.get("refined"):
                better = _refine(loc, c, title, summary, geocoder, eng)
                if better:
                    loc = {**better, "role": c["role"], "ev": loc["ev"] + " … " + better.get("ev", ""), "evsent": c["evsent"]}
            if corridor and loc.get("known") and c["level"] in ("city", "district", "upazila", "union"):
                loc = place_on_corridor([{**loc, "place_text": loc["place_text"] if "check" in loc["place_text"] else loc["place_text"] + " (check location)"}], corridor)[0]
            if corridor:
                loc["corridor"] = corridor["name"]
                loc["corridor_km"] = snap_to_line(loc["lat"], loc["lng"], corridor["line"])[2]
            out.append(loc)
        return out, None

    # Nothing in the built-in or official lists: use the map lookup, then check the result against the story
    if BN_CHARS.search(full):
        return [], "no_place"
    one = locate(title, summary, geocoder)
    corridor = find_corridor(full)
    if not one and corridor:                                    # "Dhaka-Aricha highway blocked", no town named: middle of the highway, flagged
        la, ln = corridor["line"][len(corridor["line"]) // 2]
        return [{"lat": la, "lng": ln, "place_text": f"{corridor['name']} (exact spot not stated — check location)", "radius_m": 2000,
                 "known": True, "district": eng.district_at(la, ln) if eng else None, "name": corridor["name"], "level": "highway",
                 "role": "neutral", "ev": corridor["name"], "corridor": corridor["name"], "corridor_km": 0.0}], None
    if not one:
        return [], "no_place"
    one["known"] = False
    one.setdefault("level", "district" if "district only" in one["place_text"] else "landmark")
    one.setdefault("name", one["place_text"].split(",")[0])
    one.setdefault("role", "locative")
    one.setdefault("ev", one["place_text"])
    one.setdefault("district", eng.district_at(one["lat"], one["lng"]) if eng else None)
    return [one], None


EVENT_RE = re.compile(r"\b(block\w*|torch\w*|set (?:on )?fire|set ablaze|ablaze|arson|vandali[sz]\w*|clash\w*|kill\w*|dead|died|injur\w*|"
                      r"protest\w*|demonstrat\w*|rall(?:y|ies)|explo\w*|blast\w*|cocktail|bomb\w*|attack\w*|hijack\w*|robb\w*|mugg\w*|"
                      r"crash\w*|collid\w*|collision|rams?|hit|struck|shot|gunfire|stab\w*|riot\w*|lathi|tear ?gas|halted|standstill|gridlock|"
                      r"strike|hartal|shutdown|unrest|stage\w*)\b|ককটেল|বিস্ফোরণ|আগুন|অবরোধ|সংঘর্ষ|নিহত|আহত|দুর্ঘটনা|বিক্ষোভ", re.I)


def _sentence_spans(text):
    spans, start = [], 0
    for m in re.finditer(r"(?<=[.!?।])\s+|\n+", text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return spans


def _span_of(spans, pos):
    for a, b in spans:
        if a <= pos <= b:
            return a, b
    return 0, len(spans) and spans[-1][1]


def _snippet(text, a, b):
    return re.sub(r"\s+", " ", text[max(0, a - 50):b + 60]).strip()


def _refine(loc, c, title, summary, geocoder, eng):
    """Try to improve a whole-district / area-centre pin with a street, market or bridge named in the story."""
    ctx = c["district"] if c["level"] in ("district", "city") else f"{c['name']}, {c['district']}"
    limit = REFINE_KM.get(c["level"] if c["level"] != "city" else "district", 20)
    tried = 0
    for name, district_only in place_candidates(title, summary):
        if district_only or name in DISTRICT_SET_CASE or name.lower() == c["name"].lower() or tried >= 2:
            continue
        tried += 1
        pt = geocoder.lookup(f"{name}, {ctx}")
        if pt and (not eng or eng.fits(pt[0], pt[1], [c["district"]])) and _km(pt[0], pt[1], c["lat"], c["lng"]) <= limit:
            return {"lat": pt[0], "lng": pt[1], "place_text": f"{name}, {c['district']}", "radius_m": 800, "known": False, "district": c["district"],
                    "name": name, "level": "landmark", "ev": _snippet(f"{title}. {summary}", f"{title}. {summary}".find(name), f"{title}. {summary}".find(name) + len(name))}
    return None


def locate_many(title, summary, geocoder):
    """One or more locations for an article (see analyse_story)."""
    return analyse_story(title, summary, geocoder)[0]


# ------------------------------------------------------------------ pipeline
def _km(lat1, lng1, lat2, lng2):
    from math import radians, sin, cos, asin, sqrt
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 12742 * asin(sqrt(h))


MAX_ARTICLES_PER_RUN = 70


def named_districts(text, title_len):
    eng = places_mod.engine()
    if not eng:
        return []
    t = blank_routes(text)
    return [m["entries"][0]["district"] for m in eng.mentions(t)
            if m["entries"][0]["level"] == "district" and story.role_of(t, m["pos"], m["end"], title_len) != "origin"]


def build_rows(items, geocoder, max_age_days, expiry_days, now=None, translator=None, reader=None, known_urls=()):
    """Turn feed items into rows ready for the risk_areas table. Returns (rows, stats)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    stats = {"seen": 0, "too_old": 0, "not_incident": 0, "no_place": 0, "duplicate": 0, "kept": 0, "held": 0, "articles_read": 0}
    eng, read_budget = places_mod.engine(), MAX_ARTICLES_PER_RUN
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
        art = {}
        if reader and read_budget > 0 and it["link"] not in known_urls:          # step 1: read the article itself
            read_budget -= 1
            art = reader(it["link"]) or {}
            stats["articles_read"] += 1 if art else 0
            if art.get("published"):                                              # the real date beats Google's listing date
                it["published"] = art["published"]
                if (now - it["published"]).days > max_age_days:
                    stats["too_old"] += 1
                    continue
        body = art.get("text") or ""
        locs, why = analyse_story(it["title"], (it["summary"] + " " + body).strip(), geocoder)
        if why == "abroad":
            stats["not_incident"] += 1
            log(f"   outside Bangladesh, skipped: {it['title'][:90]}")
            continue
        if not locs:
            stats["no_place"] += 1
            UNMAPPED.append(it["title"][:120])
            log(f"   no place found: {it['title'][:90]}")
            continue
        happened = (it["published"] or now).date().isoformat()
        added = 0
        full_text = f"{clean_title(it['title'])}. {it['summary']} {body}"
        tl = len(clean_title(it["title"]))
        t_locs, _ = analyse_story(it["title"], "", _NoWeb())                   # step 2: headline alone, read separately
        ctx = {"eng": eng, "title_districts": {l.get("district") for l in t_locs if l.get("district") and l.get("level") != "highway"},
               "named": named_districts(full_text, tl), "body_read": bool(body), "date_ok": bool(art.get("published")),
               "critical": bool(c.get("planned") or BLOCKAGE.search(full_text))}
        for loc in locs:
            key = (loc["place_text"].lower(), happened, c["type"])      # same story from several outlets
            if key in seen_keys or (not loc.get("known") and any(
                    r["type"] == c["type"] and r["happened_on"] == happened and
                    _km(r["lat"], r["lng"], loc["lat"], loc["lng"]) < 4 for r in rows)):
                continue
            seen_keys.add(key)
            checks = verify.run_checks(loc, ctx)                              # steps 3-8: independent checks on the pin
            conf, verdict, _issues = verify.grade(checks, ctx["critical"])
            many = len(locs) > 1
            title_en, original = it["title"], None
            if BN_CHARS.search(title_en):                       # Bangla headline -> English (the boss reads English/Chinese)
                original = it["title"]
                title_en = (translator.title(original) if translator else None) or describe_bn(it["title"], it["summary"], loc["place_text"])
            if c.get("planned"):
                title_en = "Possible blockade: " + title_en
            slug = re.sub(r"[^a-z0-9]+", "-", loc["place_text"].split(" (")[0].lower()).strip("-")
            rows.append({
                "title": ((loc["place_text"].split(" (")[0] + ": ") if many else "") + title_en[:180],
                "title_original": original[:400] if original else None,
                "type": c["type"], "severity": c["severity"],
                "lat": round(loc["lat"], 6), "lng": round(loc["lng"], 6), "radius_m": loc["radius_m"],
                "source": "news", "source_url": it["link"] + ("#" + slug if many else ""),
                "place_text": loc["place_text"][:120],
                "status": "pending" if verdict == "show" else "held", "happened_on": happened,
                "confidence": conf, "evidence": (loc.get("ev") or "")[:300], "checks": verify.summary(checks)[:900], "body_read": bool(body),
                "expires_at": (now + dt.timedelta(days=expiry_days)).isoformat(),
            })
            added += 1
            if verdict != "show":
                stats["held"] += 1
                log(f"   held back ({'; '.join(_issues)[:120]}): {it['title'][:70]}")
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


UNMAPPED = []                    # headlines that were incidents but had no usable place (listed in the run summary)


def cleanup_old(request, keep_days=4, today=None):
    """Delete waiting and rejected news older than keep_days. Approved items are NEVER touched."""
    today = today or dt.date.today()
    cutoff = (today - dt.timedelta(days=keep_days)).isoformat()
    gone = request("DELETE", f"/rest/v1/risk_areas?source=eq.news&status=in.(pending,rejected,held)&happened_on=lt.{cutoff}&select=id",
                   None, {"Prefer": "return=representation"}) or []
    request("DELETE", "/rest/v1/risk_areas?source=eq.news&status=eq.held", None, {"Prefer": "return=minimal"})   # held items are re-checked from scratch every run
    return len(gone)


class _NoWeb:
    def lookup(self, name):
        return None


def audit_row(row):
    """Why a stored WAITING row looks wrong ("abroad" / "wrong district"), or None if it is fine.
    Uses only the headline, so it costs no web lookups. Rows the admin has approved are never audited."""
    eng = places_mod.engine()
    if row.get("body_read"):                                   # verified against the full article already
        return None
    title = row.get("title_original") or row.get("title") or ""
    if "#" in (row.get("source_url") or ""):                   # several-pin stories carry a "Place: " prefix we added ourselves
        title = title.split(": ", 1)[-1]
    title = clean_title(title)
    if not title:
        return None
    locs, why = analyse_story(title, "", _NoWeb())
    if why == "abroad":
        return "abroad"
    if eng and row.get("lat") is not None:
        text = blank_routes(title)
        named = [m["entries"][0]["district"] for m in eng.mentions(text)
                 if m["entries"][0]["level"] == "district" and story.role_of(text, m["pos"], m["end"], len(title)) != "origin"]
        if named and not eng.fits(row["lat"], row["lng"], named):
            return "wrong district"
    return None


def audit_pending(request):
    """Self-heal: delete waiting news whose pin is in the wrong district or that is about another country.
    The normal run right after re-adds the story (if it is still in the feeds) with the current rules."""
    rows = request("GET", "/rest/v1/risk_areas?select=id,title,title_original,lat,lng,source_url,body_read&source=eq.news&status=eq.pending&limit=1000") or []
    bad = [(r, audit_row(r)) for r in rows]
    bad = [(r, why) for r, why in bad if why]
    for r, why in bad:
        log(f"   audit: removing ({why}): {r['title'][:80]}")
        request("DELETE", f"/rest/v1/risk_areas?id=eq.{r['id']}&status=eq.pending", None, {"Prefer": "return=minimal"})
    return len(bad)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="show what would be added; do not touch the database")
    ap.add_argument("--feeds", default=os.path.join(HERE, "feeds.txt"))
    args = ap.parse_args(argv)

    max_age = int(os.environ.get("NEWS_MAX_AGE_DAYS", "4"))
    keep_days = int(os.environ.get("NEWS_KEEP_DAYS", "4"))
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

    removed_old = audited = 0
    if not args.dry_run:                               # housekeeping first; a failure here must not stop the news check
        try:
            removed_old = cleanup_old(supabase_request, keep_days)
            audited = audit_pending(supabase_request)
            log(f"Housekeeping: deleted {removed_old} old waiting/rejected item(s), removed {audited} wrongly placed item(s) to redo them.")
        except Exception as e:
            log(f"Housekeeping skipped: {type(e).__name__}: {e}")
    known = set()
    if not args.dry_run:
        try:
            got = supabase_request("GET", "/rest/v1/risk_areas?select=source_url&limit=3000") or []
            known = {(g.get("source_url") or "").split("#")[0] for g in got}
        except Exception as e:
            log(f"Could not list stored links ({e}); every article will be read again.")

    def reader(link):
        time.sleep(0.4)
        return article.read(link)
    rows, stats = build_rows(items, Geocoder(), max_age, expiry, reader=reader, known_urls=known,
                             translator=Translator(email=os.environ.get("MYMEMORY_EMAIL")))
    log(f"\nFeeds ok: {ok}, failed: {len(failed)}   |   {stats}")

    if args.dry_run:
        for r in rows:
            log(f" + [{r['status']} {r['confidence']}] [{r['type']} sev{r['severity']}] {r['title'][:80]}  @ {r['place_text']} ({r['lat']}, {r['lng']})")
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
                    f"- New pending risk areas: **{len(rows)}**\n- Details: `{stats}`\n"
                    f"- Held back by verification (not on the map; see the Held tab): **{stats.get('held', 0)}**, articles read: **{stats.get('articles_read', 0)}**\n"
                    f"- Housekeeping: old items deleted **{removed_old}**, wrongly placed items redone **{audited}**\n")
            if UNMAPPED:
                f.write("- Incidents with no usable place (not mapped, check by hand if they matter, e.g. highway-only reports):\n")
                for t in UNMAPPED[:25]:
                    f.write(f"  - {t}\n")
            for u in failed:
                f.write(f"- ⚠️ feed failed: `{u}`\n")
    return 0 if ok else 1          # every feed failed -> mark the run red so you get an email


if __name__ == "__main__":
    sys.exit(main())
