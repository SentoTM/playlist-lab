"""Cliente de la API pública de Deezer: el catálogo, sin gastar cuota de Spotify.

Por qué Deezer: es gratis, no pide clave, tiene buen catálogo español (mucho
mejor que MusicBrainz, que se dejaba a Lori Meyers, La 126 o Niños) y cada
lanzamiento trae `record_type` (album, ep, single, compile) y fecha de
salida. Para saber qué ha publicado un artista es lo más parecido a la
discografía de Spotify sin tocar la cuota compartida del modo desarrollo.

Límites: unas 50 peticiones cada 5 s por IP. Si se pasa, Deezer no responde
con un 429 sino con un 200 cuyo cuerpo es {"error": {"code": 4, "message":
"Quota limit exceeded"}}: hay que mirar el JSON, no el código HTTP. Aquí se
reparte el ritmo con una ventana deslizante (45 cada 5 s, con margen) y, si
aun así llega el error de cuota, se espera y se reintenta.

Caché en disco (datos/deezer.json, aparte de cache.json porque son cientos
de entradas): el id de cada artista no cambia, así que se guarda para
siempre; su lista de discos, unos 7 días; la ficha de un disco, 30 días.
"""
import json
import logging
import os
import threading
import time
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from ..text import clave

log = logging.getLogger("playlist_lab.deezer")

API = "https://api.deezer.com"
HEADERS = {"User-Agent": "playlist-lab/0.3 (uso personal)", "Accept": "application/json"}
ARCHIVO = Path(__file__).resolve().parents[2] / "datos" / "deezer.json"

VENTANA_S = 5.0
MAX_EN_VENTANA = 45          # Deezer admite ~50; dejamos margen
REINTENTOS = 4
ERROR_CUOTA = 4              # {"error": {"code": 4}} = te has pasado de ritmo
ERROR_SIN_DATOS = 800        # {"error": {"code": 800}} = no existe

TTL_ALBUMES = 7 * 24 * 3600
TTL_FICHA = 30 * 24 * 3600
TTL_NO_ENCONTRADO = 30 * 24 * 3600   # volver a buscar al cabo de un mes


class DeezerError(RuntimeError):
    """Deezer no ha respondido algo utilizable (red, HTML, error no previsto)."""


class _Ritmo:
    """Ventana deslizante: como mucho N peticiones en cada intervalo."""

    def __init__(self, maximo: int = MAX_EN_VENTANA, ventana: float = VENTANA_S):
        self.maximo, self.ventana = maximo, ventana
        self._marcas: deque[float] = deque()
        self._lock = threading.Lock()

    def esperar(self) -> None:
        while True:
            with self._lock:
                ahora = time.monotonic()
                while self._marcas and ahora - self._marcas[0] > self.ventana:
                    self._marcas.popleft()
                if len(self._marcas) < self.maximo:
                    self._marcas.append(ahora)
                    return
                espera = self.ventana - (ahora - self._marcas[0]) + 0.05
            time.sleep(max(espera, 0.05))


class _Almacen:
    """Caché propia en disco, con escrituras agrupadas (no una por artista)."""

    def __init__(self, archivo: Path | None = ARCHIVO):
        self.archivo = archivo
        self._lock = threading.Lock()
        self._pendientes = 0
        self.datos = {"ids": {}, "albumes": {}, "fichas": {}}
        if archivo:
            try:
                leidos = json.loads(archivo.read_text(encoding="utf-8"))
                for k in self.datos:
                    self.datos[k].update(leidos.get(k) or {})
            except (OSError, json.JSONDecodeError):
                pass

    def obtener(self, seccion: str, k: str, ttl: float | None = None,
                desde: float = 0.0):
        """Valor guardado si no ha caducado y se guardó después de `desde`."""
        with self._lock:
            e = self.datos[seccion].get(k)
        if not e:
            return False, None
        t = e.get("t", 0)
        if (ttl is not None and time.time() - t > ttl) or t < desde:
            return False, None
        return True, e.get("v")

    def guardar(self, seccion: str, k: str, valor) -> None:
        with self._lock:
            self.datos[seccion][k] = {"t": time.time(), "v": valor}
            self._pendientes += 1
            toca = self._pendientes >= 25
        if toca:
            self.volcar()

    def volcar(self) -> None:
        if not self.archivo:
            return
        with self._lock:
            if not self._pendientes:
                return
            texto = json.dumps(self.datos, ensure_ascii=False)
            self._pendientes = 0
        try:
            self.archivo.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.archivo.with_suffix(".tmp")
            tmp.write_text(texto, encoding="utf-8")
            os.replace(tmp, self.archivo)
        except OSError as e:
            log.warning("No se pudo guardar la caché de Deezer: %s", e)


