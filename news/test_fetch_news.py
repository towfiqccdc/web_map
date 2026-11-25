"""Run with:  python3 -m unittest news.test_fetch_news -v   (from the project root)
No internet needed: feeds and the geocoder are faked."""
import datetime as dt
import json
import urllib.parse
import os
import unittest
from unittest import mock

from news import fetch_news as fn

NOW = dt.datetime(2026, 11, 17, 6, 0, tzinfo=dt.timezone.utc)

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>3 killed as bus rams truck on Dhaka-Sylhet highway in Madhabdi</title><link>https://n.example/1</link>
 <description>&lt;p&gt;Three people were killed and 10 injured when a bus collided with a truck at Madhabdi, Narsingdi.&lt;/p&gt;</description>
 <pubDate>Mon, 16 Nov 2026 10:00:00 +0600</pubDate></item>
<item><title>Same crash: bus-truck collision kills 3 in Madhabdi</title><link>https://other.example/9</link>
 <description>Collision at Madhabdi on the highway, 3 dead.</description><pubDate>Mon, 16 Nov 2026 12:00:00 +0600</pubDate></item>
<item><title>Robbers hijack bus on Mymensingh highway, passengers robbed near Bhaluka</title><link>https://n.example/2</link>
 <description>Armed robbers stopped the bus on the highway near Bhaluka and robbed passengers.</description><pubDate>Mon, 16 Nov 2026 09:00:00 +0600</pubDate></item>
<item><title>Road safety awareness campaign launched in Rajshahi</title><link>https://n.example/3</link><description>campaign on road accidents</description><pubDate>Mon, 16 Nov 2026 09:00:00 +0600</pubDate></item>
<item><title>Striker injured in league match</title><link>https://n.example/4</link><description>The player was hurt during the game.</description><pubDate>Mon, 16 Nov 2026 09:00:00 +0600</pubDate></item>
<item><title>Truck crashes on highway near Nowhereville</title><link>https://n.example/5</link><description>a truck crashed, driver injured</description><pubDate>Mon, 16 Nov 2026 09:00:00 +0600</pubDate></item>
<item><title>Bus accident on Chattogram highway kills 2</title><link>https://n.example/6</link><description>old story</description><pubDate>Mon, 02 Nov 2026 09:00:00 +0600</pubDate></item>
</channel></rss>"""

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom crash</title><link href="https://a.example/1"/>
<summary>x</summary><updated>2026-11-16T04:00:00Z</updated></entry></feed>"""

PLACES = {"madhabdi": (23.8541, 90.6672), "bhaluka": (24.4, 90.3), "dhaka-sylhet highway": (24.9, 91.5),
          "nowhereville": (22.1, 77.0)}          # <- outside Bangladesh: must be rejected


def fake_fetch(url):
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(url).query)["q"][0].split(",")[0].lower()
    p = PLACES.get(q)
    return json.dumps([{"lat": str(p[0]), "lon": str(p[1])}] if p else []).encode()


