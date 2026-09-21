"""Prensa musical por RSS: qué se está publicando y reseñando ahora.

Feeds públicos, sin claves ni scraping. Se parsean con la librería estándar
(RSS 2.0 y Atom). Cada fuente falla por separado: si una cae, el resto sigue.
"""
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

log = logging.getLogger("playlist_lab.press")

FEEDS = {
    "pitchfork": ("Pitchfork", "https://pitchfork.com/feed/feed-album-reviews/rss"),
    "pitchfork_news": ("Pitchfork · noticias", "https://pitchfork.com/feed/feed-news/rss"),
    "quietus": ("The Quietus", "https://thequietus.com/feed/"),
    "bandcamp": ("Bandcamp Daily", "https://daily.bandcamp.com/feed"),
    "mondosonoro": ("Mondo Sonoro", "https://www.mondosonoro.com/feed/"),
    "jenesaispop": ("Jenesaispop", "https://jenesaispop.com/feed/"),
    "stereogum": ("Stereogum", "https://www.stereogum.com/feed/"),
    "brooklynvegan": ("BrooklynVegan", "https://www.brooklynvegan.com/feed/"),
}

_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str | None, limit: int = 400) -> str:
    if not text:
        return ""
    text = _TAGS.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _date(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc).date().isoformat()
    except (TypeError, ValueError):
        return raw[:10]


def _parse(xml: str, source: str) -> list[dict]:
    root = ET.fromstring(xml)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        def txt(*names):
            for n in names:
                el = it.find(n) if "}" not in n else it.find(n, ns)
                if el is None:
                    el = it.find(f"{{http://www.w3.org/2005/Atom}}{n}")
                if el is not None and (el.text or el.get("href")):
                    return el.text or el.get("href")
            return None
        link = txt("link")
        if link is None:
            el = it.find("{http://www.w3.org/2005/Atom}link")
            link = el.get("href") if el is not None else None
        items.append({
            "source": source,
            "title": _clean(txt("title"), 200),
            "date": _date(txt("pubDate", "published", "updated")),
            "summary": _clean(txt("description", "summary", "content")),
            "url": link,
        })
    return items


class PressClient:
    def __init__(self, feeds: dict | None = None):
        self.feeds = feeds or FEEDS
        self._http = httpx.Client(timeout=20, follow_redirects=True,
                                  headers={"User-Agent": "playlist-lab/0.2"})

    def fetch(self, sources: list[str] | None = None, limit_per_source: int = 8,
              since_days: int | None = None) -> dict:
        """Artículos recientes. sources: claves de FEEDS (todas si se omite)."""
        keys = [s for s in (sources or self.feeds) if s in self.feeds]
        warnings = []

        def one(key: str) -> list[dict]:
            label, url = self.feeds[key]
            try:
                resp = self._http.get(url)
                resp.raise_for_status()
                return _parse(resp.text, label)[:limit_per_source]
            except (httpx.HTTPError, ET.ParseError) as e:
                log.warning("Feed %s falló: %s", key, e)
                warnings.append(f"{label}: no se pudo leer ({type(e).__name__})")
                return []

        with ThreadPoolExecutor(max_workers=6) as pool:
            batches = list(pool.map(one, keys))

        items = [i for b in batches for i in b]
        if since_days:
            cutoff = (datetime.now(timezone.utc).date()
                      - timedelta(days=since_days)).isoformat()
            items = [i for i in items if (i["date"] or "") >= cutoff]
        items.sort(key=lambda i: i["date"] or "", reverse=True)
        return {"items": items, "warnings": warnings,
                "fuentes": [self.feeds[k][0] for k in keys]}
