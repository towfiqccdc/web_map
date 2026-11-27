"""Reading a story the way a person does: WHERE did it happen, and is that in Bangladesh?

A place name in a story can play different parts:
    locative  "... set on fire IN Pallabi"  / "Sarail police station"  -> the incident is here
    dateline  "Sylhet: Bus set on fire"                                -> the incident is here
    origin    "a resident OF Cumilla", "hailing from Natore"           -> where a person comes from, NOT the incident
    neutral   mentioned without a clue
Everything below is plain text rules (no web calls, no AI), so it is free, fast and testable.
"""
import re

COUNTRIES = """Afghanistan Albania Algeria Angola Argentina Armenia Australia Austria Azerbaijan Bahrain Belarus Belgium Bhutan Bolivia Bosnia Botswana
Brazil Brunei Bulgaria Cambodia Cameroon Canada Chad Chile China Colombia Congo Croatia Cuba Cyprus Czechia Denmark Ecuador Egypt Eritrea Estonia
Ethiopia Fiji Finland France Gabon Georgia Germany Ghana Greece Guatemala Guinea Haiti Honduras Hungary Iceland India Indonesia Iran Iraq Ireland
Israel Italy Jamaica Japan Jordan Kazakhstan Kenya Kosovo Kuwait Kyrgyzstan Laos Latvia Lebanon Liberia Libya Lithuania Luxembourg Madagascar
Malawi Malaysia Maldives Mali Malta Mauritania Mauritius Mexico Moldova Mongolia Montenegro Morocco Mozambique Myanmar Namibia Nepal Netherlands
Nicaragua Niger Nigeria Norway Oman Pakistan Palestine Panama Paraguay Peru Philippines Poland Portugal Qatar Romania Russia Rwanda Saudi Senegal
Serbia Singapore Slovakia Slovenia Somalia Spain Sudan Suriname Sweden Switzerland Syria Taiwan Tajikistan Tanzania Thailand Tunisia Turkey Turkmenistan
Uganda Ukraine UAE Emirates Uruguay Uzbekistan Venezuela Vietnam Yemen Zambia Zimbabwe Gaza Rafah Kashmir Greenland Libya""".split()
FOREIGN_CITIES = ["Riyadh", "Jeddah", "Jiddah", "Mecca", "Makkah", "Medina", "Dammam", "Dubai", "Abu Dhabi", "Sharjah", "Doha", "Kuwait City", "Muscat",
                  "Manama", "Kuala Lumpur", "Johor", "Penang", "Tokyo", "Beijing", "Shanghai", "Hong Kong", "Delhi", "Kolkata", "Calcutta", "Mumbai",
                  "Assam", "Tripura", "Meghalaya", "West Bengal", "Karachi", "Lahore", "Islamabad", "Kathmandu", "Colombo", "Yangon", "Rakhine",
                  "Bangkok", "London", "New York", "Washington", "Paris", "Rome", "Tehran", "Baghdad", "Jerusalem", "Tel Aviv", "Beirut", "Kabul",
                  "Moscow", "Kyiv", "Sri Lanka", "United States", "United Kingdom", "South Korea", "North Korea", "South Africa", "New Zealand",
                  "Saudi Arabia", "Sierra Leone", "Costa Rica", "Dominican Republic", "Hong Kong", "Bahrain"]
FOREIGN = re.compile(r"(?<![\w'])(" + "|".join(sorted({re.escape(n) for n in COUNTRIES + FOREIGN_CITIES}, key=len, reverse=True)) +
                     r"|\bUS\b|\bUK\b|\bU\.S\.|\bU\.K\.)(?![\w'])")
FOREIGN_BN = re.compile(r"সৌদি|সৌদী|ওমান|কুয়েত|কাতার|দুবাই|আমিরাত|মালয়েশিয়া|সিঙ্গাপুর|লিবিয়া|ইতালি|ইরান|ইরাক|ইসরায়েল|গাজা|ভারত|পাকিস্তান|নেপাল|মিয়ানমার|চীন|জাপান|যুক্তরাষ্ট্র|যুক্তরাজ্য|লেবানন|সিরিয়া|ইয়েমেন|জর্ডান|বাহরাইন|দক্ষিণ কোরিয়া|কোরিয়া|রাশিয়া|ইউক্রেন|তুরস্ক|মিসর|মালদ্বীপ")
EXPAT = re.compile(r"expatriate|migrant worker|overseas|remittance|abroad|returnee|repatriat|brought (?:back )?home|body .{0,30}(?:arrive|reach|bring|brought|return)|প্রবাসী|প্রবাসে|লাশ দেশে|মরদেহ দেশে|বিদেশ", re.I)

