"""Radar de novedades y emergentes: se alimenta solo y acumula semana a semana.

Por qué: la IA solo buscaba novedades si se le ocurría en mitad de una
conversación, y entonces tiraba de su memoria, que tiene fecha de corte. El
radar invierte el flujo: recoge candidatos de fuentes independientes, quita
lo que el usuario ya conoce y los puntúa. Cuando se pide un menú, la novedad
sale de aquí, ya validada.

La idea central es la TRIANGULACIÓN: un grupo al que apuesta KEXP, que reseña
la prensa y que publica un sello que sigues es mucho mejor apuesta que
cualquier cosa que aparezca en una sola fuente. Y la RECURRENCIA: si sigue
saliendo semana tras semana, no era una casualidad.

Solo fuentes gratuitas; ni una petición a Spotify.
"""
import datetime as dt
import json
import logging
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import seguimiento
from .clients import press
from .clients.kexp import KexpClient
from .clients.lastfm import LastfmClient
from .clients.listenbrainz import ListenbrainzClient
from .clients.musicbrainz import MusicbrainzClient
from .clients.statsfm import StatsfmClient
from .text import norm

log = logging.getLogger("playlist_lab.radar")
ARCHIVO = Path(__file__).resolve().parents[1] / "datos" / "radar.json"
_lock = threading.Lock()

# Cuánto vale cada tipo de señal por sí sola
PESO = {
    "kexp": 3.0,              # una radio con criterio apuesta por él (x rotación)
    "sesion_kexp": 2.0,       # ha tocado en directo en KEXP
    "sello_seguido": 3.0,     # publica en un sello que él sigue
    "prensa": 2.0,            # reseñado o mencionado en la prensa archivada
    "listenbrainz": 1.0,      # lanzamiento reciente con algo de público
    "etiqueta": 1.0,          # sale en el fondo de una etiqueta de su gusto
}
BONUS_POR_FUENTE_EXTRA = 3.0  # triangulación: cada fuente independiente de más
# Para triangular cuentan ORÍGENES independientes: la rotación y la sesión de
# KEXP son la misma emisora opinando dos veces, no dos opiniones.
ORIGEN = {"sesion_kexp": "kexp"}
BONUS_RECURRENCIA = 1.5       # visto en varias pasadas del radar
BONUS_AFINIDAD = 1.5          # sus etiquetas casan con los géneros del usuario
MASIVO = 1_000_000            # por encima no es un descubrimiento
DIAS_NOVEDAD = 120


def _hoy() -> str:
    return dt.date.today().isoformat()


def cargar() -> dict:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"actualizado": None, "candidatos": [], "de_los_que_sigues": []}


def _guardar(datos: dict) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, ARCHIVO)


def _generos_del_usuario(sf: StatsfmClient | None, n: int = 8) -> list[str]:
    if not sf:
        return []
    cuenta: Counter = Counter()
    for peso, rango in ((1.0, "weeks"), (1.0, "months"), (0.5, "lifetime")):
        for i, a in enumerate(sf.top_artists(rango, 40)):
            for g in a.get("genres", []):
                cuenta[g.lower()] += peso * (40 - i) / 40
    return [g for g, _ in cuenta.most_common(n)]


class _Candidatos:
    """Acumula señales por artista a medida que se recorren las fuentes."""

    def __init__(self):
        self.d: dict[str, dict] = {}

    def add(self, artista: str, fuente: str, puntos: float, senal: str,
            ejemplo: dict | None = None):
        if not artista:
            return
        c = self.d.setdefault(norm(artista), {
            "artist": artista, "fuentes": set(), "puntos": 0.0,
            "senales": [], "ejemplo": None})
        c["fuentes"].add(fuente)
        c["puntos"] += puntos
        if senal and senal not in c["senales"]:
            c["senales"].append(senal)
        if ejemplo and not c["ejemplo"]:
            c["ejemplo"] = ejemplo