class Tests(unittest.TestCase):
    def test_classify(self):
        c = fn.classify("3 killed as bus rams truck on highway", "")
        self.assertEqual((c["type"], c["severity"], c["deaths"]), ("accident", 3, 3))
        c = fn.classify("Two people killed in road crash", "")
        self.assertEqual((c["type"], c["severity"]), ("accident", 2))
        c = fn.classify("Truck hits CNG on highway, driver injured", "")
        self.assertEqual((c["type"], c["severity"]), ("accident", 1))
        c = fn.classify("Robbers hijack bus on highway", "passengers robbed")
        self.assertEqual(c["type"], "violence")
        self.assertIsNone(fn.classify("Road safety awareness campaign", "road accidents"))
        self.assertIsNone(fn.classify("Striker injured in match", ""))

    def test_place_candidates(self):
        names = [n for n, _ in fn.place_candidates("bus rams truck on Dhaka-Sylhet highway in Madhabdi", "at Madhabdi, Narsingdi")]
        self.assertEqual(names[0], "Madhabdi")                 # town first
        self.assertEqual(names[-1], "Dhaka-Sylhet highway")    # long highway last
        self.assertNotIn("Dhaka-Sylhet", names)                # not mistaken for a place
        dist = dict(fn.place_candidates("crash in the area", "Narsingdi"))
        self.assertTrue(dist["Narsingdi"])      # flagged district-only

    def test_parse_feed(self):
        items = fn.parse_feed(RSS.encode())
        self.assertEqual(len(items), 7)
        self.assertIn("Three people were killed", items[0]["summary"])
        self.assertNotIn("<p>", items[0]["summary"])
        self.assertEqual(items[0]["published"].utcoffset(), dt.timedelta(hours=6))
        a = fn.parse_feed(ATOM.encode())
        self.assertEqual((a[0]["link"], a[0]["published"].year), ("https://a.example/1", 2026))

    def test_pipeline(self):
        geo = fn.Geocoder(sleep=0, fetch=fake_fetch)
        rows, st = fn.build_rows(fn.parse_feed(RSS.encode()), geo, 2, 30, now=NOW)
        titles = [r["title"] for r in rows]
        self.assertEqual(st, {"seen": 7, "too_old": 1, "not_incident": 2, "no_place": 1, "duplicate": 1, "kept": 2, "held": 0, "articles_read": 0}, st)
        crash = [r for r in rows if r["type"] == "accident"][0]
        self.assertEqual((crash["severity"], crash["status"], crash["source"]), (3, "pending", "news"))
        self.assertEqual(crash["lat"], 23.8583)      # Madhabdi comes from the built-in place list
        self.assertTrue(crash["expires_at"].startswith("2026-12-17"))
        self.assertEqual([r["type"] for r in rows].count("violence"), 1)
        # every row fits the database rules (see supabase/schema.sql)
        for r in rows:
            self.assertTrue(20.5 <= r["lat"] <= 26.7 and 88 <= r["lng"] <= 92.8)
            self.assertTrue(200 <= r["radius_m"] <= 20000 and 1 <= r["severity"] <= 3 and len(r["title"]) <= 200)

    # ---- security incidents in Dhaka (the two Prothom Alo stories that were being missed) -------
    def _rows(self, title, summary, link="https://n.example/x"):
        items = [{"title": title, "link": link, "summary": summary, "published": NOW}]
        return fn.build_rows(items, fn.Geocoder(sleep=0, fetch=fake_fetch), 2, 30, now=NOW)

    def test_english_cocktail_and_bus_arson_dhaka(self):
        rows, st = self._rows("Four buses set on fire and cocktail explosions at six places in the capital overnight",
                              "Buses were torched in Pallabi, Mahakhali, Badda and Rampura. Cocktails exploded in Mohammadpur, Jatrabari and Shyamoli.")
        self.assertEqual(st["kept"], 5, st)                                   # capped at 5 places per article
        self.assertEqual({r["type"] for r in rows}, {"violence"})
        self.assertEqual([r["place_text"] for r in rows][:4], ["Pallabi", "Mohakhali", "Badda", "Rampura"])
        self.assertEqual(len({r["source_url"] for r in rows}), 5)             # one pending item per place
        self.assertTrue(all(r["source_url"].startswith("https://n.example/x#") for r in rows))

    def test_bus_set_on_fire_mirpur(self):
        rows, _ = self._rows("Bus set on fire in Mirpur, 2 detained", "Unidentified people torched a Rajdhani Paribahan bus.")
        self.assertEqual((rows[0]["type"], rows[0]["place_text"], rows[0]["severity"]), ("violence", "Mirpur", 2))
        self.assertEqual(rows[0]["source_url"], "https://n.example/x")        # single place: link unchanged

    def test_cocktail_without_road_words_and_roadblock(self):
        self.assertEqual(fn.classify("Cocktail blast in Mohammadpur", "")["type"], "violence")
        self.assertEqual(fn.classify("Students block Dhaka-Sylhet highway, Sylhet", "roadblock for hours")["type"], "violence")
        self.assertIsNone(fn.classify("Gas cylinder explosion in Mirpur kills 2", ""))          # not a security incident
        self.assertIsNone(fn.classify("Court hears cocktail blast case, verdict next week", ""))

    def test_bangla_headlines(self):
        rows, st = self._rows("মিরপুরে বাসে আগুন, আটক ২", "রাজধানীর মিরপুর মডেল থানা এলাকায় রাতে রাজধানী পরিবহনের একটি বাসে আগুন দেওয়া হয়েছে।")
        self.assertEqual((rows[0]["type"], rows[0]["place_text"]), ("violence", "Mirpur"), rows)
        rows, st = self._rows("রাজধানীর ছয় স্থানে ককটেল বিস্ফোরণ, চার বাসে আগুন", "পল্লবী, মহাখালী, বাড্ডা ও রামপুরায় বাসে আগুন। মোহাম্মদপুর, যাত্রাবাড়ী ও শ্যামলীতে ককটেল বিস্ফোরণ।")
        self.assertEqual([r["place_text"] for r in rows][:3], ["Pallabi", "Mohakhali", "Badda"], rows)
        self.assertEqual(st["kept"], 5)
        rows, st = self._rows("রাজধানীতে ককটেল বিস্ফোরণ", "")                    # only "the capital": whole-city pin to refine
        self.assertEqual(rows[0]["place_text"], "Dhaka (whole city/district — check location)")
        self.assertEqual(rows[0]["radius_m"], 2000)
        rows, st = self._rows("সিলেটে সড়ক দুর্ঘটনায় তিনজন নিহত", "মহাসড়কে বাস-ট্রাকের মুখোমুখি সংঘর্ষে তিনজন নিহত হয়েছেন।")
        self.assertEqual((rows[0]["type"], rows[0]["severity"]), ("accident", 3), rows)
        self.assertEqual(fn.classify("ককটেল বিস্ফোরণ মামলার রায় ঘোষণা", ""), None)
        self.assertEqual(fn.classify("সড়ক নিরাপত্তা সচেতনতা সেমিনার", "বাস ও ট্রাক চালকদের জন্য"), None)
        self.assertEqual(fn.classify("খেলায় জয়ী দল", "ম্যাচে দুই গোল"), None)

    def test_same_story_from_two_outlets_not_duplicated(self):
        items = [{"title": "Bus torched in Pallabi", "link": "https://a/1", "summary": "", "published": NOW},
                 {"title": "Bus set on fire in Pallabi", "link": "https://b/2", "summary": "", "published": NOW}]
        rows, st = fn.build_rows(items, fn.Geocoder(sleep=0, fetch=fake_fetch), 2, 30, now=NOW)
        self.assertEqual((len(rows), st["duplicate"]), (1, 1), st)

    def test_nearby_dhaka_areas_from_one_article_are_all_kept(self):
        rows, _ = self._rows("Cocktails hurled in Pallabi and Mirpur", "")
        self.assertEqual(len(rows), 2)                                           # 2 km apart is fine inside one article

    def test_unknown_place_falls_back_to_map_lookup(self):
        rows, _ = self._rows("Robbers hijack bus on Mymensingh highway near Bhaluka", "passengers robbed")
        self.assertAlmostEqual(rows[0]["lat"], 24.4, delta=0.05)

    # ---- Bangla -> English titles (the manager reads English / Chinese) -------------------------
    def _tr(self, mapping=None, status=200, text=None):
        calls = []
        def fetch(url):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
            calls.append(q)
            out = text if text is not None else (mapping or {}).get(q)
            return json.dumps({"responseData": {"translatedText": out or ""}, "responseStatus": status}).encode()
        return fn.Translator(sleep=0, fetch=fetch), calls

    def test_bangla_title_translated_and_outlet_mapped(self):
        tr, calls = self._tr({"মিরপুরে বাসে আগুন": "Bus set on fire in Mirpur"})
        self.assertEqual(tr.title("মিরপুরে বাসে আগুন - প্রথম আলো"), "Bus set on fire in Mirpur - Prothom Alo")
        self.assertEqual(calls, ["মিরপুরে বাসে আগুন"])                      # outlet name needs no web call
        self.assertEqual(tr.title("মিরপুরে বাসে আগুন - প্রথম আলো"), "Bus set on fire in Mirpur - Prothom Alo")
        self.assertEqual(len(calls), 1)                                       # cached

    def test_quota_message_or_untranslated_is_rejected(self):
        tr, _ = self._tr(text="MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY")
        self.assertIsNone(tr.text("ককটেল বিস্ফোরণ"))
        tr, _ = self._tr(text="ককটেল বিস্ফোরণ")                              # came back still Bangla
        self.assertIsNone(tr.text("ককটেল বিস্ফোরণ"))
        tr, _ = self._tr(status=429, text="Bomb blast")
        self.assertIsNone(tr.text("ককটেল বিস্ফোরণ"))

    def test_rows_get_english_title_and_keep_original(self):
        tr, _ = self._tr({"মিরপুরে বাসে আগুন, আটক ২": "Bus set on fire in Mirpur, 2 detained"})
        items = [{"title": "মিরপুরে বাসে আগুন, আটক ২", "link": "https://n/1", "summary": "", "published": NOW}]
        rows, _ = fn.build_rows(items, fn.Geocoder(sleep=0, fetch=fake_fetch), 2, 30, now=NOW, translator=tr)
        self.assertEqual(rows[0]["title"], "Bus set on fire in Mirpur, 2 detained")
        self.assertEqual(rows[0]["title_original"], "মিরপুরে বাসে আগুন, আটক ২")

    def test_offline_english_title_when_translation_fails(self):
        tr, _ = self._tr(text="")                                              # service down
        items = [{"title": "রাজধানীর ছয় স্থানে ককটেল বিস্ফোরণ, চার বাসে আগুন", "link": "https://n/2",
                  "summary": "পল্লবী, মহাখালী ও বাড্ডায়", "published": NOW}]
        rows, _ = fn.build_rows(items, fn.Geocoder(sleep=0, fetch=fake_fetch), 2, 30, now=NOW, translator=tr)
        self.assertTrue(rows)
        for r in rows:
            self.assertFalse(fn.BN_CHARS.search(r["title"]), r["title"])       # always English
            self.assertIn("(Bangla report)", r["title"])
            self.assertTrue(fn.BN_CHARS.search(r["title_original"]))
        self.assertIn("Cocktail / bomb blast", rows[0]["title"])
        self.assertIn("Pallabi", rows[0]["title"])
        # and with no translator at all
        rows, _ = fn.build_rows(items, fn.Geocoder(sleep=0, fetch=fake_fetch), 2, 30, now=NOW)
        self.assertFalse(fn.BN_CHARS.search(rows[0]["title"]))

    def test_english_titles_untouched(self):
        tr, calls = self._tr(text="should not be used")
        items = [{"title": "Bus set on fire in Mirpur - The Daily Star", "link": "https://n/3", "summary": "", "published": NOW}]
        rows, _ = fn.build_rows(items, fn.Geocoder(sleep=0, fetch=fake_fetch), 2, 30, now=NOW, translator=tr)
        self.assertEqual((rows[0]["title"], rows[0]["title_original"], calls), ("Bus set on fire in Mirpur - The Daily Star", None, []))

    # ---- accuracy: a story about another district must not be pinned in Dhaka
    def _one(self, title, summary="", geo=None):
        geo = geo or fn.Geocoder(sleep=0, fetch=fake_fetch)
        items = [{"title": title, "link": "https://n/" + str(abs(hash(title))), "summary": summary, "published": NOW}]
        return fn.build_rows(items, geo, 2, 30, now=NOW)[0]

    def test_other_district_is_not_pinned_in_dhaka(self):
        queries = []

        def fetch(url):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
            queries.append(q)
            return json.dumps([{"lat": "24.37", "lon": "88.60"}]).encode()
        rows = self._one("Bus set on fire in Rampura, Rajshahi", "The bus was heading to the capital.", fn.Geocoder(sleep=0, fetch=fetch))
        self.assertEqual(len(rows), 1)
        self.assertGreater(abs(rows[0]["lng"] - 90.4), 1)                  # nowhere near Dhaka
        self.assertIn("Rajshahi", rows[0]["place_text"])
        self.assertTrue(any("Rajshahi" in q for q in queries), queries)

    def test_bangla_other_district_is_not_pinned_in_dhaka(self):
        queries = []

        def fetch(url):
            queries.append(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0])
            return json.dumps([{"lat": "24.37", "lon": "88.60"}]).encode()
        rows = self._one("রাজশাহীতে বাসে আগুন, রাজধানীগামী যাত্রীরা আতঙ্কিত", geo=fn.Geocoder(sleep=0, fetch=fetch))
        self.assertEqual(len(rows), 1)
        self.assertGreater(abs(rows[0]["lng"] - 90.4), 1)
        self.assertIn("Rajshahi", rows[0]["place_text"])

    def test_geocoded_name_is_narrowed_to_the_named_district(self):
        queries = []

        def fetch(url):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0]
            queries.append(q)
            return json.dumps([{"lat": "24.37", "lon": "88.60"}] if "Rajshahi" in q else [{"lat": "23.80", "lon": "90.36"}]).encode()
        rows = self._one("Petrol bombs hurled at Grameen Bank office in Rajshahi - Jagonews24", geo=fn.Geocoder(sleep=0, fetch=fetch))
        self.assertEqual(len(rows), 1)
        self.assertLess(rows[0]["lng"], 89)                                # Rajshahi, not the Dhaka head office
        self.assertTrue(all("Rajshahi" in q for q in queries), queries)

    def test_mirpur_sections_are_not_all_mirpur_10(self):
        r1 = self._one("Bus set on fire at Mirpur-1 - New Age BD")[0]
        self.assertEqual(r1["place_text"], "Mirpur-1")
        self.assertAlmostEqual(r1["lat"], 23.7957, places=3)
        r10 = self._one("Bus set on fire at Mirpur-10 roundabout")[0]
        self.assertEqual(r10["place_text"], "Mirpur-10")
        r7 = self._one("Cocktail blast near Mirpur 7 bus stand")[0]
        self.assertIn("check location", r7["place_text"])
        bn = self._one("মিরপুর-১ এ বাসে আগুন")[0]
        self.assertEqual(bn["place_text"], "Mirpur-1")
        plain = self._one("Bus set on fire in Mirpur")[0]
        self.assertEqual(plain["place_text"], "Mirpur")

    def test_highway_plus_district_pins_on_that_highway(self):
        r = self._one("Garment workers demanding a wage hike blocked the Dhaka-Mymensingh highway in Gazipur this morning, disrupting traffic")[0]
        self.assertIn("Dhaka-Mymensingh highway", r["place_text"])
        self.assertIn("Gazipur", r["place_text"])
        self.assertLess(abs(r["lat"] - 24.0), 0.08)                         # Gazipur stretch, not Dhaka airport (23.85)
        self.assertEqual(r["type"], "violence")
        r = self._one("Truck set on fire on Dhaka-Chattogram highway in Feni")[0]
        self.assertIn("Dhaka-Chattogram highway", r["place_text"])
        self.assertLess(abs(r["lat"] - 23.0159), 0.08)

    def test_snap_to_line_stays_on_the_road(self):
        la, ln, km = fn.snap_to_line(24.0, 90.5, fn.CORRIDORS[0]["line"])
        self.assertLess(km, 12)

    def test_stories_about_other_countries_are_skipped(self):
        self.assertEqual(self._one("12 dead in Iran bus accident: state media - The Daily Star"), [])
        self.assertEqual(self._one("Bus crash in India kills 5 near Kolkata"), [])
        self.assertEqual(len(self._one("Bus set on fire in Mirpur near Indian High Commission, Dhaka")), 1)

    def test_dhaka_story_still_pinned_in_dhaka(self):
        rows = self._one("Bus set on fire in Mirpur, Dhaka")
        self.assertEqual(rows[0]["place_text"], "Mirpur")
        self.assertAlmostEqual(rows[0]["lat"], 23.8069, places=3)

    def test_route_endpoints_do_not_decide_the_place(self):
        rows = self._one("Dhaka-bound bus from Sylhet set on fire at Sreemangal on Dhaka-Sylhet highway")
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["place_text"].startswith("Sreemangal"), rows[0]["place_text"])

    def test_neighbouring_districts_are_not_a_conflict(self):
        rows = self._one("Bus hijacked in Tongi, Gazipur near Dhaka")
        self.assertEqual(rows[0]["place_text"], "Tongi")

    def test_corridor_town_known(self):
        rows = self._one("Truck torched by protesters at Mirsarai on Chattogram-Dhaka highway")
        self.assertTrue(rows[0]["place_text"].startswith("Mirsarai"))
        self.assertAlmostEqual(rows[0]["lat"], 22.777, places=2)

    # ---- possible blockades
    def test_announced_blockade_is_flagged_as_possible(self):
        rows = self._one("Transport workers announce strike, to block Dhaka-Chattogram highway on Sunday", "Sitakunda leaders said so")
        self.assertEqual(rows[0]["type"], "other")
        self.assertTrue(rows[0]["title"].startswith("Possible blockade:"))
        rows = self._one("সীতাকুণ্ডে মহাসড়ক অবরোধের ডাক")
        self.assertEqual(rows[0]["type"], "other")

    def test_blockade_happening_now_is_violence(self):
        rows = self._one("Protesters block Dhaka-Sylhet highway at Sarail for hours")
        self.assertEqual(rows[0]["type"], "violence")
        self.assertFalse(rows[0]["title"].startswith("Possible"))

    def test_geocoder_cache_and_cap(self):
        calls = []
        geo = fn.Geocoder(max_calls=2, sleep=0, fetch=lambda u: (calls.append(u), fake_fetch(u))[1])
        geo.lookup("Madhabdi"); geo.lookup("madhabdi"); geo.lookup("Bhaluka")
        self.assertEqual(len(calls), 2)                      # second Madhabdi came from cache
        self.assertIsNone(geo.lookup("Somewhere else"))      # cap reached -> no further calls
        self.assertEqual(len(calls), 2)

    def test_drop_already_stored(self):
        row = {"source_url": "https://n.example/1", "place_text": "Madhabdi", "happened_on": "2026-11-16", "type": "accident"}
        same_story = dict(row, source_url="https://zzz")
        new = dict(row, source_url="https://new", place_text="Bhaluka", type="violence")
        existing = [{"source_url": "https://n.example/1", "place_text": "Madhabdi", "happened_on": "2026-11-16", "type": "accident"}]
        out = fn.drop_already_stored([row, same_story, new], request=lambda *a, **k: existing)
        self.assertEqual(out, [new])

    def test_main_end_to_end(self):
        sent = []
        def req(method, path, body=None, extra=None):
            if method == "GET": return []
            sent.append((path, body, extra)); return None
        def get(url, **k):
            if "dead" in url: raise OSError("boom")
            return RSS.encode()
        geo = fn.Geocoder(sleep=0, fetch=fake_fetch)
        real_build = fn.build_rows
        feeds = os.path.join(os.path.dirname(__file__), "_t_feeds.txt")
        with open(feeds, "w") as f: f.write("https://ok.example/rss\nhttps://dead.example/rss\n")
        try:
            with mock.patch.dict(os.environ, {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "k"}), \
                 mock.patch.object(fn, "http_get", get), mock.patch.object(fn, "supabase_request", req), \
                 mock.patch.object(fn, "Geocoder", lambda: geo), \
                 mock.patch.object(fn, "build_rows", lambda i, g, a, e, translator=None, **kw: real_build(i, g, a, e, now=NOW, translator=translator)):
                code = fn.main(["--feeds", feeds])
        finally:
            os.remove(feeds)
        self.assertEqual(code, 0)                           # one feed died, the run still succeeds
        self.assertTrue(any("status=in.(pending,rejected,held)" in x[0] for x in sent))     # old waiting news cleaned up first
        posts = [x for x in sent if "on_conflict" in x[0]]
        self.assertEqual(len(posts), 1)
        path, body, extra = posts[0]
        self.assertIn("on_conflict=source_url", path)
        self.assertIn("ignore-duplicates", extra["Prefer"])
        self.assertEqual(len(body), 2)
        self.assertTrue(all(r["status"] == "pending" for r in body))

    def test_all_feeds_dead_is_failure(self):
        feeds = os.path.join(os.path.dirname(__file__), "_t_feeds2.txt")
        with open(feeds, "w") as f: f.write("https://dead.example/rss\n")
        try:
            with mock.patch.dict(os.environ, {"SUPABASE_URL": "u", "SUPABASE_SERVICE_KEY": "k"}), \
                 mock.patch.object(fn, "http_get", side_effect=OSError("x")):
                self.assertEqual(fn.main(["--feeds", feeds]), 1)
        finally:
            os.remove(feeds)

    def test_refuses_to_run_without_keys(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(fn.main([]), 2)


if __name__ == "__main__":
    unittest.main()
