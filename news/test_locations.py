"""One general test table for "where did this happen?" — add a line whenever a real headline is placed wrongly.
Run:  python3 -m unittest news.test_locations"""
import json
import unittest
import urllib.parse

try:
    from . import fetch_news as fn, places
except ImportError:
    import fetch_news as fn
    import places


def fetch(url):                                     # fake map lookup: a spot in the district named in the query
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
    eng = places.engine()
    for d in eng.districts.values():
        if d["name"].lower() in q.lower():
            return json.dumps([{"lat": str(d["c"][0] + 0.01), "lon": str(d["c"][1] + 0.01)}]).encode()
    return json.dumps([]).encode()


# (headline, summary, expected)   expected: "abroad" | "none" | ("district", Name) | ("place", "Name")
CASES = [
    # --- other countries
    ("Bangladeshi worker killed in road accident in Saudi Arabia", "", "abroad"),
    ("Man from Cumilla dies in Riyadh fire", "", "abroad"),
    ("Cumilla man killed in Malaysia", "He was hailing from Chandina upazila of Cumilla.", "abroad"),
    ("Four Bangladeshis die in Oman bus crash", "They were from Sylhet and Habiganj.", "abroad"),
    ("Expatriate's body returns home to Habiganj", "He died in Saudi Arabia last week.", "abroad"),
    ("Hundreds of Bangladeshi workers stranded in Libya", "", "abroad"),
    ("12 dead in Iran bus accident: state media - The Daily Star", "", "abroad"),
    ("সৌদি আরবে সড়ক দুর্ঘটনায় কুমিল্লার যুবক নিহত", "", "abroad"),
    # --- where a person comes from is not where it happened
    ("A resident of Natore was killed in a road accident in Mirpur", "", ("district", "Dhaka")),
    ("Fire at Mirpur-10 kills 2; victims were from Kurigram", "", ("place", "Mirpur-10")),
    ("Truck driver from Dinajpur killed in Bhairab", "", ("place", "Bhairab")),
    ("Rickshaw puller from Barishal robbed in Pallabi", "", ("place", "Pallabi")),
    # --- routes are not places
    ("Dhaka-bound bus hijacked in Natore, passengers robbed", "", ("district", "Natore")),
    ("Sylhet-bound bus from Dhaka collides with truck at Sreemangal", "", ("place", "Sreemangal")),
    ("Truck-bus collision on Dhaka-Chattogram highway kills 5 in Feni", "", ("district", "Feni")),
    ("Workers block Dhaka-Mymensingh highway in Gazipur", "", ("district", "Gazipur")),
    ("ঢাকা থেকে সিলেটগামী বাসে ডাকাতি, শ্রীমঙ্গলে", "", ("place", "Sreemangal")),
    # --- the district the story names wins over a famous name that also exists elsewhere
    ("Mob beats youth to death in Rampura, Rajshahi", "", ("district", "Rajshahi")),
    ("Petrol bombs hurled at Grameen Bank office in Rajshahi", "", ("district", "Rajshahi")),
    ("রাজশাহীতে ককটেল বিস্ফোরণ", "রাজধানীর পথে ছিল বাসটি", ("district", "Rajshahi")),
    ("Bus torched in Rajshahi, passengers fled to the capital", "", ("district", "Rajshahi")),
    # --- official upazilas / unions
    ("BNP leader shot dead in Narsingdi's Madhabdi", "", ("district", "Narsingdi")),
    ("Fire at Rohingya camp in Ukhia, Cox's Bazar", "", ("district", "Cox's Bazar")),
    ("Student killed in clash at Hathazari, Chattogram", "", ("district", "Chattogram")),
    ("Accident in Tongi kills 3", "", ("place", "Tongi")),
    ("Bus hits CNG at Sarail Police Station crossing", "", ("place", "Sarail")),
    ("Dhaka-based businessman shot dead in Natore", "", ("district", "Natore")),
    ("Cocktail blast in Dhaka, bus attacked in Cumilla", "", ("district", "Dhaka")),
    ("Jisan of Gangni killed in a road accident in Kushtia", "", ("district", "Kushtia")),
    ("Madrasa student injured in a road accident in Barolekha dies", "", ("district", "Moulvibazar")),
    ("Bus set on fire on Dhaka-Chattogram Highway in Narayanganj", "", ("district", "Narayanganj")),
    ("Parked bus set on fire on Dhaka-Chattogram highway in N'ganj", "", ("district", "Narayanganj")),
    ("Two killed in Cox’s Bazar road accident", "", ("district", "Cox's Bazar")),
    ("2 killed in road accidents in Sirajganj and Jhalokati", "", ("district", "Sirajganj")),
    ("বগুড়ায় বিএনপির ধাওয়া, ককটেল ফেলে পালালেন আওয়ামী লীগের নেতাকর্মীরা - Dhaka Prokash", "", ("district", "Bogura")),
    ("চুয়াডাঙ্গায় সাংবাদিকের গাড়িতে অতর্কিত হামলা, ভাঙচুর", "", ("district", "Chuadanga")),
    ("মিরসরাইয়ে পুলিশের টহল ভ্যানে বাসের ধাক্কা, ছয় পুলিশ সদস্য আহত", "", ("district", "Chattogram")),
    ("গাজীপুরে ঢাকা-ময়মনসিংহ মহাসড়ক অবরোধ, পুলিশের গাড়িতে অগ্নিসংযোগ - bdnews24.com", "", ("district", "Gazipur")),
    # --- a foreign name next to a Bangladesh incident
    ("Protesters in Dhaka burn effigy over Gaza attack, clash with police", "", ("district", "Dhaka")),
]