def recorrer(lf: LastfmClient, mb: MusicbrainzClient, lb: ListenbrainzClient,
             kexp: KexpClient, sf: StatsfmClient | None, conocidos: dict,
             paso=lambda _t: None) -> dict:
    """Una pasada completa del radar. Tarda uno o dos minutos."""
    seg = seguimiento.cargar()
    sellos_seguidos = {s.lower() for s in seg["sellos"]}
    desde = (dt.date.today() - dt.timedelta(days=DIAS_NOVEDAD)).isoformat()
    cand = _Candidatos()
    fallos: list[str] = []

    # 1) KEXP: la apuesta de una radio con criterio
    paso("KEXP: qué está apostando esta semana")
    try:
        for r in kexp.artistas_mas_pinchados(7, 500):
            ej = r.get("ejemplo") or {}
            apuesta = r.get("apuesta_de_la_emisora") or 0
            if apuesta > 0:
                cand.add(r["artist"], "kexp", PESO["kexp"] * min(apuesta, 6) / 3,
                         f"KEXP lo tiene en rotación {r.get('rotacion') or '?'} "
                         f"({r['veces_emitido']} emisiones esta semana)",
                         {"album": ej.get("album"), "sello": ej.get("sello"),
                          "año": ej.get("año")})
            if r.get("sesion_en_directo"):
                cand.add(r["artist"], "sesion_kexp", PESO["sesion_kexp"],
                         "ha hecho SESIÓN EN DIRECTO en KEXP")
            if (ej.get("sello") or "").lower() in sellos_seguidos:
                cand.add(r["artist"], "sello_seguido", PESO["sello_seguido"],
                         f"publica en {ej['sello']}, un sello que sigues")
    except Exception as e:  # noqa: BLE001
        fallos.append(f"KEXP: {e}")

    # 2) Sellos que sigue: lo que han sacado en los últimos meses
    for sello in seg["sellos"]:
        paso(f"sellos: mirando {sello}")
        try:
            cat = mb.catalogo_sello(sello, desde=desde, limit=15)
            for pub in cat.get("publicaciones", []) if isinstance(cat, dict) else []:
                cand.add(pub["artist"], "sello_seguido", PESO["sello_seguido"],
                         f"nuevo en {sello}: «{pub['album']}» ({pub['fecha']})",
                         {"album": pub["album"], "sello": sello, "año": pub["fecha"][:4]})
        except Exception as e:  # noqa: BLE001
            fallos.append(f"sello {sello}: {e}")

    # 3) ListenBrainz: lanzamientos recientes con algo de público
    paso("ListenBrainz: novedades con público")
    try:
        for r in lb.novedades(21, 120, min_escuchas=10):
            cand.add(r["artist"], "listenbrainz", PESO["listenbrainz"],
                     f"acaba de sacar «{r['album']}» ({r['fecha']})",
                     {"album": r["album"], "año": (r.get("fecha") or "")[:4]})
    except Exception as e:  # noqa: BLE001
        fallos.append(f"ListenBrainz: {e}")

    # 4) El fondo de las etiquetas de su gusto (donde no llegan los grandes),
    # más las que sigue a propósito (castellano incluido)
    generos = _generos_del_usuario(sf)
    extra = [e for e in seg.get("etiquetas", []) if e.lower() not in generos]
    a_recorrer = generos[:5] + extra
    paso(f"etiquetas: {', '.join(a_recorrer)}")
    for g in a_recorrer:
        try:
            for a in lf.tag_top_artists(g, 50, 5):
                cand.add(a["name"], "etiqueta", PESO["etiqueta"],
                         f"sale en el fondo de la etiqueta «{g}»")
        except Exception as e:  # noqa: BLE001
            fallos.append(f"etiqueta {g}: {e}")

    # Fuera lo que ya conoce (y lo que vetó)
    vivos = {k: c for k, c in cand.d.items() if k not in conocidos}

    # Una sola fuente débil (ListenBrainz global, etiqueta) no basta para entrar
    fuertes = {"kexp", "sesion_kexp", "sello_seguido"}
    preseleccion = sorted(
        (c for c in vivos.values() if c["fuentes"] & fuertes or len(c["fuentes"]) >= 2),
        key=lambda c: c["puntos"], reverse=True)[:60]

    # 5) Enriquecer: audiencia, afinidad de etiquetas y prensa
    paso(f"comprobando {len(preseleccion)} candidatos (audiencia y prensa)")

    def enriquecer(c: dict) -> dict:
        try:
            info = lf.artist_info(c["artist"]) or {}
        except Exception:  # noqa: BLE001
            info = {}
        c["oyentes"] = info.get("listeners") or 0
        c["escuchas_por_oyente"] = info.get("escuchas_por_oyente") or 0
        c["etiquetas"] = (info.get("tags") or [])[:5]
        menciones = press.buscar_en_archivo(c["artist"], 5)
        if menciones:
            c["fuentes"].add("prensa")
            c["puntos"] += PESO["prensa"]
            c["senales"].append(
                f"en la prensa: {menciones[0].get('source')} "
                f"(«{(menciones[0].get('title') or '')[:60]}»)")
        comunes = {t.lower() for t in c["etiquetas"]} & (set(generos) | {e.lower() for e in extra})
        if comunes:
            c["puntos"] += BONUS_AFINIDAD
            c["senales"].append(f"encaja con tus géneros ({', '.join(sorted(comunes))})")
        return c

    with ThreadPoolExecutor(max_workers=6) as pool:
        enriquecidos = list(pool.map(enriquecer, preseleccion))

    resultado = []
    for c in enriquecidos:
        if c["oyentes"] > MASIVO:
            continue
        origenes = {ORIGEN.get(f, f) for f in c["fuentes"]}
        c["puntos"] += max(0, len(origenes) - 1) * BONUS_POR_FUENTE_EXTRA
        c["fuentes"] = sorted(c["fuentes"])
        c["origenes_independientes"] = len(origenes)
        c["triangulado"] = len(origenes) >= 2
        c["puntos"] = round(c["puntos"], 1)
        resultado.append(c)

    # Novedades de los artistas que sigue (esos sí los conoce: van aparte)
    de_los_tuyos = []
    for artista in seg["artistas"]:
        paso(f"artistas que sigues: {artista}")
        try:
            for r in mb.recent_by_artist(artista, desde):
                de_los_tuyos.append({"artist": artista, "album": r["album"],
                                     "fecha": r["fecha"], "tipo": r.get("tipo")})
        except Exception as e:  # noqa: BLE001
            fallos.append(f"artista {artista}: {e}")

    return {"candidatos": resultado, "de_los_que_sigues": de_los_tuyos,
            "generos_usados": generos, "fallos": fallos}


