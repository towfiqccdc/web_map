"""Optional AI second reader (Google Gemini, free tier). Used only for stories the rules are unsure about.

The model never gives coordinates. It only answers "which district / upazila / area, and which words in the text say so".
The answer is accepted only if the quoted words really appear in the text, then it is turned into a place by the SAME
official place list the rules use, and compared with the rules' answer. Any failure just means "no second opinion".
"""
import json
import re
import urllib.error
import urllib.request

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-2.5-flash"
MAX_TEXT = 2200

PROMPT = """You read Bangladeshi news. Say WHERE IN BANGLADESH the incident in this story happened. Use only the text.
Ignore: where victims or suspects live or come from ("son of", "resident of", "village under"), newspaper names, addresses and phone numbers,
places that are only background or are where people travelled from. If the incident happened outside Bangladesh, set abroad to true.
Answer with JSON only:
{"abroad": true|false, "district": string|null, "upazila_or_thana": string|null, "union_or_area": string|null, "road_or_landmark": string|null,
 "evidence": "the exact words copied from the text that state the place", "confidence": "high"|"medium"|"low",
 "latitude": number|null, "longitude": number|null}
latitude and longitude are your best estimate of the place named, or null if you are not sure. Never guess them.
Use English spellings of official place names. Use null when the text does not say. Never guess."""


class RateLimited(Exception):
    pass


STATS = {}          # what happened to each question, so the run log can say whether Gemini answered
SAMPLES = []        # the first few error messages (never contains the key)


def _count(name, detail=None):
    STATS[name] = STATS.get(name, 0) + 1
    if detail and len(SAMPLES) < 3:
        SAMPLES.append(f"{name}: {detail}"[:240])


def _post(url, body, key, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def _norm(s):
    return re.sub(r"\W+", " ", (s or "").lower()).strip()


def ask(title, text, key, model=DEFAULT_MODEL, post=_post, timeout=30):
    """Dict with district / upazila_or_thana / union_or_area / road_or_landmark / evidence / abroad, or None."""
    if not key:
        return None
    body = {"contents": [{"parts": [{"text": f"{PROMPT}\n\nHEADLINE: {title}\nTEXT: {(text or '')[:MAX_TEXT]}"}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
    try:
        out = post(ENDPOINT.format(model=model), body, key, timeout)
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8", "ignore")).get("error", {}).get("message", "")
        except Exception:
            detail = ""
        _count(f"http_{e.code}", detail)
        if e.code == 429:
            raise RateLimited(str(e.code))
        return None
    except Exception as e:
        _count("network_error", repr(e))
        return None
    try:
        raw = out["candidates"][0]["content"]["parts"][0]["text"]
        ans = json.loads(raw)
        if isinstance(ans, list):
            ans = ans[0]
    except Exception:
        _count("unreadable_answer", str(out)[:160])
        return None
    if not isinstance(ans, dict):
        _count("unreadable_answer", str(ans)[:160])
        return None
    if ans.get("abroad") is True:
        _count("answered_abroad")
        return {"abroad": True}
    ev = _norm(ans.get("evidence"))
    if len(ev) < 6 or ev not in _norm(f"{title}. {text}"):               # the words it quotes must really be in the story
        _count("quote_not_in_story", str(ans.get("evidence"))[:100])
        return None
    keep = {k: (str(ans[k]).strip() if ans.get(k) else None) for k in ("district", "upazila_or_thana", "union_or_area", "road_or_landmark")}
    if not any(keep.values()):
        _count("no_place_in_answer")
        return None
    _count("answered_with_place")
    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    la, lo = num(ans.get("latitude")), num(ans.get("longitude"))
    if la is not None and lo is not None and not (20.5 <= la <= 26.7 and 87.8 <= lo <= 92.8):
        la = lo = None
    return {"abroad": False, **keep, "evidence": str(ans["evidence"])[:300], "confidence": ans.get("confidence"), "lat": la, "lng": lo}


def as_sentence(ans):
    """The answer written as a plain sentence, so the normal place rules can resolve it."""
    parts = [p for p in (ans.get("road_or_landmark"), ans.get("union_or_area"), ans.get("upazila_or_thana")) if p]
    where = ", ".join(parts + ([ans["district"]] if ans.get("district") else []))
    return f"Incident reported in {where}."
