"""Run with:  python3 -m unittest news.test_fetch_news -v   (from the project root)
No internet needed: feeds and the geocoder are faked."""
import datetime as dt
import json
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
        self.assertEqual(st, {"seen": 7, "too_old": 1, "not_incident": 2, "no_place": 1, "duplicate": 1, "kept": 2}, st)
        crash = [r for r in rows if r["type"] == "accident"][0]
        self.assertEqual((crash["severity"], crash["status"], crash["source"]), (3, "pending", "news"))
        self.assertEqual(crash["lat"], 23.8541)
        self.assertTrue(crash["expires_at"].startswith("2026-12-17"))
        self.assertEqual([r["type"] for r in rows].count("violence"), 1)
        # every row fits the database rules (see supabase/schema.sql)
        for r in rows:
            self.assertTrue(20.5 <= r["lat"] <= 26.7 and 88 <= r["lng"] <= 92.8)
            self.assertTrue(200 <= r["radius_m"] <= 20000 and 1 <= r["severity"] <= 3 and len(r["title"]) <= 200)

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
                 mock.patch.object(fn, "build_rows", lambda i, g, a, e: real_build(i, g, a, e, now=NOW)):
                code = fn.main(["--feeds", feeds])
        finally:
            os.remove(feeds)
        self.assertEqual(code, 0)                           # one feed died, the run still succeeds
        self.assertEqual(len(sent), 1)
        path, body, extra = sent[0]
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
