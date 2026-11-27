"""Verification gate + article reading. Run: python3 -m unittest discover -s news -t .   (no internet)"""
import datetime as dt
import unittest

from news import article, dedupe, fetch_news as fn, llm as llm_mod, verify

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

    # ---- general patterns seen in real articles ("what happened, where") -----------------------
    def _places(self, title, body):
        rows, st = run(title, body)
        return [r["place_text"].split(" (")[0] for r in rows], rows, st

    def test_event_sentence_beats_background_mentions(self):     # "blocked the highway in Gazipur", workers/police come from Dhaka
        places, _, _ = self._places("RMG unrest: Highway blocked, police box torched, 70 factories declare holiday - Prothom Alo English",
            "Garment workers demanding higher wages staged demonstrations and blocked several sections of the Dhaka-Mymensingh highway in Gazipur on Sunday. "
            "Workers from Dhaka and Narayanganj also joined the protest, police said. Police from Dhaka were sent to the spot.")
        self.assertEqual(places, ["Dhaka-Mymensingh highway, Gazipur"])

    def test_place_must_agree_with_district_in_its_own_sentence(self):
        places, rows, _ = self._places("Bangladesh: A Havoc Of Cocktail Bombings - Analysis",
            "Multiple cocktail bomb explosions were reported in Shahjahanpur, Shyampur and Sher-e-Bangla Nagar in Dhaka city, in which four people were injured. "
            "Clashes between two factions occurred in the Bhanga Sub-district of Faridpur District.")
        self.assertFalse(any("Chapainawabganj" in p for p in places), places)

    def test_foreign_outlets_and_places_are_dropped(self):
        for t, b in [("Rickshaw Driver Killed in Bus Collision Near Chak 26 Adda - UrduPoint", "A rickshaw driver was killed in a bus collision near Chak 26 Adda."),
                     ("Kannauj School Bus Accident: 4 Children Killed, 24 Injured - Dainik Jagran", "Four children were killed when a school bus overturned near Rampur.")]:
            self.assertEqual(run(t, b)[0], [])

    def test_highway_only_headline_does_not_contradict_article(self):
        places, rows, _ = self._places("6 policemen injured as bus rams into police van on Dhaka-Chattogram Highway",
            "A bus rammed into a police van in the Chinki Astana area of Jorarganj in Chattogram early today, leaving six policemen injured.")
        self.assertEqual(places, ["Jorarganj, Chattogram"])
        self.assertEqual(rows[0]["status"], "pending")

    def test_site_footer_is_not_story_text(self):
        page = ("<article><p>A cocktail exploded in Khilgaon on Sunday night, police said, and no one was hurt in the blast.</p>"
                "<p>Media Corporation Limited, 102 Kazi Nazrul Islam Avenue, Karwan Bazar, Dhaka-1215 Phone: +880-2-55013511-15 News Room</p></article>")
        t = article.body_text(page)
        self.assertIn("Khilgaon", t)
        self.assertNotIn("Karwan", t)

    # ---- newspaper name, victim's home village, duplicates ------------------------------------
    def test_outlet_name_in_google_summary_is_not_a_place(self):
        xml = (b'<rss><channel><item><title>Awami League man dies while making crude bombs - Dhaka Tribune</title><link>https://news.google.com/rss/articles/zz</link>'
               b'<description>&lt;a href="x"&gt;Awami League man dies while making crude bombs&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font&gt;Dhaka Tribune&lt;/font&gt;</description>'
               b'<source url="https://www.dhakatribune.com">Dhaka Tribune</source></item></channel></rss>')
        item = fn.parse_feed(xml)[0]
        self.assertEqual((item["summary"], item["outlet"]), ("", "Dhaka Tribune"))
        rows, _ = fn.build_rows([{**item, "published": NOW}], geo(), 4, 30, now=NOW)
        self.assertFalse([r for r in rows if r["status"] == "pending"], rows)       # no place known: nothing is pinned (and never Dhaka)

    def test_victims_home_village_is_not_the_incident_place(self):
        body = ("An activist of the banned Awami League died when a homemade bomb exploded in Shibganj upazila of Chapainawabganj on Wednesday. "
                "The blast happened near a field in the Chowka area of Monakasha union. The dead man, Md Thomas Uddin, 35, was the son of Mortuza Ali "
                "of Bishwanathpur village under Binodpur union. The officer-in-charge of Shibganj Police Station said a case would be filed.")
        places, rows, _ = self._places("Awami League man dies while making crude bombs - Dhaka Tribune", body)
        self.assertTrue(places and all("Chapainawabganj" in p for p in places), places)
        self.assertFalse(any("Binodpur" in p for p in places), places)

    def test_whole_district_is_held_not_pinned_at_the_district_centre(self):
        rows, st = run("Two killed in road accident in Dhaka", "", art_date=None)
        self.assertEqual([r["status"] for r in rows], ["held"] if rows else [])

    def test_same_event_from_two_newspapers_is_one_pin(self):
        a = {"title": "Crude bomb explodes behind Khilgaon police station, one held - Daily Star", "type": "violence", "lat": 23.748, "lng": 90.429,
             "happened_on": "2026-11-24", "source_url": "https://n/a", "confidence": "high", "body_read": True, "radius_m": 800, "_outlet": "Daily Star"}
        b = {**a, "title": "Cocktail blast behind Khilgaon police station; man held - Dhaka Post", "lat": 23.7482, "lng": 90.4292, "source_url": "https://n/b",
             "confidence": "medium", "body_read": False, "radius_m": 1500, "_outlet": "Dhaka Post"}
        other = {**a, "title": "Bus torched in Mirpur", "lat": 23.80, "lng": 90.36, "source_url": "https://n/c"}
        rows, _ = dedupe.merge([b, a, other])
        self.assertEqual(sorted(r["source_url"] for r in rows), ["https://n/a", "https://n/c"])
        self.assertIn("Dhaka Post|https://n/b", [r for r in rows if r["source_url"] == "https://n/a"][0]["also_in"])

    def test_event_already_on_the_map_gets_an_also_reported_by_line(self):
        old = {"id": "p1", "type": "violence", "lat": 23.748, "lng": 90.429, "happened_on": "2026-11-24", "title": "Khilgaon: Crude bomb explodes behind police station",
               "also_in": None, "source_url": "https://n/a"}
        new = {"title": "Crude bomb explodes behind Khilgaon police station - Dhaka Post", "type": "violence", "lat": 23.7481, "lng": 90.4291,
               "happened_on": "2026-11-25", "source_url": "https://n/b", "radius_m": 800, "_outlet": "Dhaka Post"}
        rows, patches = dedupe.merge([new], [old])
        self.assertEqual((rows, patches), ([], [("p1", "Dhaka Post|https://n/b")]))

    def test_unreadable_page_falls_back_to_other_agent_and_amp(self):
        calls = []

        def fetch(url, headers=None, **k):
            calls.append((url, bool(headers)))
            if "news.google.com" in url:
                return b'<c-wiz><div data-n-a-sg="S" data-n-a-ts="1"></div></c-wiz>'
            if "/amp/" in url and headers:
                return b'<article><p>A bomb exploded near a field in Monakasha union of Shibganj upazila in Chapainawabganj on Wednesday afternoon.</p></article>'
            raise OSError("403")
        real = article.resolve
        article.resolve = lambda link, f=None: "https://www.dhakatribune.com/bangladesh/crime/425763/x"
        try:
            got = article.read("https://news.google.com/rss/articles/abc", fetch=fetch)
        finally:
            article.resolve = real
        self.assertIn("Monakasha", got["text"])

    # ---- optional AI second reader (always faked here: no network) ------------------------------
    def _run_ai(self, title, body, answer, points=None):
        calls = []

        def post(url, req, key, timeout):
            calls.append(1)
            import json
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(answer)}]}}]}
        reader = lambda link: {"text": body, "published": NOW - dt.timedelta(days=1)}
        llm = lambda t, x: llm_mod.ask(t, x, "k", post=post)
        items = [{"title": title, "link": "https://news.google.com/rss/articles/ai1", "summary": "", "published": NOW}]
        rows, st = fn.build_rows(items, geo(points), 4, 30, now=NOW, reader=reader, llm=llm)
        return rows, st, calls

    def test_ai_rescues_a_story_the_rules_cannot_place(self):
        body = "Unidentified miscreants hurled crude bombs at a party office in Kachua upazila late on Tuesday night, leaving two people injured, locals said."
        ans = {"abroad": False, "district": "Chandpur", "upazila_or_thana": "Kachua", "union_or_area": None, "road_or_landmark": None,
               "evidence": "office in Kachua upazila", "confidence": "high"}
        rows, st, calls = self._run_ai("Crude bombs hurled at party office, two hurt", body, ans)
        self.assertEqual((len(calls), st["ai_rescued"]), (1, 1))
        self.assertTrue(rows and "Chandpur" in rows[0]["place_text"], rows)

    def test_ai_answer_with_invented_evidence_is_ignored(self):
        ans = {"abroad": False, "district": "Khulna", "upazila_or_thana": None, "union_or_area": None, "road_or_landmark": None,
               "evidence": "in the heart of Khulna city", "confidence": "high"}
        self.assertIsNone(llm_mod.ask("Bus torched", "A bus was torched on Tuesday night.", "k",
                                      post=lambda *a: {"candidates": [{"content": {"parts": [{"text": __import__("json").dumps(ans)}]}}]}))

    def test_ai_disagreement_is_flagged_not_hidden(self):
        body = "Workers blocked the highway in Gazipur on Sunday and clashed with police, who fired tear gas near the factory gate."
        ans = {"abroad": False, "district": "Narayanganj", "upazila_or_thana": None, "union_or_area": None, "road_or_landmark": None,
               "evidence": "in Gazipur on Sunday", "confidence": "medium"}
        rows, st, calls = self._run_ai("Workers block highway, clash with police", body, ans)
        self.assertEqual(st["ai_disagree"], 1)
        self.assertTrue(all("AI second reading says" in r["checks"] and r["confidence"] != "high" for r in rows), rows)

    def test_ai_failure_or_no_key_changes_nothing(self):
        self.assertIsNone(llm_mod.ask("t", "x", None))
        def boom(*a):
            raise OSError("offline")
        self.assertIsNone(llm_mod.ask("t", "x", "k", post=boom))
        import urllib.error
        def limited(*a):
            raise urllib.error.HTTPError("u", 429, "limit", {}, None)
        with self.assertRaises(llm_mod.RateLimited):
            llm_mod.ask("t", "x", "k", post=limited)

    def test_police_station_that_handles_the_case_is_not_the_incident_place(self):
        from news import story
        for t, name in [("Khilgaon Police Station seeks assistance in identifying a woman who died at Kuril.", "Khilgaon"),
                        ("Police at Sutrapur Police Station filed a case in connection with the incident.", "Sutrapur"),
                        ("Matiur Rahman, officer-in-charge of Shibganj Police Station, said a case would be filed.", "Shibganj")]:
            i = t.find(name)
            self.assertEqual(story.role_of(t, i, i + len(name)), "neutral", t)
        t = "A bus was set on fire near Sarail police station on Tuesday."
        self.assertEqual(story.role_of(t, t.find("Sarail"), t.find("Sarail") + 6), "locative")

    def test_ai_coordinates_are_only_a_cross_check(self):
        body = "Workers blocked the highway in Gazipur on Sunday and clashed with police, who fired tear gas near the factory gate."
        ans = {"abroad": False, "district": "Gazipur", "upazila_or_thana": None, "union_or_area": None, "road_or_landmark": None,
               "evidence": "in Gazipur on Sunday", "confidence": "medium", "latitude": 22.0, "longitude": 91.8}
        rows, st, calls = self._run_ai("Workers block highway, clash with police", body, ans)
        if calls:
            self.assertTrue(all("coordinate estimate" in r["checks"] for r in rows), rows)

    def test_retired_model_falls_back_to_the_next(self):
        import json, urllib.error
        llm_mod._RETIRED.clear()
        seen = []

        def post(url, req, key, timeout):
            seen.append(url.split("models/")[1].split(":")[0])
            if len(seen) == 1:
                raise urllib.error.HTTPError(url, 404, "gone", {}, __import__("io").BytesIO(b'{"error":{"message":"model retired"}}'))
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({"abroad": False, "district": "Gazipur", "evidence": "in Gazipur on Sunday"})}]}}]}
        got = llm_mod.ask("Workers block road", "Workers blocked the road in Gazipur on Sunday.", "k", post=post)
        self.assertEqual(got["district"], "Gazipur")
        self.assertEqual(len(seen), 2)
        llm_mod._RETIRED.clear()

    def test_busy_model_is_retried_on_the_next_model(self):
        import json, urllib.error
        llm_mod._RETIRED.clear()
        old, llm_mod.sleep = llm_mod.sleep, lambda s: None
        seen = []

        def post(url, req, key, timeout):
            seen.append(url.split("models/")[1].split(":")[0])
            if len(seen) < 3:
                raise urllib.error.HTTPError(url, 503, "busy", {}, __import__("io").BytesIO(b'{"error":{"message":"high demand"}}'))
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({"abroad": False, "district": "Gazipur", "evidence": "in Gazipur on Sunday"})}]}}]}
        try:
            got = llm_mod.ask("Workers block road", "Workers blocked the road in Gazipur on Sunday.", "k", post=post)
        finally:
            llm_mod.sleep = old
        self.assertEqual((got["district"], len(seen)), ("Gazipur", 3))
        self.assertEqual(len(set(seen)), 3)

    def test_held_rows_carry_status_and_reason(self):
        rows, st = run("Bus set on fire", "A bus was torched on Tuesday night. Police are investigating the case in detail.",
                       art_date=NOW - dt.timedelta(days=1))
        self.assertEqual(rows, [])                                            # no place at all -> nothing to show


if __name__ == "__main__":
    unittest.main()
