"""Read the article behind a Google News link: its real publish date and the first paragraphs.

Why: the feed gives only the headline, and Google shows the day it LISTED a story, not the day it was written.
The article itself names the real places ("Savar, Ashulia, Hemayetpur") and carries the real date.
Everything here fails soft: if anything goes wrong the caller keeps working from the headline.
"""
import base64
import datetime as dt
import html
import json
import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; web_map-road-safety/1.0; +https://github.com/towfiqccdc/web_map)"
GN_ID = re.compile(r"news\.google\.com/(?:rss/)?(?:articles|read)/([A-Za-z0-9_-]+)")


def _get(url, timeout=12, data=None, headers=None, limit=600_000):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def google_id(link):
    m = GN_ID.search(link or "")
    return m.group(1) if m else None


def decode_local(gid):
    """Older Google links carry the publisher URL inside the id itself."""
    try:
        raw = base64.urlsafe_b64decode(gid + "=" * (-len(gid) % 4))
    except Exception:
        return None
    m = re.search(rb"https?://[\x21-\x7e]+", raw)
    return m.group(0).decode() if m and not raw.startswith(b"\x08\x13\x22") else None


def resolve(link, fetch=_get):
    """Publisher URL for a Google News link, or None."""
    gid = google_id(link)
    if not gid:
        return link if link and "news.google.com" not in link else None
    local = decode_local(gid)
    if local:
        return local
    page = fetch(f"https://news.google.com/rss/articles/{gid}").decode("utf-8", "ignore")
    sg = re.search(r'data-n-a-sg="([^"]+)"', page)
    ts = re.search(r'data-n-a-ts="([^"]+)"', page)
    if not (sg and ts):
        return None
    inner = ('["garturlreq",[["X","X",["X","X"],null,null,1,1,"US:en",null,1,null,null,null,null,null,0,1],'
             f'"X","X",1,[1,1,1],1,1,null,0,0,null,0],"{gid}",{ts.group(1)},"{sg.group(1)}"]')
    body = "f.req=" + urllib.parse.quote(json.dumps([[["Fbv4je", inner]]]))
    out = fetch("https://news.google.com/_/DotsSplashUi/data/batchexecute", data=body.encode(),
                headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"}).decode("utf-8", "ignore")
    try:
        return json.loads(json.loads(out.split("\n\n")[1])[0][2])[1]
    except Exception:
        return None


DATE_KEYS = (r'property=["\']article:published_time["\']\s+content=["\']([^"\']+)',
             r'content=["\']([^"\']+)["\']\s+property=["\']article:published_time',
             r'itemprop=["\']datePublished["\']\s+content=["\']([^"\']+)',
             r'"datePublished"\s*:\s*"([^"]+)"',
             r'name=["\'](?:pubdate|publish-date|date)["\']\s+content=["\']([^"\']+)')


def parse_date(page):
    """First usable publish date in the page (a datetime, UTC-naive-safe) or None."""
    for pat in DATE_KEYS:
        for raw in re.findall(pat, page, re.I):
            raw = raw.strip()
            try:
                d = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                try:
                    d = dt.datetime.strptime(raw[:10], "%Y-%m-%d")
                except ValueError:
                    continue
            if d.tzinfo is None:
                d = d.replace(tzinfo=dt.timezone(dt.timedelta(hours=6)))      # Bangladesh outlets
            return d.astimezone(dt.timezone.utc)
    return None


def body_text(page, max_chars=2600):
    """The story's own paragraphs. Related-headline lists live in links/headings, so only real <p> text is kept."""
    page = re.sub(r"(?is)<(script|style|nav|footer|aside|header|form|figure|noscript)\b.*?</\1>", " ", page)
    art = re.search(r"(?is)<article\b.*?</article>", page)
    scope = art.group(0) if art else page
    paras = []
    for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", scope):
        t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", p))).strip()
        if len(t) >= 60 and not re.search(r"(?i)read more|also read|follow us|subscribe|copyright|advertisement", t):
            paras.append(t)
    return " ".join(paras)[:max_chars]


def read(link, fetch=_get):
    """{"url", "published", "text"} for a feed link; any failure returns {}."""
    try:
        url = resolve(link, fetch)
        if not url:
            return {}
        page = fetch(url).decode("utf-8", "ignore")
        return {"url": url, "published": parse_date(page), "text": body_text(page)}
    except Exception:
        return {}
