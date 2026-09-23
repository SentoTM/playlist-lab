"""KEXP: qué está pinchando de verdad una radio con criterio.

La API pública de KEXP (api.kexp.org, sin clave) expone cada canción que han
emitido, con artista, disco, sello y fecha. Es una señal distinta a todas las
demás: no es popularidad agregada ni una etiqueta de la comunidad, es lo que
unos programadores humanos han decidido poner esta semana. Para encontrar
bandas emergentes antes de que existan cifras, es de lo mejor que hay gratis.
"""
import datetime as dt
import logging
from collections import Counter

import httpx

log = logging.getLogger("playlist_lab.kexp")

# La rotación dice cuánto está APOSTANDO la emisora por una canción: Heavy es
# una apuesta fuerte por algo nuevo; Library es fondo de catálogo. Pesa más
# que el simple número de emisiones, que depende del azar de la muestra.
PESO_ROTACION = {"Heavy": 3.0, "Medium": 2.0, "Light": 1.0, "R/N": 1.0,
                 "Recurrent": 0.5, "Library": 0.0}


def _sello(p: dict):
    sello = (p.get("labels") or [None])[0]
    return None if sello in (None, "", "[no label]") else sello


def _es_sesion(p: dict) -> bool:
    """Las sesiones en directo de KEXP salen como disco 'Live on KEXP'."""
    return "live on kexp" in (p.get("album") or "").lower() or _sello(p) == "KEXP"
API = "https://api.kexp.org/v2"
HEADERS = {"User-Agent": "playlist-lab/0.2 (uso personal)", "Accept": "application/json"}


class KexpClient:
    def __init__(self):
        self._http = httpx.Client(timeout=25, headers=HEADERS)

    def _get(self, path: str, **params) -> dict:
        try:
            resp = self._http.get(f"{API}{path}", params=params)
            if resp.status_code != 200:
                log.warning("KEXP %s en %s", resp.status_code, path)
                return {}
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("KEXP falló en %s: %s", path, e)
            return {}

    def plays(self, limit: int = 100, desde_dias: int = 7,
              max_paginas: int = 5) -> list[dict]:
        """Emisiones recientes. Devuelve solo canciones (no cortinillas)."""
        desde = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=desde_dias)).isoformat()
        out: list[dict] = []
        offset = 0
        for _ in range(max_paginas):
            data = self._get("/plays/", limit=min(limit, 100), offset=offset,
                             airdate_after=desde)
            filas = data.get("results") or []
            for p in filas:
                if p.get("play_type") != "trackplay" or not p.get("artist"):
                    continue
                out.append({
                    "artist": p.get("artist"),
                    "song": p.get("song"),
                    "album": p.get("album"),
                    "sello": _sello(p),
                    "año": (p.get("release_date") or "")[:4],
                    "fecha_emision": (p.get("airdate") or "")[:10],
                    "rotacion": p.get("rotation_status"),
                    "sesion_en_directo": _es_sesion(p),
                    "local": p.get("is_local"),
                })
            if len(filas) < min(limit, 100) or len(out) >= limit:
                break
            offset += len(filas)
        return out[:limit]

    def artistas_mas_pinchados(self, desde_dias: int = 7,
                               muestras: int = 400) -> list[dict]:
        """Ranking de lo más emitido en los últimos días.

        Un artista que suena varias veces en una semana está siendo apoyado
        por la emisora, no es una coincidencia.
        """
        plays = self.plays(limit=muestras, desde_dias=desde_dias)
        veces: Counter = Counter()
        apuesta: Counter = Counter()
        ejemplo: dict[str, dict] = {}
        sesion: set[str] = set()
        for p in plays:
            a = p["artist"]
            veces[a] += 1
            apuesta[a] += PESO_ROTACION.get(p.get("rotacion") or "", 0.5)
            if p.get("sesion_en_directo"):
                sesion.add(a)
            # como ejemplo, mejor un disco de estudio que la sesión
            if a not in ejemplo or (ejemplo[a].get("sesion_en_directo")
                                    and not p.get("sesion_en_directo")):
                ejemplo[a] = p
        # un artista sin rotación (solo fondo de catálogo) no es una apuesta
        puntua = {a: apuesta[a] + (2.0 if a in sesion else 0.0) for a in veces}
        ranking = sorted(veces, key=lambda a: (puntua[a], veces[a]), reverse=True)
        return [{"artist": a, "veces_emitido": veces[a],
                 "apuesta_de_la_emisora": round(puntua[a], 1),
                 "sesion_en_directo": a in sesion,
                 "rotacion": ejemplo[a].get("rotacion"),
                 "ejemplo": {k: ejemplo[a].get(k)
                             for k in ("song", "album", "sello", "año")}}
                for a in ranking[:60]]

    def emisiones_de(self, artista: str, desde_dias: int = 365) -> list[dict]:
        """¿Ha pinchado KEXP a este artista? Señal de que alguien con criterio
        le presta atención, aunque sus cifras sean pequeñas."""
        desde = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(days=desde_dias)).isoformat()
        data = self._get("/plays/", artist=artista, limit=30, airdate_after=desde)
        return [{"song": p.get("song"), "album": p.get("album"),
                 "fecha_emision": (p.get("airdate") or "")[:10],
                 "rotacion": p.get("rotation_status"),
                 "sesion_en_directo": _es_sesion(p)}
                for p in (data.get("results") or [])
                if p.get("play_type") == "trackplay"]
