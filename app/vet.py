"""Validar candidatos: el aval externo de una propuesta, en una sola llamada.

Por qué existe: en la primera semana real, la IA eligió 25 discos solo con su
propio conocimiento y no usó ninguna fuente externa. Para los clásicos no
importa —Wire no necesita aval—, pero para lo nuevo y lo emergente sí: su
conocimiento tiene fecha de corte y no sabe qué está sonando ahora, ni si un
grupo sigue en activo, ni si tiene sesión en KEXP. No las usó porque cada
comprobación eran varias llamadas por artista. Aquí es una por lista.

Solo fuentes gratuitas: nada de cuota de Spotify.
"""
import datetime as dt
import logging
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import historial
from .clients import press
from .clients.kexp import KexpClient
from .clients.lastfm import LastfmClient
from .text import norm

log = logging.getLogger("playlist_lab.vet")

# Niveles de conocimiento. "Rozado" NO descarta: para él cualquier disco es
# susceptible de segunda escucha, así que un grupo oído de pasada puede
# volver, diciendo que ya lo rozó.
UMBRAL_ROZADO = 15      # escuchas (Last.fm o stats.fm)
UMBRAL_MUCHO = 100

# Trayectoria: "novedad" no es lo mismo que "emergente". Un disco nuevo de
# un grupo con veinte años (Ceremony, en activo desde 2005) es una novedad,
# no un descubrimiento; lo detectó el propio chat, no la herramienta.
EMERGENTE_MAX_ANOS = 5
VETERANO_MIN_ANOS = 12

PEQUENO = 150_000
GRANDE = 1_000_000
DEVOTO = 8.0


def nivel_de_conocimiento(evidencia: dict | None, lastfm_plays: int = 0) -> str:
    """nuevo | rozado | conocido | muy escuchado, a partir de toda la evidencia."""
    ev = evidencia or {}
    escuchas = max(ev.get("statsfm_streams") or 0, ev.get("lastfm_plays") or 0,
                   lastfm_plays or 0)
    guardado = bool(ev.get("canciones_guardadas") or ev.get("album_guardado")
                    or ev.get("lo_sigues"))
    if escuchas > UMBRAL_MUCHO or (ev.get("spotify_rank") or 999) <= 20:
        return "muy escuchado"
    if escuchas > UMBRAL_ROZADO or guardado:
        return "conocido"
    if escuchas > 0:
        return "rozado"
    return "nuevo"


def etapa(activo_desde: str | None) -> str | None:
    """emergente | consolidado | veterano, según los años en activo."""
    if not activo_desde or not activo_desde[:4].isdigit():
        return None
    anos = dt.date.today().year - int(activo_desde[:4])
    if anos <= EMERGENTE_MAX_ANOS:
        return "emergente"
    if anos >= VETERANO_MIN_ANOS:
        return "veterano"
    return "consolidado"


def _uno(nombre: str, lf: LastfmClient, kexp: KexpClient,
         conocidos: dict, opiniones: dict) -> dict:
    ev = conocidos.get(norm(nombre))
    try:
        info = lf.artist_info(nombre) or {}
    except Exception as e:  # noqa: BLE001
        log.warning("Last.fm falló con %s: %s", nombre, e)
        info = {}
    plays_propios = 0
    if not ev and lf.username:
        try:
            plays_propios = lf.user_artist_playcount(nombre)
        except Exception:  # noqa: BLE001
            plays_propios = 0
    try:
        emisiones = kexp.emisiones_de(nombre)
    except Exception as e:  # noqa: BLE001
        log.warning("KEXP falló con %s: %s", nombre, e)
        emisiones = []
    prensa = press.buscar_en_archivo(nombre, 5)

    nivel = nivel_de_conocimiento(ev, plays_propios)
    oyentes = info.get("listeners") or 0
    ratio = info.get("escuchas_por_oyente") or 0
    sesion = any(e.get("sesion_en_directo") for e in emisiones)
    ultima = max((e.get("fecha_emision") or "" for e in emisiones), default="")

    senales = []
    if oyentes:
        if oyentes < PEQUENO:
            senales.append(f"pequeño ({oyentes:,} oyentes)")
        elif oyentes > GRANDE:
            senales.append(f"masivo ({oyentes:,} oyentes)")
        else:
            senales.append(f"mediano ({oyentes:,} oyentes)")
        if ratio >= DEVOTO and oyentes < GRANDE:
            senales.append(f"público devoto ({ratio}/oyente)")
    else:
        senales.append("sin datos de audiencia")
    if emisiones:
        senales.append(f"KEXP lo ha pinchado {len(emisiones)} veces (última {ultima})")
    if sesion:
        senales.append("tiene SESIÓN EN DIRECTO en KEXP")
    if prensa:
        senales.append(f"{len(prensa)} menciones en la prensa archivada")

    corregido = info.get("artist")
    if corregido and norm(corregido) != norm(nombre):
        senales.append(f"OJO: Last.fm lo interpreta como '{corregido}'; comprueba "
                       "que es el mismo artista")

    opinion = opiniones.get(nombre) or opiniones.get(norm(nombre))
    return {
        "artist": info.get("artist") or nombre,
        "nivel": nivel,
        "tu_opinion": ({k: v for k, v in opinion.items() if k != "artista"}
                       if opinion else None),
        "senales": senales,
        "oyentes": oyentes,
        "escuchas_por_oyente": ratio,
        "etiquetas": (info.get("tags") or [])[:5],
        "kexp": {"emisiones": len(emisiones), "sesion_en_directo": sesion,
                 "ultima": ultima or None},
        "prensa": [{"medio": p.get("source"), "titular": p.get("title"),
                    "fecha": p.get("date")} for p in prensa[:3]],
    }


