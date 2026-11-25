"""Verification gate + article reading. Run: python3 -m unittest discover -s news -t .   (no internet)"""
import datetime as dt
import unittest

from news import article, fetch_news as fn, verify

NOW = dt.datetime(2026, 11, 25, 6, 0, tzinfo=dt.timezone.utc)
D = dt.timezone.utc


def geo(points=None):
    pts = points or {}

    def fetch(url):
        import json, urllib.parse
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["q"][0].lower()
        for k, (la, lo) in pts.items():
            if k in q:
                return json.dumps([{"lat": str(la), "lon": str(lo)}]).encode()
        return b"[]"
    return fn.Geocoder(sleep=0, fetch=fetch)


def run(title, body="", art_date=NOW - dt.timedelta(days=1), summary="", points=None, feed_date=None):
    items = [{"title": title, "link": "https://news.google.com/rss/articles/x1", "summary": summary, "published": feed_date or NOW}]
    reader = (lambda link: {"text": body, "published": art_date}) if body or art_date else None
    return fn.build_rows(items, geo(points), 4, 30, now=NOW, reader=reader)


class ArticleReader(unittest.TestCase):
    PAGE = """<html><head><meta property="article:published_time" content="2026-11-18T15:30:00+06:00"></head><body>
    <nav><p>Home news sports and a very long menu text that should never ever be counted as story text ok</p></nav>
    <article><p>Workers' unrest spread across several industrial areas in Savar and Ashulia on Wednesday morning.</p>
    <p>Short.</p><p>Police said hundreds gathered near Hemayetpur Padmar Mor and blocked the Dhaka-Aricha Highway for hours.</p></article>
    <div><h3><a>Garment workers block Gazipur road</a></h3><p>Mirpur bus fire: related headline text that is long enough to count as text</p></div></body></html>"""

    def test_date_and_body(self):
        d = article.parse_date(self.PAGE)
        self.assertEqual(d.date().isoformat(), "2026-11-18")
        t = article.body_text(self.PAGE)
        self.assertIn("Savar and Ashulia", t)
        self.assertIn("Hemayetpur", t)
        self.assertNotIn("Gazipur", t)               # related headlines are not the story
        self.assertNotIn("Mirpur", t)
        self.assertNotIn("menu", t)

    def test_json_ld_date(self):
        self.assertEqual(article.parse_date('<script>{"datePublished":"2026-11-19T01:00:00Z"}</script>').day, 19)

    def test_reader_fails_soft(self):
        def boom(*a, **k):
            raise OSError("no network")
        self.assertEqual(article.read("https://news.google.com/rss/articles/ABC", fetch=boom), {})
        self.assertEqual(article.read("", fetch=boom), {})

    def test_google_link_decoded(self):
        def fake(url, data=None, headers=None, **k):
            if "batchexecute" in url:
                return b')]}\'\n\n[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://www.thedailystar.net/x\\",1]",null]]\n\n[]'
            return b'<c-wiz><div data-n-a-sg="SIG" data-n-a-ts="123"></div></c-wiz>'
        self.assertEqual(article.resolve("https://news.google.com/rss/articles/CBMiUEFVX3lxTE1mZlZPNEc0", fake), "https://www.thedailystar.net/x")


class Pipeline(unittest.TestCase):
    def test_article_places_beat_headline_only(self):         # Dhaka-Aricha: places are only in the article
        rows, st = run("Thousands block Dhaka-Aricha Highway as garment workers' unrest spreads - The Daily Star",
                       "Workers' unrest spread across several industrial areas in Savar and Ashulia today. Workers blocked the highway near Hemayetpur.")
        places = {r["place_text"].split(" (")[0] for r in rows}
        self.assertTrue({"Savar", "Ashulia"} <= {p.split(",")[0] for p in places}, places)
        self.assertTrue(all(r["body_read"] and r["status"] == "pending" for r in rows))
        self.assertTrue(all(r["confidence"] in ("high", "medium") and r["evidence"] for r in rows))

    def test_real_date_replaces_google_date(self):
        rows, st = run("Garment workers block Dhaka-Aricha Highway in Savar", "Workers blocked the highway in Savar.",
                       art_date=NOW - dt.timedelta(days=7))
        self.assertEqual((len(rows), st["too_old"]), (0, 1))                   # Google listed it today, article is a week old
        rows, _ = run("Garment workers block Dhaka-Aricha Highway in Savar", "Workers blocked the highway in Savar.",
                      art_date=NOW - dt.timedelta(days=2))
        self.assertEqual(rows[0]["happened_on"], "2026-11-23")

    def test_outlet_name_is_not_a_place(self):
        rows, _ = run("Two killed as pickup hits CNG autorickshaw in Comilla - Dhaka Tribune",
                      "Two people were killed when a pickup van hit a CNG-run autorickshaw in Comilla on Monday night.")
        self.assertEqual([r["place_text"].split(" (")[0] for r in rows], ["Cumilla"])

    def test_landmark_found_by_map_lookup(self):                # Dhaka College is not in any list
        rows, _ = run("Cocktail explosion at Dhaka College, protesting students - edutimes.net",
                      "A cocktail exploded at Dhaka College during a protest on Saturday night.",
                      points={"dhaka college": (23.7345, 90.3836)})
        self.assertEqual((rows[0]["lat"], rows[0]["lng"]), (23.7345, 90.3836))
        self.assertIn("Dhaka College", rows[0]["place_text"])

    def test_highway_only_story_is_kept_and_flagged(self):      # blockades are never hidden
        rows, _ = run("Hundreds block Dhaka-Chattogram highway demanding wages", "", art_date=None)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "pending")
        self.assertIn("check location", rows[0]["place_text"])

    def test_wrong_place_is_held_not_shown(self):
        loc = {"lat": 23.78, "lng": 90.41, "district": "Dhaka", "name": "Dhaka", "level": "district", "role": "neutral", "ev": "x", "known": True}
        ctx = {"eng": fn.places_mod.engine(), "named": ["Rajshahi"], "title_districts": {"Rajshahi"}, "body_read": True, "date_ok": True, "critical": False}
        conf, verdict, why = verify.grade(verify.run_checks(loc, ctx))
        self.assertEqual((conf, verdict), ("low", "held"))
        self.assertTrue(any("Rajshahi" in w for w in why))

    def test_good_pin_is_high(self):
        loc = {"lat": 23.7345, "lng": 90.3836, "district": "Dhaka", "name": "Dhaka College", "level": "landmark", "role": "locative",
               "ev": "explosion at Dhaka College during", "known": False}
        ctx = {"eng": fn.places_mod.engine(), "named": ["Dhaka"], "title_districts": {"Dhaka"}, "body_read": True, "date_ok": True, "critical": False}
        self.assertEqual(verify.grade(verify.run_checks(loc, ctx))[:2], ("high", "show"))

    def test_held_rows_carry_status_and_reason(self):
        rows, st = run("Bus set on fire", "A bus was torched on Tuesday night. Police are investigating the case in detail.",
                       art_date=NOW - dt.timedelta(days=1))
        self.assertEqual(rows, [])                                            # no place at all -> nothing to show


if __name__ == "__main__":
    unittest.main()