LOC_BEFORE = re.compile(r"(?:\b(?:in|at|near|outside|inside|around|within|across|beside|opposite|along|between|off|from the area of)"
                        r"|outskirts of|area of|areas of|vicinity of|premises of|centre of|center of|heart of|police station in|ahead of)\s+(?:the\s+)?(?:[\w'’-]+\s+){0,3}$", re.I)
LIST_LOC = re.compile(r"\b(?:in|at|near|across|around)\s+(?:the\s+)?[\w'’ ,-]{1,90}?(?:,|\band\b|&)\s*(?:the\s+)?$", re.I)     # "in Sylhet and Chhatak"
ORIGIN_BEFORE = re.compile(r"(?:(?-i:\b(?!(?:Area|Areas|Outskirts|Vicinity|Premises|Centre|Center|Heart|Parts?|City|District|Residents?|Natives?|Part)\s)[A-Z][a-z]{2,}\s+of)|\b(?:residents? of|natives? of|hail(?:s|ing)? from|hometown(?: in| of)?|home district(?: of)?|belonging to|originally from|son of|daughter of|from)"
                           r"|\b(?:man|woman|youth|worker|workers|student|expatriate|migrant|labourer|laborer|driver|businessman|teenager|boy|girl|passenger|farmer|trader|couple|family|person|people)"
                           r"(?:,)?\s+(?:aged\s+\d+\s+)?(?:of|from))\s+(?:the\s+)?(?:[\w'’-]+\s+){0,2}$", re.I)
KIN_CLAUSE = re.compile(r"\b(?:son|daughter|wife|husband|father|mother|brother|sister|relative|neighbou?r)s?\s+of\b|\bvillage\s+(?:under|in|of)\s+(?:the\s+)?(?:[\w'’-]+\s+){0,2}$", re.I)
AFTER_LOC = re.compile(r"^\s*(?:area|police station|thana|upazila|union|bazar|bazaar|mor\b|more\b|intersection|crossing|bridge|flyover|bus stand|market|hospital|mill|factory|road|highway)", re.I)
BN_AFTER_LOC = re.compile(r"^(?:ে|তে|য়|য়ে|-এ|-তে|\sএ\b|র?\s*এলাকায়|র?\s*কাছে|র?\s*নিকটে|\sথানা|\sইউনিয়নে|\sউপজেলায়)")
AFTER_ORIGIN = re.compile(r"^[-\s]*(?:based|born|origin|native|resident|national)\b", re.I)               # "Dhaka-based", "Natore-born"
BN_AFTER_ORIGIN = re.compile(r"^(?:ের|র|-এর)?\s*(?:বাসিন্দা|নিবাসী|বাসী|বাড়ি|গ্রামের)")


def role_of(text, start, end, title_len=0):
    """locative | dateline | origin | neutral — what part the place at text[start:end] plays."""
    before = text[max(0, start - 60):start]
    cut = max(before.rfind(". "), before.rfind("; "), before.rfind(": "), before.rfind(" - "), before.rfind("! "), before.rfind("? "))
    if cut >= 0:
        before = before[cut + 2:]
    after = text[end:end + 40]
    if start < title_len and start < 30 and re.match(r"^\s*[:,]", after):
        return "dateline"
    if ORIGIN_BEFORE.search(before) or KIN_CLAUSE.search(before) or BN_AFTER_ORIGIN.match(after) or AFTER_ORIGIN.match(after):
        return "origin"
    if LOC_BEFORE.search(before) or LIST_LOC.search(before) or AFTER_LOC.match(after) or BN_AFTER_LOC.match(after):
        return "locative"
    return "neutral"


def foreign_mentions(text, title_len=0):
    """[(start, end, name, role)] for every foreign country/city named."""
    out = []
    for m in FOREIGN.finditer(text):
        out.append((m.start(), m.end(), m.group(1), role_of(text, m.start(), m.end(), title_len)))
    for m in FOREIGN_BN.finditer(text):
        out.append((m.start(), m.end(), m.group(0), role_of(text, m.start(), m.end(), title_len)))
    return out


def is_abroad(text, bd_mentions, title_len=0):
    """True when the incident happened outside Bangladesh.
    bd_mentions: [{"pos","end","role"}] for the Bangladesh places the story names."""
    foreign = foreign_mentions(text, title_len)
    if not foreign:
        return False
    bd_here = [m for m in bd_mentions if m["role"] in ("locative", "dateline")]
    if bd_here:                                         # something clearly happened in a Bangladesh place
        return False
    foreign_here = [f for f in foreign if f[3] in ("locative", "dateline") or f[0] < title_len]
    if foreign_here:
        return True                                     # "died in Saudi Arabia", "Saudi Arabia:" ... and nothing local
    if EXPAT.search(text):
        return True                                     # expatriate / migrant-worker story: the place named is a home town
    return not [m for m in bd_mentions if m["role"] != "origin"]     # foreign names only and no local place at all