def actualizar(lf, mb, lb, kexp, sf, conocidos, paso=lambda _t: None) -> dict:
    """Pasa el radar y lo funde con lo anterior, llevando la cuenta de la
    recurrencia: quien sigue apareciendo semana tras semana suma."""
    nuevo = recorrer(lf, mb, lb, kexp, sf, conocidos, paso)
    with _lock:
        previo = cargar()
        historia = {norm(c["artist"]): c for c in previo.get("candidatos", [])}
        hoy = _hoy()
        fusion = []
        for c in nuevo["candidatos"]:
            antes = historia.pop(norm(c["artist"]), None)
            c["primera_vez"] = (antes or {}).get("primera_vez", hoy)
            c["veces_visto"] = (antes or {}).get("veces_visto", 0) + 1
            c["ultima_vez"] = hoy
            if c["veces_visto"] >= 2:
                c["puntos"] = round(c["puntos"] + BONUS_RECURRENCIA, 1)
                c["senales"].append(f"sigue apareciendo ({c['veces_visto']} pasadas)")
            fusion.append(c)
        # lo que no ha salido hoy se conserva unas semanas, sin sumar
        limite = (dt.date.today() - dt.timedelta(days=42)).isoformat()
        for c in historia.values():
            if (c.get("ultima_vez") or "") >= limite:
                fusion.append(c)
        fusion.sort(key=lambda c: c["puntos"], reverse=True)
        datos = {"actualizado": hoy, "candidatos": fusion[:150],
                 "de_los_que_sigues": nuevo["de_los_que_sigues"],
                 "generos_usados": nuevo["generos_usados"],
                 "fallos_ultima_pasada": nuevo["fallos"]}
        _guardar(datos)
    return datos


def leer(conocidos: dict, solo_triangulados: bool = False, limite: int = 25) -> dict:
    """Lo que hay en el radar ahora, quitando lo que haya conocido después."""
    datos = cargar()
    lista = [c for c in datos.get("candidatos", [])
             if norm(c["artist"]) not in conocidos
             and (c.get("triangulado") or not solo_triangulados)]
    return {"actualizado": datos.get("actualizado"),
            "candidatos": lista[:limite],
            "total_en_radar": len(lista),
            "de_los_que_sigues": datos.get("de_los_que_sigues", []),
            "fallos_ultima_pasada": datos.get("fallos_ultima_pasada") or None}