def validar(nombres: list[str], lf: LastfmClient, kexp: KexpClient,
            conocidos: dict, opiniones: dict, mb=None) -> dict:
    nombres = [n for n in dict.fromkeys(nombres) if n][:20]
    with ThreadPoolExecutor(max_workers=6) as pool:
        filas = list(pool.map(
            lambda n: _uno(n, lf, kexp, conocidos, opiniones), nombres))

    # Trayectoria en MusicBrainz: va en serie (una petición por segundo)
    if mb is not None:
        for f, nombre in zip(filas, nombres):
            try:
                ficha = mb.find_artist(nombre) or {}
            except Exception:  # noqa: BLE001
                ficha = {}
            f["activo_desde"] = ficha.get("activo_desde")
            f["pais"] = ficha.get("country")
            f["etapa"] = etapa(ficha.get("activo_desde"))
            if f["etapa"] == "veterano":
                f["senales"].append(f"VETERANO: en activo desde {f['activo_desde'][:4]}; "
                                    "un disco suyo es novedad, no descubrimiento")
            elif f["etapa"] == "emergente":
                f["senales"].append(f"emergente de verdad (desde {f['activo_desde'][:4]})")

    for f, nombre in zip(filas, nombres):
        f["ya_propuesto_en"] = historial.listas_de(nombre) or None
        if f["ya_propuesto_en"]:
            f["senales"].append("YA TE LO PROPUSE en: " + ", ".join(f["ya_propuesto_en"][:3]))

    descartar = [f["artist"] for f in filas
                 if f["nivel"] in ("conocido", "muy escuchado")
                 or (f["tu_opinion"] or {}).get("veredicto") in ("nunca más", "no es lo mío")]
    con_aval = [f["artist"] for f in filas
                if f["kexp"]["emisiones"] or f["prensa"]]
    return {
        "candidatos": filas,
        "resumen": {
            "ya_conocidos_o_descartados": descartar,
            "rozados_se_pueden_proponer": [f["artist"] for f in filas
                                           if f["nivel"] == "rozado"],
            "con_aval_externo": con_aval,
            "con_sesion_kexp": [f["artist"] for f in filas if f["kexp"]["sesion_en_directo"]],
            "veteranos_no_emergentes": [f["artist"] for f in filas
                                        if f.get("etapa") == "veterano"],
            "ya_propuestos_antes": [f["artist"] for f in filas if f.get("ya_propuesto_en")],
        },
        "diversidad": diversidad(filas),
        "como_leerlo": (
            "nivel: nuevo < rozado < conocido < muy escuchado. 'Rozado' NO "
            "descarta: puedes proponerlo diciendo que ya lo oyó de pasada. "
            "Para novedades y emergentes, prioriza los que tienen aval externo "
            "(KEXP o prensa): tu conocimiento tiene fecha de corte. Si alguno "
            "tiene sesión en KEXP, díselo: el directo le importa. "
            "'ya_propuestos_antes' no descarta, pero repetir nombres es la señal "
            "de que estás tirando de lo obvio: busca un nivel más hondo. Mira "
            "'diversidad': si avisa de concentración, es que tu lista se ha "
            "ido hacia un mismo sitio sin que él lo pidiera."),
    }


CONCENTRACION = 0.6   # si más del 60 % comparte país, década o etiqueta


def diversidad(filas: list[dict]) -> dict:
    """Cuánto se parecen entre sí los candidatos: el control objetivo contra
    el sesgo del modelo hacia lo más documentado (siempre los mismos países,
    la misma década, la misma etiqueta)."""
    n = len(filas)
    paises = Counter(f.get("pais") for f in filas if f.get("pais"))
    decadas = Counter(f"{f['activo_desde'][:3]}0s" for f in filas
                      if (f.get("activo_desde") or "")[:4].isdigit())
    etiquetas = Counter(t.lower() for f in filas for t in (f.get("etiquetas") or [])[:3])
    oyentes = [f.get("oyentes") or 0 for f in filas if f.get("oyentes")]
    avisos = []
    if n >= 5:
        for nombre, cont in (("país", paises), ("década de inicio", decadas),
                             ("etiqueta", etiquetas)):
            if cont:
                valor, veces = cont.most_common(1)[0]
                if veces / n >= CONCENTRACION:
                    avisos.append(f"{veces} de {n} comparten {nombre}: {valor}")
        masivos = sum(1 for o in oyentes if o > GRANDE)
        if masivos / n >= 0.4:
            avisos.append(f"{masivos} de {n} son masivos (más de un millón de oyentes)")
    return {"paises": dict(paises.most_common()), "decadas": dict(sorted(decadas.items())),
            "etiquetas_frecuentes": dict(etiquetas.most_common(5)),
            "avisos": avisos or None}