class Locations(unittest.TestCase):
    def test_table(self):
        fn.time.sleep = lambda s: None
        geo = fn.Geocoder(sleep=0, fetch=fetch)
        eng = places.engine()
        wrong = []
        for title, summary, expect in CASES:
            locs, why = fn.analyse_story(title, summary, geo)
            if expect == "abroad":
                ok = why == "abroad"
            elif expect == "none":
                ok = not locs
            else:
                kind, name = expect
                ok = bool(locs)
                if ok and kind == "place":
                    ok = locs[0]["place_text"].lower().startswith(name.lower())
                if ok and kind == "district":
                    ok = eng.district_at(locs[0]["lat"], locs[0]["lng"]) == name
            if not ok:
                wrong.append((title[:70], expect, why, [(l["place_text"], round(l["lat"], 3), round(l["lng"], 3)) for l in locs]))
        self.assertEqual(wrong, [], "\n" + "\n".join(map(str, wrong)))


class Housekeeping(unittest.TestCase):
    def test_cleanup_deletes_only_old_waiting_and_rejected(self):
        calls = []

        def request(method, path, body=None, extra=None):
            calls.append((method, path))
            return [{"id": "1"}, {"id": "2"}]
        import datetime as dt
        n = fn.cleanup_old(request, 4, today=dt.date(2026, 11, 22))
        self.assertEqual(n, 2)
        method, path = calls[0]
        self.assertEqual(method, "DELETE")
        self.assertIn("happened_on=lt.2026-11-18", path)
        self.assertIn("status=in.(pending,rejected,held)", path)
        self.assertNotIn("approved", path)                       # approved items are never deleted

    def test_audit_removes_wrong_district_and_abroad_but_keeps_good(self):
        rows = [
            {"id": "a", "title": "Petrol bombs hurled at Grameen Bank office in Rajshahi", "title_original": None, "lat": 23.80, "lng": 90.36},
            {"id": "b", "title": "A young man from Brahmanbaria killed in a road accident in Saudi Arabia", "title_original": None, "lat": 23.96, "lng": 91.11},
            {"id": "c", "title": "Bus set on fire in Mirpur", "title_original": None, "lat": 23.8069, "lng": 90.3687},
            {"id": "d", "title": "Bus torched in Rajshahi - Dhaka Post", "title_original": None, "lat": 24.37, "lng": 88.60},
        ]
        deleted = []

        def request(method, path, body=None, extra=None):
            if method == "GET":
                return rows
            deleted.append(path)
            return None
        self.assertEqual(fn.audit_pending(request), 2)
        self.assertTrue(any("id=eq.a" in d for d in deleted) and any("id=eq.b" in d for d in deleted))
        self.assertFalse(any("id=eq.c" in d or "id=eq.d" in d for d in deleted))
        self.assertTrue(all("status=eq.pending" in d for d in deleted))         # approved rows can never be deleted by the audit


if __name__ == "__main__":
    unittest.main()
