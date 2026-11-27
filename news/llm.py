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
 "evidence": "the exact words copied from the text that state the place", "confidence": "high"|"medium"|"low"}
Use English spellings of official place names. Use null when the text does not say. Never guess."""


class RateLimited(Exception):
    pass


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
        if e.code in (429, 403):
            raise RateLimited(str(e.code))
        return None
    except Exception:
        return None
    try:
        ans = json.loads(out["candidates"][0]["content"]["parts"][0]["text"])
        if isinstance(ans, list):
            ans = ans[0]
    except Exception:
        return None
    if not isinstance(ans, dict):
        return None
    if ans.get("abroad") is True:
        return {"abroad": True}
    ev = _norm(ans.get("evidence"))
    if len(ev) < 6 or ev not in _norm(f"{title}. {text}"):               # the words it quotes must really be in the story
        return None
    keep = {k: (str(ans[k]).strip() if ans.get(k) else None) for k in ("district", "upazila_or_thana", "union_or_area", "road_or_landmark")}
    if not any(keep.values()):
        return None
    return {"abroad": False, **keep, "evidence": str(ans["evidence"])[:300], "confidence": ans.get("confidence")}


def as_sentence(ans):
    """The answer written as a plain sentence, so the normal place rules can resolve it."""
    parts = [p for p in (ans.get("road_or_landmark"), ans.get("union_or_area"), ans.get("upazila_or_thana")) if p]
    where = ", ".join(parts + ([ans["district"]] if ans.get("district") else []))
    return f"Incident reported in {where}."
