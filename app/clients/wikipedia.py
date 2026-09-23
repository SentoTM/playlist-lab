"""Cliente de Wikipedia: contexto e historia, en español con respaldo en inglés.

API pública, sin claves. Sirve para lo que ni Spotify ni Last.fm dan: de
dónde sale un grupo, qué fue una escena, por qué un disco importó. Se busca
primero en español (mejor para escenas locales) y, si no hay nada, en inglés
(mucho mejor para escenas anglosajonas y subgéneros).
"""
import logging
import re
import unicodedata
from urllib.parse import quote

import httpx

log = logging.getLogger("playlist_lab.wikipedia")
HEADERS = {"User-Agent": "playlist-lab/0.2 (herramienta personal; https://github.com/SentoTM/playlist-lab)",
           "Accept": "application/json"}


def _flat(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]+", " ", s)


def _es_del_tema(query: str, titulo: str, resumen: str) -> bool:
    """Evita el falso positivo clásico: buscar un grupo y que la búsqueda
    devuelva el festival donde tocó. Exige que el nombre aparezca en el
    título, o en la primera frase del resumen (donde se define el sujeto)."""
    q, t = _flat(query), _flat(titulo)
    if not q:
        return False
    # sin espacios también: "coldwave" debe casar con "Cold wave (música)"
    qc, tc = q.replace(" ", ""), t.replace(" ", "")
    if q in t or qc in tc:
        return True
    # el sujeto se define en la primera frase: se parte ANTES de normalizar,
    # porque la normalización se come los puntos
    primera = _flat((resumen or "").split(".")[0])
    return q in primera or qc in primera.replace(" ", "")


# Buscar "Gurriers banda grupo musical" en la Wikipedia inglesa no encuentra
# nada: la pista tiene que ir en el idioma de cada edición.
_PISTAS_EN = {"banda grupo musical": "band", "género musical": "music genre",
              "álbum": "album", "música escena": "music scene"}


def _traducir_pista(pista: str, lang: str) -> str:
    if not pista or lang == "es":
        return pista
    return _PISTAS_EN.get(pista, "")


class WikipediaClient:
    def __init__(self, langs: tuple[str, ...] = ("es", "en")):
        self.langs = langs
        self._http = httpx.Client(timeout=20, headers=HEADERS, follow_redirects=True)

    def _search(self, lang: str, query: str, limit: int) -> list[dict]:
        try:
            resp = self._http.get(f"https://{lang}.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": limit, "format": "json", "srnamespace": 0,
            })
            resp.raise_for_status()
            return resp.json().get("query", {}).get("search", [])
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Wikipedia búsqueda '%s' (%s): %s", query, lang, e)
            return []

    def _summary(self, lang: str, title: str) -> dict:
        try:
            resp = self._http.get(
                f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
                f"{quote(title.replace(' ', '_'), safe='')}")
            if resp.status_code != 200:
                return {}
            d = resp.json()
            if d.get("type", "").endswith("disambiguation"):
                return {}
            return {
                "titulo": d.get("title"),
                "resumen": d.get("extract", ""),
                "url": (d.get("content_urls", {}).get("desktop", {}) or {}).get("page"),
                "idioma": lang,
            }
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Wikipedia resumen '%s' (%s): %s", title, lang, e)
            return {}

    def lookup(self, query: str, hint: str = "") -> dict:
        """Resumen del artículo que mejor case con `query`.

        `hint` acota la búsqueda ('banda', 'álbum', 'género musical') para no
        acabar en el artículo equivocado cuando el nombre es ambiguo.
        """
        for lang in self.langs:
            pista = _traducir_pista(hint, lang)
            intentos = [f"{query} {pista}".strip(), query] if pista else [query]
            for consulta in intentos:
                for result in self._search(lang, consulta, 3):
                    summary = self._summary(lang, result["title"])
                    if not summary or not summary.get("resumen"):
                        continue
                    if _es_del_tema(query, summary["titulo"], summary["resumen"]):
                        return summary
        return {}
