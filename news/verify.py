"""Verification gate: every pin must pass several independent checks before it is shown on the map.

Each check returns ("pass" | "warn" | "fail", note). The grade is then:
    any fail              -> held back (not shown; listed in the run summary and the admin "Held" tab)
    3 or more warnings    -> held back, unless the story is a blockade / road closure (those are never hidden)
    1-2 warnings          -> shown as "medium" (the admin sees which checks warned)
    no warnings           -> shown as "high"
"""
import re


BBOX = (20.5, 26.7, 87.8, 92.8)


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def run_checks(loc, ctx):
    """ctx: {eng, text, title, title_districts(set), named(list of districts the story names), body_read, date_ok(bool|None), critical}"""
    eng, out = ctx.get("eng"), []
    lat, lng = loc["lat"], loc["lng"]

    # 1. Inside Bangladesh and inside a known district
    if not (BBOX[0] <= lat <= BBOX[1] and BBOX[2] <= lng <= BBOX[3]):
        out.append(("fail", "pin is outside Bangladesh"))
    else:
        d = eng.district_at(lat, lng) if eng else None
        out.append(("pass", f"pin is inside {d}") if d else ("warn", "pin is not inside any district border"))

    # 2. Evidence: the place is written in the story, and says what part it plays
    ev, role, name = loc.get("ev"), loc.get("role"), loc.get("name")
    if loc.get("level") == "highway":
        out.append(("warn", "story names the highway but not where on it"))
    elif ev and name and _norm(name) in _norm(ev) or (ev and loc.get("known") is False):
        out.append(("pass", f"\"{name}\" is written in the story"))
    elif ev:
        out.append(("pass", "place found in the story"))
    else:
        out.append(("fail", "no sentence in the story supports this place"))
    if role == "origin":
        out.append(("fail", "place is only where someone comes from"))
    elif role in ("locative", "dateline"):
        out.append(("pass", f"story says it happened there ({role})"))
    elif loc.get("level") != "highway" and ctx.get("body_read"):
        out.append(("warn", "story does not clearly say it happened there"))

    # 3. Named districts: the pin must lie in (or at the border of) a district the story names
    named = ctx.get("named") or []
    if named and eng:
        out.append(("pass", "pin is in a district the story names") if eng.fits(lat, lng, named)
                   else ("fail", f"story names {', '.join(sorted(set(named)))} but the pin is elsewhere"))
    elif loc.get("level") not in ("highway", "district", "city"):
        out.append(("warn", "story names no district to cross-check"))

    # 4. Second opinion: the headline alone, read separately, must not disagree with the pin
    td, pd = ctx.get("title_districts") or set(), loc.get("district")
    if td and pd:
        out.append(("pass", "headline and article agree on the district") if pd in td
                   else ("fail", f"headline says {', '.join(sorted(td))}, pin is in {pd}"))
    elif ctx.get("body_read"):
        out.append(("pass", "article text read"))
    else:
        out.append(("warn", "only the headline was available"))

    # 4b. The place must sit in a sentence that describes the incident (not background, an address or a name in passing)
    if ctx.get("body_read") and loc.get("evsent") is False:
        out.append(("warn", "place is mentioned outside the sentences describing the incident"))
    # 4c. Small or guessed places with no district anywhere in the story are ambiguous (many villages share a name)
    if not named and not td and loc.get("level") in ("union", "upazila", "landmark", "area") and loc.get("source_kind") != "curated":
        out.append(("fail", "small place with no district anywhere in the story (the name may belong to another country or district)"))
    if len(set(ctx.get("named") or [])) >= 4:
        out.append(("warn", "article covers many districts (round-up): check each pin"))

    # 5. Precision
    lvl = loc.get("level")
    if lvl in ("area", "union", "landmark", "upazila"):
        out.append(("pass", f"precise place ({lvl})"))
    elif lvl in ("district", "city") and not ctx.get("critical"):
        out.append(("fail", "only the whole district is known: too vague to put on the map"))     # a district centre is a misleading spot (e.g. Dhaka -> Baridhara)
    else:
        out.append(("warn", "whole district or highway only"))

    # 6. Highway: if a highway is named the pin must be on or near it
    if loc.get("corridor") and loc.get("corridor_km") is not None and loc["corridor_km"] > 35:
        out.append(("fail", f"pin is {loc['corridor_km']:.0f} km from {loc['corridor']}"))

    # 6b. AI second reader (only present for stories the rules were unsure about)
    ai = ctx.get("llm")
    if loc.get("ai_only"):
        out.append(("warn", "place found by the AI reader only (the rules found none): check it"))
    elif ai is not None:
        out.append(("pass", "AI second reading agrees on the place") if ai["agree"] else ("warn", f"AI second reading says {ai['where']}: check it"))
        km = ai.get("coord_km")                                             # the AI's own coordinates are only a cross-check, never the pin
        if km is not None:
            out.append(("pass", f"AI's coordinate estimate is {km:.0f} km from the pin") if km <= 15 else ("warn", f"AI's coordinate estimate is {km:.0f} km away from the pin"))

    # 7. Date
    dok = ctx.get("date_ok")
    out.append(("pass", "real publish date read from the article") if dok else ("info", "publish date not verified (feed date used)"))
    return out


def grade(checks, critical=False):
    fails = [n for s, n in checks if s == "fail"]
    warns = [n for s, n in checks if s == "warn"]
    if fails:
        return ("low" if not critical else "medium"), "held" if not critical else "show", fails + warns
    if len(warns) >= 3 and not critical:
        return "low", "held", warns
    return ("medium" if warns else "high"), "show", warns


def summary(checks):
    return "; ".join(("✓ " if s == "pass" else "ℹ " if s == "info" else "⚠ " if s == "warn" else "✗ ") + n for s, n in checks)