def _parecido(a: str, b: str) -> float:
    return SequenceMatcher(None, clave(a), clave(b)).ratio()


class DeezerClient:
    def __init__(self, http: httpx.Client | None = None,
                 almacen: _Almacen | None = None, ritmo: _Ritmo | None = None,
                 dormir=time.sleep):
        self._http = http or httpx.Client(timeout=20, headers=HEADERS)
        self.almacen = almacen if almacen is not None else _Almacen()
        self._ritmo = ritmo or _Ritmo()
        self._dormir = dormir
        self.peticiones = 0
        self.esperas_por_cuota = 0
        self.fallos: dict[str, int] = {}

    # ---------- transporte ----------

    def _fallo(self, motivo: str) -> None:
        self.fallos[motivo] = self.fallos.get(motivo, 0) + 1

    def _get(self, path: str, **params) -> dict:
        """GET con ritmo y reintentos. {} si Deezer dice que no existe.

        Lanza DeezerError si no consigue respuesta: quien llama decide si eso
        tumba un artista (se cuenta y se avisa) o la tanda entera.
        """
        ultimo = "sin respuesta"
        for intento in range(REINTENTOS):
            self._ritmo.esperar()
            self.peticiones += 1
            try:
                resp = self._http.get(f"{API}{path}", params=params)
                datos = resp.json()
            except (httpx.HTTPError, ValueError) as e:
                ultimo = f"{type(e).__name__}"
                self._dormir(1.0 + intento)
                continue
            if resp.status_code == 429 or (resp.status_code >= 500):
                ultimo = f"HTTP {resp.status_code}"
                self._dormir(2.0 * (intento + 1))
                continue
            error = datos.get("error") if isinstance(datos, dict) else None
            if error:
                codigo = error.get("code")
                if codigo == ERROR_CUOTA:
                    self.esperas_por_cuota += 1
                    ultimo = "cuota de Deezer"
                    self._dormir(VENTANA_S * (intento + 1))
                    continue
                if codigo == ERROR_SIN_DATOS:
                    return {}
                ultimo = f"error {codigo}: {error.get('message')}"
                break
            return datos if isinstance(datos, dict) else {}
        self._fallo(ultimo)
        raise DeezerError(f"Deezer no respondió en {path} ({ultimo})")

    # ---------- artistas ----------

    def buscar_artistas(self, nombre: str, limite: int = 10) -> list[dict]:
        datos = self._get("/search/artist", q=nombre, limit=limite)
        return [{"id": a.get("id"), "name": a.get("name") or "",
                 "nb_fan": a.get("nb_fan") or 0, "nb_album": a.get("nb_album") or 0}
                for a in datos.get("data") or [] if a.get("id")]

    @staticmethod
    def elegir(nombre: str, candidatos: list[dict]) -> tuple[dict | None, str | None]:
        """El artista que de verdad buscamos entre lo que devuelve la búsqueda.

        La búsqueda de Deezer, como la de Spotify, devuelve lo más parecido
        aunque no sea él: hay que exigir que el nombre case. Con varios que
        casan (homónimos), gana el de más fans, avisando. Sin ninguno exacto,
        solo se acepta un nombre casi idéntico (erratas, "y"/"&").
        """
        buscada = clave(nombre)
        exactos = [c for c in candidatos if clave(c["name"]) == buscada]
        if exactos:
            exactos.sort(key=lambda c: c.get("nb_fan") or 0, reverse=True)
            aviso = None
            if len(exactos) > 1:
                aviso = (f"hay {len(exactos)} artistas llamados '{nombre}' en Deezer; "
                         f"se usa el de más fans ({exactos[0].get('nb_fan') or 0:,})")
            return exactos[0], aviso
        parecidos = [c for c in candidatos if _parecido(nombre, c["name"]) >= 0.9]
        if parecidos:
            parecidos.sort(key=lambda c: (_parecido(nombre, c["name"]),
                                          c.get("nb_fan") or 0), reverse=True)
            return parecidos[0], (f"en Deezer figura como '{parecidos[0]['name']}'")
        return None, None

    def artista(self, nombre: str) -> dict | None:
        """{id, name, nb_fan, aviso} del artista, o None si Deezer no lo tiene.

        El id se cachea para siempre; un "no lo tiene" se recuerda un mes.
        """
        k = clave(nombre)
        if not k:
            return None
        hay, valor = self.almacen.obtener("ids", k)
        if hay:
            if valor is None or valor.get("no_encontrado"):
                hay2, _ = self.almacen.obtener("ids", k, ttl=TTL_NO_ENCONTRADO)
                if hay2:
                    return None
            else:
                return valor
        candidatos = self.buscar_artistas(nombre)
        elegido, aviso = self.elegir(nombre, candidatos)
        if not elegido:
            self.almacen.guardar("ids", k, {"no_encontrado": True})
            return None
        # Con homónimos se guardan los demás: el de más fans no siempre es el
        # tuyo, y quien rastrea puede mirar también sus discos.
        otros = [{"id": c["id"], "name": c["name"], "nb_fan": c.get("nb_fan") or 0}
                 for c in candidatos if clave(c["name"]) == k
                 and c["id"] != elegido["id"]][:2] if aviso and "llamados" in aviso else []
        valor = {"id": elegido["id"], "name": elegido["name"],
                 "nb_fan": elegido.get("nb_fan") or 0, "aviso": aviso, "otros": otros}
        self.almacen.guardar("ids", k, valor)
        return valor

    def albumes(self, artista_id: int, desde: float = 0.0,
                max_paginas: int = 2) -> list[dict]:
        """Lanzamientos del artista: [{id, title, release_date, record_type}].

        `desde` (unix) obliga a refrescar lo que se guardó antes: una lista de
        discos guardada el día 28 no puede saber qué salió el 30.
        """
        k = str(artista_id)
        hay, valor = self.almacen.obtener("albumes", k, ttl=TTL_ALBUMES, desde=desde)
        if hay:
            return valor
        out: list[dict] = []
        indice = 0
        for _ in range(max_paginas):
            datos = self._get(f"/artist/{artista_id}/albums", limit=50, index=indice)
            filas = datos.get("data") or []
            out.extend({"id": a.get("id"), "title": a.get("title") or "",
                        "release_date": a.get("release_date") or "",
                        "record_type": (a.get("record_type") or "").lower(),
                        "fans": a.get("fans")}
                       for a in filas if a.get("id"))
            if not datos.get("next") or len(filas) < 50:
                break
            indice += 50
        self.almacen.guardar("albumes", k, out)
        return out

    def ficha(self, album_id: int) -> dict:
        """Detalle de un disco: canciones, duración, sello, géneros y artista."""
        k = str(album_id)
        hay, valor = self.almacen.obtener("fichas", k, ttl=TTL_FICHA)
        if hay:
            return valor
        a = self._get(f"/album/{album_id}")
        valor = {
            "id": a.get("id"), "title": a.get("title") or "",
            "nb_tracks": a.get("nb_tracks"), "duration": a.get("duration"),
            "label": a.get("label"), "release_date": a.get("release_date"),
            "record_type": (a.get("record_type") or "").lower(),
            "genres": [g.get("name") for g in ((a.get("genres") or {}).get("data") or [])
                       if g.get("name")],
            "fans": a.get("fans"),
            "artist": (a.get("artist") or {}).get("name"),
            "link": a.get("link"),
        }
        if a:
            self.almacen.guardar("fichas", k, valor)
        return valor

    def volcar(self) -> None:
        self.almacen.volcar()
