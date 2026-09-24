"""Wikidata: la única fuente gratuita de influencias con estructura.

La propiedad P737 ("influenced by") dice de quién bebe un artista, y leída al
revés, quién bebe de él. La cobertura es desigual: los artistas canónicos
suelen estar bien descritos y los grupos recientes mucho menos, así que sirve
más para los "abuelos" que para los nietos. Es evidencia, no la verdad
completa: que algo no esté aquí no significa que no sea una influencia.

API pública sin clave; Wikimedia exige un User-Agent identificable.
"""
import logging

import httpx

log = logging.getLogger("playlist_lab.wikidata")
API = "https://www.wikidata.org/w/api.php"
SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "playlist-lab/0.3 (herramienta personal; "
                         "https://github.com/SentoTM/playlist-lab)",
           "Accept": "application/json"}

# Palabras que delatan que una entidad es de música (para no confundir a
# "Wire" el grupo con un cable, o a "Television" el grupo con la tele)
_MUSICAL = ("band", "musician", "singer", "rapper", "group", "composer",
            "songwriter", "duo", "rock", "punk", "musical", "dj", "producer",
            "grupo", "músic", "cantante", "banda")


class WikidataClient:
    def __init__(self):
        self._http = httpx.Client(timeout=25, headers=HEADERS, follow_redirects=True)

    def _get(self, url: str, **params):
        try:
            resp = self._http.get(url, params=params)
            if resp.status_code != 200:
                log.warning("Wikidata %s en %s", resp.status_code, url)
                return None
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Wikidata falló: %s", e)
            return None

    def buscar_artista(self, nombre: str) -> dict | None:
        """La entidad musical con ese nombre (Q-id, etiqueta, descripción)."""
        data = self._get(API, action="wbsearchentities", search=nombre,
                         language="en", uselang="en", type="item", limit=8,
                         format="json")
        for r in (data or {}).get("search", []):
            desc = (r.get("description") or "").lower()
            if any(p in desc for p in _MUSICAL):
                return {"qid": r["id"], "nombre": r.get("label"),
                        "descripcion": r.get("description")}
        return None

    def _sparql(self, consulta: str) -> list[dict]:
        data = self._get(SPARQL, query=consulta, format="json")
        filas = ((data or {}).get("results") or {}).get("bindings") or []
        out = []
        for f in filas:
            nombre = (f.get("xLabel") or {}).get("value")
            qid = ((f.get("x") or {}).get("value") or "").rsplit("/", 1)[-1]
            # si no hay etiqueta, Wikidata devuelve el propio Q-id: fuera
            if nombre and not (nombre.startswith("Q") and nombre[1:].isdigit()):
                out.append({"nombre": nombre, "qid": qid})
        return out

    def influido_por(self, qid: str) -> list[dict]:
        """De quién bebe (P737 del propio artista)."""
        return self._sparql(
            f"SELECT ?x ?xLabel WHERE {{ wd:{qid} wdt:P737 ?x . "
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,es". } }')

    def influyo_en(self, qid: str, limite: int = 60) -> list[dict]:
        """Quién bebe de él (P737 de otros apuntando a este artista)."""
        return self._sparql(
            f"SELECT ?x ?xLabel WHERE {{ ?x wdt:P737 wd:{qid} . "
            'SERVICE wikibase:label { bd:serviceParam wikibase:language "en,es". } } '
            f"LIMIT {limite}")
