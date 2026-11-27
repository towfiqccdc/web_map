"""The routes CCDC vehicles drive every day, so incidents on them can be found, ranked and shown first.

A pin is "on a route" when it lies within ON_ROUTE_KM of the route's line. Lines are approximate polylines of the
national highways (the same ones the highway snapping uses), so keep ON_ROUTE_KM generous.
"""
from math import asin, cos, radians, sin, sqrt

OFFICE = (23.8043, 90.4219)        # Baridhara
ON_ROUTE_KM = 5.0
NEAR_OFFICE_KM = 6.0

SYLHET_LINE = [(23.7000, 90.5000), (23.8541, 90.6672), (24.0522, 90.9764), (24.0735, 91.1148), (24.3745, 91.4155),
               (24.3065, 91.7296), (24.4829, 91.7774), (24.8949, 91.8687)]
ROUTES = [
    {"name": "Dhaka–Narsingdi–Bhairab–Brahmanbaria",
     "line": [(23.7640, 90.4110), (23.7000, 90.5000), (23.8541, 90.6672), (23.9246, 90.7150), (24.0522, 90.9764), (24.0300, 91.0050), (23.9571, 91.1119)],
     "districts": {"Dhaka", "Narayanganj", "Narsingdi", "Kishoreganj", "Brahmanbaria"}},
    {"name": "Dhaka–Sylhet", "line": [(23.7640, 90.4110)] + SYLHET_LINE,
     "districts": {"Dhaka", "Narayanganj", "Narsingdi", "Brahmanbaria", "Habiganj", "Moulvibazar", "Sylhet"}},
    {"name": "Dhaka–Cumilla–Chattogram",
     "line": [(23.7104, 90.4344), (23.7000, 90.5000), (23.5400, 90.7200), (23.4690, 91.0030), (23.4607, 91.1809), (23.2480, 91.1310),
              (23.0159, 91.3976), (22.7770, 91.5810), (22.6190, 91.6690), (22.3569, 91.7832)],
     "districts": {"Dhaka", "Narayanganj", "Munshiganj", "Cumilla", "Feni", "Chattogram"}},
    {"name": "Dhaka–Ashulia–Gazipur",
     "line": [(23.8043, 90.4219), (23.8759, 90.3795), (23.8898, 90.3187), (23.8977, 90.2670)],
     "districts": {"Dhaka", "Gazipur"}},
    {"name": "Dhaka–Gazipur–Mymensingh",
     "line": [(23.8500, 90.4000), (23.8918, 90.4058), (23.9999, 90.4203), (24.2000, 90.3500), (24.4000, 90.3000), (24.7471, 90.4203)],
     "districts": {"Dhaka", "Gazipur", "Mymensingh"}},
    {"name": "Chattogram–Cumilla–Brahmanbaria–Sylhet",
     "line": [(22.3569, 91.7832), (22.7770, 91.5810), (23.4607, 91.1809), (23.7000, 91.1500), (23.9571, 91.1119), (24.3745, 91.4155),
              (24.3065, 91.7296), (24.8949, 91.8687)],
     "districts": {"Chattogram", "Feni", "Cumilla", "Brahmanbaria", "Habiganj", "Moulvibazar", "Sylhet"}},
]
# words that suggest a story is about these routes (used only to decide which stories get read / AI-checked first)
ROUTE_WORDS = ("narsingdi", "madhabdi", "bhairab", "ashuganj", "brahmanbaria", "sarail", "akhaura", "kasba", "ashulia", "savar", "gazipur", "tongi", "konabari",
               "kanchpur", "sonargaon", "daudkandi", "chandina", "cumilla", "comilla", "feni", "laksam", "sylhet", "habiganj", "moulvibazar", "sreemangal",
               "chattogram", "chittagong", "sitakunda", "mirsarai", "kishoreganj", "narayanganj", "dhaka-sylhet", "dhaka-chattogram", "dhaka-mymensingh",
               "dhaka-aricha", "dhaka-cumilla", "মেঘনা", "নরসিংদী", "ভৈরব", "আশুগঞ্জ", "ব্রাহ্মণবাড়িয়া", "সরাইল", "আশুলিয়া", "সাভার", "গাজীপুর", "টঙ্গী",
               "কাঁচপুর", "সোনারগাঁও", "দাউদকান্দি", "চান্দিনা", "কুমিল্লা", "ফেনী", "সিলেট", "হবিগঞ্জ", "মৌলভীবাজার", "চট্টগ্রাম", "সীতাকুণ্ড", "কিশোরগঞ্জ", "নারায়ণগঞ্জ")


def _km(a, b, c, d):
    p = radians
    h = sin(p(c - a) / 2) ** 2 + cos(p(a)) * cos(p(c)) * sin(p(d - b) / 2) ** 2
    return 12742 * asin(sqrt(h))


def _dist_to_line(lat, lng, line):
    best = 1e9
    for (a1, o1), (a2, o2) in zip(line, line[1:]):
        kx = 111.0 * cos(radians(lat))
        ax, ay, bx, by = (o1 - lng) * kx, (a1 - lat) * 111.0, (o2 - lng) * kx, (a2 - lat) * 111.0
        dx, dy = bx - ax, by - ay
        t = 0 if dx == dy == 0 else max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
        best = min(best, sqrt((ax + t * dx) ** 2 + (ay + t * dy) ** 2))
    return best


def match(lat, lng):
    """{"route": name or None, "km": distance to it, "near_office": bool}"""
    best = min(((_dist_to_line(lat, lng, r["line"]), r["name"]) for r in ROUTES))
    return {"route": best[1] if best[0] <= ON_ROUTE_KM else None, "km": round(best[0], 1),
            "near_office": _km(lat, lng, *OFFICE) <= NEAR_OFFICE_KM}


def priority(text):
    """Cheap score of how route-related a headline/summary is (higher = read and AI-check first)."""
    t = (text or "").lower()
    return sum(1 for w in ROUTE_WORDS if w in t) + (2 if "highway" in t or "মহাসড়ক" in t else 0)
