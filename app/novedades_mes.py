"""Novedades del mes: qué discos han salido en un mes y cuáles te importan.

Por qué existe: la tarea programada del día 1 montaba la lista de novedades
preguntando a Spotify artista por artista (artist_releases), y el 3 de
noviembre de 2026 unas 45 llamadas seguidas bastaron para que Spotify
bloqueara la app 24 horas. new_releases no gasta cuota, pero mira solo unos
24 artistas y tira de MusicBrainz, que cubre muy mal el indie español: para
septiembre y octubre solo encontró a Fontaines D.C.

Aquí el rastreo es amplio y SIN SPOTIFY:

1. Artistas candidatos: todo el historial de stats.fm con un mínimo de
   escuchas (no solo los tops), sus artistas de Last.fm, lo que sigue y
   guarda (solo si ya está en la caché: pedirlo gasta cuota) y los vecinos
   de sus ~50 artistas principales de los últimos seis meses ("órbita").
2. Lanzamientos: la API pública de Deezer (gratis, sin clave, buen catálogo
   español) y MusicBrainz de respaldo para quien Deezer no tenga.
3. Filtro: solo discos (álbumes y EPs de 4 o más canciones) con fecha dentro
   del mes natural; fuera singles, directos, remezclas, reediciones,
   ediciones deluxe o japonesas, recopilatorios y bandas sonoras. Lo que se
   cae se devuelve con su motivo, para poder revisar el filtro.
4. Fuentes externas del mes: radar, prensa archivada, KEXP y los
   calendarios de lanzamientos (Dod, Binaural, Bandcamp Daily). Lo que solo
   sale de ahí pasa por vet_candidates y por sus géneros.
5. Puntuación: sus escuchas (pesa más lo reciente), afinidad de géneros,
   avales externos y tipo de disco. Cada disco trae una frase con el porqué.

Spotify solo se usa después, UNA vez, cuando la tarea crea la lista.
"""
import calendar
import datetime as dt
import logging
import math
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from . import cache
from . import radar as radar_mod
from .clients import press
from .clients.deezer import DeezerClient, DeezerError
from .text import clave, norm, titulo_base

log = logging.getLogger("playlist_lab.novedades_mes")

MIN_ESCUCHAS = 10            # escuchas de toda la vida para entrar en el rastreo
MIN_ESCUCHAS_RECIENTES = 3   # o estas en los últimos seis meses
N_PRINCIPALES = 50           # artistas de los que se buscan vecinos
VECINOS_POR_ARTISTA = 12
MATCH_MINIMO = 0.35          # parecido en Last.fm (0-1) para contar como vecino
MIN_CANCIONES_EP = 4
MAX_PETICIONES_MB = 120      # MusicBrainz va a 1 por segundo: tope por ejecución
FANS_SOSPECHOSOS = 50        # un artista que escuchas mucho con tan pocos fans…
ESCUCHAS_PARA_SOSPECHAR = 50
TTL_CANDIDATOS = 24 * 3600
TTL_VECINOS = 7 * 24 * 3600

# ---------- qué es un disco y qué no ----------

# Por el título. El orden importa: el primer motivo que casa es el que se da.
_FUERA = [
    ("directo", re.compile(r"[\(\[\-–—:]\s*(live|en directo|en vivo|directo)\b"
                           r"|\blive (at|from|in|on|session)s?\b|\ben directo\b"
                           r"|\bunplugged\b|\blive$", re.I)),
    ("remezclas", re.compile(r"\bremix(es|ed)?\b|\brmx\b|\brework(s|ed)?\b"
                             r"|\bremezclas?\b|\bdub versions?\b", re.I)),
    ("edición deluxe o especial", re.compile(
        r"\bdeluxe\b|\bexpanded\b|\bedition\b|\bedición\b|\bedicion\b"
        r"|\bjapan(ese)?\b|\bbonus tracks?\b|\bextended\b|\bcomplete\b", re.I)),
    ("aniversario", re.compile(r"\banniversary\b|\baniversario\b", re.I)),
    ("reedición o remasterización", re.compile(
        r"\bremaster(ed)?\b|\bremasterizado\b|\breissue\b|\breedici[oó]n\b", re.I)),
    ("banda sonora", re.compile(r"\bost\b|\bsoundtrack\b|\bbanda sonora\b"
                                r"|\bmusic from (the )?(motion picture|film|series)\b", re.I)),
    ("sesiones", re.compile(r"\bsessions?\b", re.I)),
    ("recopilatorio", re.compile(r"\bgreatest hits\b|\bbest of\b|\banthology\b"
                                 r"|\brarities\b|\bb-sides\b|\bgrandes [eé]xitos\b", re.I)),
]


def motivo_por_titulo(titulo: str) -> str | None:
    for motivo, patron in _FUERA:
        if patron.search(titulo or ""):
            return motivo
    return None


def filtro_previo(lanz: dict, anteriores: list[dict]) -> str | None:
    """Motivo para descartar sin pedir la ficha del disco (o None si sigue).

    `anteriores`: lanzamientos del mismo artista ANTES del mes (sin singles:
    el single que adelanta un disco suele llamarse igual que el disco).
    """
    tipo = (lanz.get("record_type") or "").lower()
    if tipo == "single":
        return "single"
    if tipo == "compile":
        return "recopilatorio"
    motivo = motivo_por_titulo(lanz.get("title") or "")
    if motivo:
        return motivo
    base = titulo_base(lanz.get("title") or "")
    for a in anteriores:
        if base and titulo_base(a.get("title") or "") == base:
            return f"reedición de un disco de {(a.get('release_date') or '')[:4]}"
    return None


def filtro_ficha(ficha: dict, anteriores_fichas: list[dict] = ()) -> str | None:
    """Lo que solo se ve con la ficha: canciones de un EP y ediciones infladas."""
    tipo = (ficha.get("record_type") or "").lower()
    canciones = ficha.get("nb_tracks") or 0
    if tipo == "single":
        return "single"
    if tipo == "compile":
        return "recopilatorio"
    if tipo == "ep" and canciones and canciones < MIN_CANCIONES_EP:
        return f"EP de {canciones} canciones"
    base = titulo_base(ficha.get("title") or "")
    for a in anteriores_fichas:
        if base and titulo_base(a.get("title") or "") == base:
            if (a.get("nb_tracks") or 0) < canciones:
                return "edición ampliada de un disco anterior"
            return "reedición de un disco anterior"
    return None


# ---------- géneros ----------

# Deezer etiqueta en grueso ("Pop", "Alternative", "Rap/Hip Hop") y Spotify
# o Last.fm en fino ("spanish indie pop", "post-punk"). Para saber si un disco
# encaja con el artista que escuchas se comparan FAMILIAS, no etiquetas.
FAMILIAS = {
    "rock": ("rock", "punk", "indie", "alternativ", "grunge", "garage", "shoegaze",
             "emo", "post-", "noise", "psych", "stoner", "britpop", "new wave",
             "math", "slowcore", "surf", "rock and roll"),
    "metal": ("metal", "hardcore", "doom", "sludge", "thrash", "grind", "core"),
    "pop": ("pop", "indie", "cantautor", "singer-songwriter", "synth", "chanson",
            "variété", "variete", "bedroom"),
    "electronica": ("electr", "techno", "house", "dance", "ambient", "idm", "synth",
                    "edm", "trance", "drum and bass", "dubstep", "club", "breakbeat"),
    "hiphop": ("hip hop", "hip-hop", "rap", "trap", "drill", "grime"),
    "latino": ("reggaeton", "latin", "dembow", "urbano", "salsa", "bachata",
               "cumbia", "bolero", "ranchera", "corrido"),
    "negra": ("jazz", "blues", "soul", "funk", "r&b", "rnb", "gospel", "reggae"),
    "folk": ("folk", "country", "americana", "flamenco", "cantautor",
             "singer-songwriter", "bluegrass"),
    "clasica": ("classical", "clásica", "clasica", "opera", "orchestral", "baroque"),
    "bso": ("soundtrack", "films", "film", "games", "bandas sonoras", "score"),
    "infantil": ("kids", "infantil", "children"),
}


def familias(etiquetas) -> set[str]:
    out = set()
    for e in etiquetas or []:
        e = (e or "").lower()
        for familia, claves in FAMILIAS.items():
            if any(k in e for k in claves):
                out.add(familia)
    return out


_GENERICOS = {"music", "musica", "música", "band", "spanish", "espanol", "español",
              "uk", "british", "american", "irish", "new", "the", "and", "of"}


def _tokens(g: str) -> set[str]:
    return {t for t in re.split(r"[\s\-/&]+", (g or "").lower())
            if len(t) > 2 and t not in _GENERICOS}


def afinidad(generos_artista, mis_generos: dict[str, float]) -> tuple[float, list[str]]:
    """0-1: cuánto se parecen los géneros de un artista a los tuyos.

    Una etiqueta idéntica cuenta entera; compartir una palabra con sentido
    ("post-punk" y "post-punk revival", "indie" y "spanish indie") cuenta a
    medias. Devuelve también qué géneros tuyos casaron, para el porqué.
    """
    mejor, casados = 0.0, []
    for g in generos_artista or []:
        g = (g or "").lower()
        if g in mis_generos:
            if mis_generos[g] > mejor:
                mejor = mis_generos[g]
            casados.append(g)
            continue
        tg = _tokens(g)
        for mio, peso in mis_generos.items():
            if tg & _tokens(mio):
                if 0.5 * peso > mejor:
                    mejor = 0.5 * peso
                if mio not in casados and len(casados) < 3:
                    casados.append(mio)
    return round(min(mejor, 1.0), 2), casados[:3]


def mis_generos(artistas: dict, n: int = 30) -> dict[str, float]:
    """Tus géneros, ponderados por lo que escuchas ahora (normalizado a 0-1)."""
    cuenta: Counter = Counter()
    for c in artistas.values():
        if c["relacion"] != "de_los_tuyos":
            continue
        e = c["escuchas"]
        peso = math.log10(1 + 3 * e["ultimos_6_meses"] + e["total"])
        for g in c.get("generos") or []:
            cuenta[g.lower()] += peso
    hay, perfil = cache.obtener("profile", 30 * 24 * 3600)
    for i, g in enumerate((perfil or {}).get("generos_principales") or [] if hay else []):
        cuenta[g.lower()] += max(0.0, 25 - i) / 5
    if not cuenta:
        return {}
    tope = cuenta.most_common(1)[0][1]
    return {g: round(v / tope, 3) for g, v in cuenta.most_common(n)}


# ---------- 1. artistas candidatos ----------

def rango_mes(mes: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes or ""):
        raise ValueError(f"El mes va como 'AAAA-MM' (p. ej. '2026-10'), no {mes!r}")
    anio, m = int(mes[:4]), int(mes[5:7])
    return f"{mes}-01", f"{mes}-{calendar.monthrange(anio, m)[1]:02d}"


def _nuevo(nombre: str, relacion: str) -> dict:
    return {"nombre": nombre, "relacion": relacion, "generos": [],
            "escuchas": {"total": 0, "ultimos_6_meses": 0, "lastfm": 0},
            "biblioteca": [], "vecino_de": [], "fuentes_externas": {}}


def reunir_artistas(sf, lf, biblioteca: dict | None, vetados: dict,
                    min_escuchas: int = MIN_ESCUCHAS, paso=lambda _t: None,
                    avisos: list | None = None) -> dict[str, dict]:
    """Todos los artistas que merece la pena rastrear, por clave normalizada."""
    avisos = avisos if avisos is not None else []
    pool: dict[str, dict] = {}

    def de_los_tuyos(nombre: str) -> dict:
        k = clave(nombre)
        c = pool.get(k)
        if c is None:
            c = pool[k] = _nuevo(nombre, "de_los_tuyos")
        c["relacion"] = "de_los_tuyos"
        return c

    if sf:
        paso("stats.fm: todo tu historial (toda la vida y últimos seis meses)")
        vida = sf.top_artists_todos("lifetime", min_streams=1)
        meses = sf.top_artists_todos("months", min_streams=1)
        if not vida:
            avisos.append("stats.fm no devolvió tu historial: el rastreo se apoya "
                          "solo en Last.fm y tu biblioteca (faltarán artistas)")
        recientes = {clave(a["name"]): a["streams"] for a in meses}
        for a in vida:
            k = clave(a["name"])
            if a["streams"] >= min_escuchas or recientes.get(k, 0) >= MIN_ESCUCHAS_RECIENTES:
                c = de_los_tuyos(a["name"])
                c["escuchas"]["total"] = a["streams"]
                c["generos"] = (a.get("genres") or [])[:5]
        for a in meses:
            k = clave(a["name"])
            if a["streams"] >= MIN_ESCUCHAS_RECIENTES or k in pool:
                c = de_los_tuyos(a["name"])
                c["escuchas"]["ultimos_6_meses"] = a["streams"]
                c["escuchas"]["total"] = max(c["escuchas"]["total"], a["streams"])
                c["generos"] = c["generos"] or (a.get("genres") or [])[:5]
    else:
        avisos.append("stats.fm no está configurado: falta la fuente principal")

    if lf and lf.username:
        paso("Last.fm: tus artistas del último año y de siempre")
        for periodo in ("12month", "overall"):
            try:
                filas = lf.user_top_artists(periodo, 500)
            except Exception as e:  # noqa: BLE001
                avisos.append(f"Last.fm ({periodo}) falló: {e}")
                filas = []
            for a in filas:
                if a["playcount"] >= min_escuchas or clave(a["name"]) in pool:
                    c = de_los_tuyos(a["name"])
                    c["escuchas"]["lastfm"] = max(c["escuchas"]["lastfm"], a["playcount"])

    if biblioteca:
        for fila in biblioteca.get("artistas_seguidos") or []:
            de_los_tuyos(fila)["biblioteca"].append("lo sigues")
        for fila in biblioteca.get("artistas_mas_guardados") or []:
            de_los_tuyos(fila["artist"])["biblioteca"].append(
                f"{fila['canciones']} canciones guardadas")
        for fila in biblioteca.get("albumes_recientes_en_tu_biblioteca") or []:
            if fila.get("artist"):
                de_los_tuyos(fila["artist"])["biblioteca"].append("disco guardado")
    else:
        avisos.append("Tu biblioteca de Spotify (seguidos y guardados) no está en la "
                      "caché y pedirla gasta cuota: esta vez no cuenta")

    # Vecinos de los ~50 que más suenan ahora: la órbita
    if lf:
        principales = sorted((c for c in pool.values() if c["escuchas"]["ultimos_6_meses"]),
                             key=lambda c: c["escuchas"]["ultimos_6_meses"],
                             reverse=True)[:N_PRINCIPALES]
        paso(f"Last.fm: vecinos de tus {len(principales)} artistas de los últimos meses")

        def vecinos(c: dict) -> tuple[dict, list]:
            try:
                sims = cache.recordar(f"similares:{clave(c['nombre'])}", TTL_VECINOS,
                                      lambda: lf.similar_artists(c["nombre"], 15))
            except Exception as e:  # noqa: BLE001
                log.warning("Similares de %s fallaron: %s", c["nombre"], e)
                sims = []
            return c, [s for s in sims if (s.get("match") or 0) >= MATCH_MINIMO][:VECINOS_POR_ARTISTA]

        with ThreadPoolExecutor(max_workers=4) as pool_hilos:
            for origen, sims in pool_hilos.map(vecinos, principales):
                for s in sims:
                    k = clave(s["name"])
                    c = pool.get(k)
                    if c is None:
                        c = pool[k] = _nuevo(s["name"], "órbita")
                    if c["relacion"] == "órbita":
                        c["vecino_de"].append({"artista": origen["nombre"],
                                               "match": round(s["match"], 2)})

    # Fuera lo que ha vetado: un disco nuevo de alguien que dijo "nunca más"
    # no es una novedad que le interese
    for k in [k for k, c in pool.items() if norm(c["nombre"]) in vetados]:
        pool.pop(k)
    return pool


# ---------- 2. rastreo en Deezer ----------

def _marca_de_refresco(fin: str) -> float:
    """Lo guardado antes del día siguiente al fin de mes no sabe qué salió al final."""
    limite = dt.datetime.fromisoformat(fin) + dt.timedelta(days=1)
    ahora = time.time()
    return min(limite.timestamp(), ahora - 6 * 3600)


def rastrear_artista(dz: DeezerClient, nombre: str, inicio: str, fin: str,
                     refresco: float, generos_artista=()) -> dict:
    """Qué ha sacado un artista en el mes según Deezer, ya filtrado.

    Con homónimos ("Niños" el grupo y "Niños" de canciones infantiles) se
    miran todos los que se llaman igual y se quedan los discos cuyo género
    cuadra con el artista que escuchas; si ninguno cuadra, pasan como
    dudosos en vez de perderse.
    """
    a = dz.artista(nombre)
    if not a:
        return {"encontrado": False}
    variantes = [a] + [dict(o, aviso=a.get("aviso")) for o in a.get("otros") or []]
    resultados = [_rastrear_variante(dz, v, inicio, fin, refresco) for v in variantes]
    entran = [d for r in resultados for d in r["entran"]]
    fuera = [d for r in resultados for d in r["fuera"]]
    if len(variantes) > 1 and generos_artista:
        mias = familias(generos_artista)

        def cuadra(d):
            del_disco = familias(d.get("generos_disco"))
            return not del_disco or not mias or bool(del_disco & mias)

        if any(cuadra(d) for d in entran):
            for d in [d for d in entran if not cuadra(d)]:
                entran.remove(d)
                fuera.append({**{k: d[k] for k in ("titulo", "fecha", "tipo",
                                                   "canciones", "deezer_id")},
                              "motivo": "homónimo: "
                                        + ", ".join(d["generos_disco"]) + " no es lo tuyo"})
            for d in entran:
                d["homonimo_resuelto"] = True
    return {"encontrado": True, "artista_deezer": a, "entran": entran, "fuera": fuera}


def _rastrear_variante(dz: DeezerClient, a: dict, inicio: str, fin: str,
                       refresco: float) -> dict:
    albumes = dz.albumes(a["id"], desde=refresco)
    del_mes = [x for x in albumes if inicio <= (x.get("release_date") or "") <= fin]
    anteriores = [x for x in albumes
                  if (x.get("release_date") or "") < inicio and x.get("record_type") != "single"]
    entran, fuera = [], []
    vistos: set[str] = set()
    for x in sorted(del_mes, key=lambda x: x.get("record_type") == "single"):
        motivo = filtro_previo(x, anteriores)
        if motivo:
            fuera.append({"titulo": x["title"], "fecha": x["release_date"],
                          "tipo": x.get("record_type"), "motivo": motivo,
                          "deezer_id": x["id"]})
            continue
        ficha = dz.ficha(x["id"])
        motivo = filtro_ficha(ficha)
        base = titulo_base(x["title"])
        if not motivo and base in vistos:
            motivo = "duplicado (otra versión del mismo disco en Deezer)"
        if motivo:
            fuera.append({"titulo": x["title"], "fecha": x["release_date"],
                          "tipo": ficha.get("record_type") or x.get("record_type"),
                          "canciones": ficha.get("nb_tracks"), "motivo": motivo,
                          "deezer_id": x["id"]})
            continue
        vistos.add(base)
        entran.append({"titulo": x["title"], "fecha": x["release_date"],
                       "tipo": ficha.get("record_type") or x.get("record_type"),
                       "canciones": ficha.get("nb_tracks"),
                       "minutos": round((ficha.get("duration") or 0) / 60) or None,
                       "sello": ficha.get("label"), "generos_disco": ficha.get("genres") or [],
                       "deezer_id": x["id"], "artista_deezer": a})
    return {"entran": entran, "fuera": fuera}


def motivo_dudoso(candidato: dict, artista_deezer: dict, disco: dict) -> str | None:
    """Señales de homónimo: se marca, no se descarta (que decida él)."""
    motivos = []
    if (artista_deezer.get("aviso") and "llamados" in artista_deezer["aviso"]
            and not disco.get("homonimo_resuelto")):
        motivos.append(artista_deezer["aviso"])
    escuchas = max(candidato["escuchas"]["total"], candidato["escuchas"]["lastfm"])
    fans = artista_deezer.get("nb_fan") or 0
    if escuchas >= ESCUCHAS_PARA_SOSPECHAR and fans < FANS_SOSPECHOSOS:
        motivos.append(f"lo has escuchado {escuchas} veces pero el artista de Deezer "
                       f"solo tiene {fans} fans: puede ser un homónimo")
    del_disco = familias(disco.get("generos_disco"))
    del_artista = familias(candidato.get("generos"))
    if del_disco and del_artista and not (del_disco & del_artista):
        motivos.append(f"el disco sale como {', '.join(disco['generos_disco'])} y el "
                       f"artista que escuchas es {', '.join(candidato['generos'][:2])}")
    return "; ".join(motivos) or None


# ---------- 3. avales externos ----------

def _plano(s: str) -> str:
    return norm(s)


def menciones_en_prensa(artista: str, titulo: str, inicio: str, fin: str,
                        archivo: list[dict]) -> list[str]:
    """Medios que nombran el disco (artista Y título) cerca del mes.

    Se exige el título porque con el artista solo, "Niños" o "Dummy"
    aparecían en cualquier noticia.
    """
    desde = (dt.date.fromisoformat(inicio) - dt.timedelta(days=45)).isoformat()
    hasta = (dt.date.fromisoformat(fin) + dt.timedelta(days=30)).isoformat()
    a, t = _plano(artista), _plano(re.sub(r"\s*[\(\[].*?[\)\]]", "", titulo))
    if len(t) < 3:
        return []
    medios = []
    for item in archivo:
        if not (desde <= (item.get("date") or "") <= hasta):
            continue
        texto = _plano((item.get("title") or "") + " " + (item.get("summary") or ""))
        if a in texto and t in texto and item.get("source") not in medios:
            medios.append(item.get("source"))
    return medios


def kexp_del_disco(kexp, artista: str, titulo: str, inicio: str) -> int:
    """Cuántas veces ha pinchado KEXP canciones de este disco desde un mes antes."""
    dias = (dt.date.today() - dt.date.fromisoformat(inicio)).days + 30
    try:
        emisiones = kexp.emisiones_de(artista, desde_dias=max(dias, 30))
    except Exception:  # noqa: BLE001
        return 0
    base = titulo_base(titulo)
    return sum(1 for e in emisiones if titulo_base(e.get("album") or "") == base)


# ---------- 4. puntuación ----------

def puntuar(d: dict) -> float:
    e = d["escuchas_artista"]
    puntos = 0.0
    if d["relacion"] == "de_los_tuyos":
        peso = 3 * e["ultimos_6_meses"] + e["total"] + 0.5 * e["lastfm"]
        puntos += 2 + min(12.0, 4 * math.log10(1 + peso))
    elif d["relacion"] == "órbita":
        mejor = max((v["match"] for v in d.get("vecino_de") or []), default=0)
        puntos += 2 + 3 * mejor + min(2, 0.5 * (len(d.get("vecino_de") or []) - 1))
    puntos += 5 * (d.get("afinidad") or 0)
    n = len(d.get("fuentes_externas") or [])
    puntos += 2.5 * min(n, 4) + (2 if n >= 2 else 0)
    puntos += 3 if d["tipo"] == "album" else 1
    if d.get("dudoso"):
        puntos -= 3
    return round(puntos, 1)


def porque(d: dict) -> str:
    e = d["escuchas_artista"]
    partes = []
    if d["relacion"] == "de_los_tuyos":
        total = max(e["total"], e["lastfm"])
        if e["ultimos_6_meses"]:
            partes.append(f"lo has escuchado {total} veces ({e['ultimos_6_meses']} en "
                          "los últimos seis meses)")
        elif total:
            partes.append(f"lo has escuchado {total} veces, aunque no últimamente")
        elif d.get("biblioteca"):
            partes.append(f"está en tu biblioteca ({d['biblioteca'][0]})")
    elif d["relacion"] == "órbita":
        vec = sorted(d["vecino_de"], key=lambda v: -v["match"])[:2]
        partes.append("vecino de " + " y ".join(v["artista"] for v in vec) + " en Last.fm")
    else:
        partes.append("no lo escuchas" if d.get("fuentes_externas")
                      else "no lo escuchas, pero sale en el radar")
    fuentes = d.get("fuentes_externas") or []
    if fuentes:
        partes.append(("lo cita " if len(fuentes) == 1 else "lo citan ")
                      + " y ".join([", ".join(fuentes[:2]), fuentes[2]] if len(fuentes) > 2
                                   else [" y ".join(fuentes)]))
    if d.get("generos_casados"):
        partes.append("encaja con lo tuyo (" + ", ".join(d["generos_casados"][:2]) + ")")
    frase = "; ".join(partes)
    return frase[:1].upper() + frase[1:] + "."


# ---------- todo junto ----------

def calcular(mes: str, sf, lf, dz: DeezerClient, mb, kexp, calendarios,
             biblioteca: dict | None, vetados: dict, vet_fn,
             min_escuchas: int = MIN_ESCUCHAS, paso=lambda _t: None,
             contar_spotify=lambda: 0) -> dict:
    """Rastreo completo de un mes. `vet_fn(nombres)` valida externos (vet_candidates)."""
    inicio, fin = rango_mes(mes)
    avisos: list[str] = []
    spotify_antes = contar_spotify()
    mb_antes = type(mb).peticiones if mb is not None else 0
    lf_antes = type(lf).peticiones if lf is not None else 0
    dz_antes = dz.peticiones
    cal_antes = getattr(calendarios, "peticiones", 0)

    # 1) artistas
    # Se guarda un día, pero solo si stats.fm respondió: un historial vacío
    # por un fallo puntual no debe dejar el rastreo cojo 24 horas.
    clave_cache = f"novedades_mes:candidatos:{min_escuchas}"
    hay, artistas = cache.obtener(clave_cache, TTL_CANDIDATOS)
    if not hay:
        artistas = reunir_artistas(sf, lf, biblioteca, vetados, min_escuchas, paso, avisos)
        if any(c["escuchas"]["total"] for c in artistas.values()):
            cache.guardar(clave_cache, artistas)
    artistas = {k: dict(v, fuentes_externas={}) for k, v in artistas.items()}
    for k in [k for k, c in artistas.items() if norm(c["nombre"]) in vetados]:
        artistas.pop(k)
    generos = mis_generos(artistas)

    # 2) fuentes externas del mes (nombres que no escucha incluidos)
    paso("fuentes del mes: calendarios, prensa y radar")
    externos: dict[str, dict] = {}   # clave → {nombre, fuentes:set, titulos:set, fecha}

    def externo(nombre: str, fuente: str, titulo: str | None = None, fecha=None):
        k = clave(nombre)
        if not k:
            return
        e = externos.setdefault(k, {"nombre": nombre, "fuentes": set(),
                                    "titulos": set(), "fecha": None})
        e["fuentes"].add(fuente)
        if titulo:
            e["titulos"].add(titulo_base(titulo))
        e["fecha"] = e["fecha"] or fecha

    try:
        cal = calendarios.del_mes(mes) if calendarios else {"discos": [], "avisos": []}
    except Exception as e:  # noqa: BLE001
        cal = {"discos": [], "avisos": [f"calendarios: {e}"]}
    avisos.extend(cal.get("avisos") or [])
    for f in cal["discos"]:
        externo(f["artista"], f["fuente"], f.get("titulo"), f.get("fecha"))

    datos_radar = radar_mod.cargar()
    for c in datos_radar.get("candidatos") or []:
        ej = c.get("ejemplo") or {}
        if c.get("triangulado") or c.get("zona") == "encaja":
            externo(c["artist"], "radar", ej.get("album"))
    for r in datos_radar.get("de_los_que_sigues") or []:
        if inicio <= (r.get("fecha") or "")[:10] <= fin:
            externo(r["artist"], "radar", r.get("album"), r.get("fecha"))

    try:
        press.PressClient().fetch(limit_per_source=30, since_days=60)
    except Exception as e:  # noqa: BLE001
        avisos.append(f"prensa: no se pudo refrescar ({e}); uso lo archivado")
    archivo = press.cargar_archivo()
    desde_prensa = (dt.date.fromisoformat(inicio) - dt.timedelta(days=30)).isoformat()
    hasta_prensa = (dt.date.fromisoformat(fin) + dt.timedelta(days=21)).isoformat()
    recientes = [i for i in archivo if desde_prensa <= (i.get("date") or "") <= hasta_prensa]
    for n in press.nombres_en_titulares(recientes):
        externo(n["nombre"], n["medio"] or "prensa")

    for k, e in externos.items():
        if k in artistas:
            artistas[k]["fuentes_externas"] = {f: True for f in e["fuentes"]}

    # 3) Deezer, artista a artista (con caché casi todo es instantáneo)
    refresco = _marca_de_refresco(fin)
    a_rastrear = list(artistas.items()) + [
        (k, _nuevo(e["nombre"], "internacional")) for k, e in externos.items()
        if k not in artistas]
    for k, c in a_rastrear:
        if c["relacion"] == "internacional":
            c["fuentes_externas"] = {f: True for f in externos[k]["fuentes"]}
    total = len(a_rastrear)
    hechos = [0]
    no_en_deezer: list[tuple[str, dict]] = []
    resultados: list[tuple[dict, dict]] = []
    fallos_deezer = 0

    def uno(par):
        k, c = par
        try:
            r = rastrear_artista(dz, c["nombre"], inicio, fin, refresco,
                                 c.get("generos") or [])
        except DeezerError as e:
            r = {"error": str(e)}
        hechos[0] += 1
        if hechos[0] % 25 == 0:
            paso(f"Deezer: {hechos[0]} de {total} artistas revisados")
        return c, r

    paso(f"Deezer: revisando {total} artistas")
    with ThreadPoolExecutor(max_workers=8) as hilos:
        for c, r in hilos.map(uno, a_rastrear):
            if r.get("error"):
                fallos_deezer += 1
            elif not r["encontrado"]:
                no_en_deezer.append((clave(c["nombre"]), c))
            else:
                resultados.append((c, r))
    dz.volcar()
    if fallos_deezer:
        avisos.append(f"Deezer falló con {fallos_deezer} artistas ({dz.fallos}); "
                      "la lista puede estar incompleta: vuelve a lanzarlo luego")

    discos: list[dict] = []
    descartados: list[dict] = []
    singles = 0
    for c, r in resultados:
        for f in r["fuera"]:
            if f["motivo"] == "single":
                singles += 1
                continue
            descartados.append({"artista": c["nombre"], **f})
        for d in r["entran"]:
            discos.append({
                "artista": c["nombre"], "titulo": d["titulo"], "fecha": d["fecha"],
                "tipo": d["tipo"], "canciones": d["canciones"], "minutos": d["minutos"],
                "sello": d["sello"], "relacion": c["relacion"],
                "escuchas_artista": dict(c["escuchas"]),
                "biblioteca": c.get("biblioteca") or [],
                "vecino_de": c.get("vecino_de") or [],
                "generos_artista": c.get("generos") or [],
                "generos_disco": d["generos_disco"],
                "dudoso": False,
                "motivo_dudoso": motivo_dudoso(c, d.get("artista_deezer") or r["artista_deezer"], d),
                "ids": {"deezer": d["deezer_id"], "musicbrainz": None},
                "_fuentes_artista": sorted(c.get("fuentes_externas") or {}),
                "_clave": clave(c["nombre"]),
            })

    # 4) MusicBrainz: respaldo para los tuyos que Deezer no tiene, y fechas
    presupuesto = [MAX_PETICIONES_MB]
    tuyos_sin_deezer = sorted(
        (c for _, c in no_en_deezer if c["relacion"] == "de_los_tuyos"),
        key=lambda c: -(3 * c["escuchas"]["ultimos_6_meses"] + c["escuchas"]["total"]))
    if mb is not None:
        paso(f"MusicBrainz: {min(len(tuyos_sin_deezer), MAX_PETICIONES_MB)} artistas "
             "que Deezer no encuentra")
        for c in tuyos_sin_deezer:
            if presupuesto[0] <= 0:
                avisos.append(f"MusicBrainz: quedaron {len(tuyos_sin_deezer)} artistas sin "
                              "Deezer y solo se miraron los primeros (1 petición por segundo)")
                break
            filas = cache.obtener(f"mb_mes:{clave(c['nombre'])}:{mes}", 7 * 24 * 3600)
            if filas[0]:
                filas = filas[1]
            else:
                presupuesto[0] -= 1
                filas = mb.lanzamientos_entre(c["nombre"], inicio, fin)
                cache.guardar(f"mb_mes:{clave(c['nombre'])}:{mes}", filas)
            for rg in filas:
                tipo = (rg.get("tipo") or "").lower()
                motivo = (("recopilatorio" if "Compilation" in rg["subtipos"] else
                           "directo" if "Live" in rg["subtipos"] else
                           "remezclas" if "Remix" in rg["subtipos"] else
                           "banda sonora" if "Soundtrack" in rg["subtipos"] else
                           ", ".join(rg["subtipos"]).lower()) if rg["subtipos"]
                          else ("single" if tipo == "single" else
                                motivo_por_titulo(rg["album"]) or
                                (None if tipo in ("album", "ep") else f"tipo {tipo or '?'}")))
                if motivo == "single":
                    singles += 1
                    continue
                if motivo:
                    descartados.append({"artista": c["nombre"], "titulo": rg["album"],
                                        "fecha": rg["fecha"], "tipo": tipo, "motivo": motivo,
                                        "musicbrainz_id": rg["mbid"]})
                    continue
                discos.append({
                    "artista": c["nombre"], "titulo": rg["album"], "fecha": rg["fecha"],
                    "tipo": tipo, "canciones": None, "minutos": None, "sello": None,
                    "relacion": c["relacion"], "escuchas_artista": dict(c["escuchas"]),
                    "biblioteca": c.get("biblioteca") or [], "vecino_de": [],
                    "generos_artista": c.get("generos") or [], "generos_disco": [],
                    "dudoso": False,
                    "motivo_dudoso": ("EP según MusicBrainz, que no dice cuántas "
                                      "canciones tiene" if tipo == "ep" else None),
                    "ids": {"deezer": None, "musicbrainz": rg["mbid"]},
                    "_fuentes_artista": sorted(c.get("fuentes_externas") or {}),
                    "_clave": clave(c["nombre"]), "_solo_mb": True})

    # Duplicados entre Deezer y MusicBrainz
    vistos: dict[tuple, dict] = {}
    unicos = []
    for d in discos:
        k = (d["_clave"], titulo_base(d["titulo"]))
        if k in vistos:
            continue
        vistos[k] = d
        unicos.append(d)
    discos = unicos

    # 5) externos: pasan por vet_candidates y por tus géneros
    internacionales = [d for d in discos if d["relacion"] == "internacional"]
    if internacionales:
        paso(f"validando {len(internacionales)} discos que solo cita la prensa o el radar")
        nombres = list(dict.fromkeys(d["artista"] for d in internacionales))
        fichas: dict[str, dict] = {}
        for i in range(0, len(nombres), 20):
            try:
                res = vet_fn(nombres[i:i + 20])
                for f in res.get("candidatos") or []:
                    fichas[clave(f["artist"])] = f
            except Exception as e:  # noqa: BLE001
                avisos.append(f"vet_candidates falló ({e}): los externos van sin validar")
        quedan = []
        for d in discos:
            if d["relacion"] != "internacional":
                quedan.append(d)
                continue
            f = fichas.get(d["_clave"]) or {}
            veredicto = (f.get("tu_opinion") or {}).get("veredicto")
            if veredicto in ("nunca más", "no es lo mío"):
                descartados.append({"artista": d["artista"], "titulo": d["titulo"],
                                    "fecha": d["fecha"], "tipo": d["tipo"],
                                    "motivo": f"lo vetaste ({veredicto})"})
                continue
            d["generos_artista"] = f.get("etiquetas") or []
            if f.get("nivel") in ("conocido", "muy escuchado"):
                d["relacion"] = "de_los_tuyos"
            af, casados = afinidad(d["generos_artista"] or d["generos_disco"], generos)
            n_fuentes = len(d["_fuentes_artista"])
            if not af and n_fuentes < 2:
                descartados.append({"artista": d["artista"], "titulo": d["titulo"],
                                    "fecha": d["fecha"], "tipo": d["tipo"],
                                    "motivo": "fuera de tus géneros ("
                                              + ", ".join(d["generos_artista"][:3] or ["sin etiquetas"])
                                              + ") y con una sola fuente"})
                continue
            d["_vet"] = {"oyentes": f.get("oyentes"), "senales": (f.get("senales") or [])[:3]}
            quedan.append(d)
        discos = quedan

    # 6) avales del disco y puntuación
    paso(f"avales y puntuación de {len(discos)} discos")

    def avales(d: dict) -> dict:
        fuentes = set(d["_fuentes_artista"])
        base = titulo_base(d["titulo"])
        ext = externos.get(d["_clave"])
        if ext and ext["titulos"] and base not in ext["titulos"]:
            # el calendario cita OTRO disco del artista: no avala este
            fuentes -= {f for f in ext["fuentes"] if f != "radar"}
        fuentes.update(menciones_en_prensa(d["artista"], d["titulo"], inicio, fin, archivo))
        if kexp is not None and kexp_del_disco(kexp, d["artista"], d["titulo"], inicio):
            fuentes.add("KEXP")
        d["fuentes_externas"] = sorted(f for f in fuentes if f)
        return d

    with ThreadPoolExecutor(max_workers=4) as hilos:
        discos = list(hilos.map(avales, discos))

    for d in discos:
        d["afinidad"], d["generos_casados"] = afinidad(
            d["generos_artista"] or d["generos_disco"], generos)
        d["dudoso"] = bool(d["motivo_dudoso"])
        d["puntos"] = puntuar(d)
        d["porque"] = porque(d)
        d["fuentes"] = (["Deezer"] if d["ids"]["deezer"] else ["MusicBrainz"]) + d["fuentes_externas"]

    discos.sort(key=lambda d: (-d["puntos"], d["fecha"]))
    salida = [{
        "artista": d["artista"], "titulo": d["titulo"], "fecha": d["fecha"],
        "tipo": d["tipo"], "canciones": d["canciones"], "minutos": d["minutos"],
        "sello": d["sello"], "relacion": d["relacion"],
        "escuchas_artista": d["escuchas_artista"], "puntos": d["puntos"],
        "porque": d["porque"], "fuentes": d["fuentes"], "dudoso": d["dudoso"],
        "motivo_dudoso": d["motivo_dudoso"], "ids": d["ids"],
    } for d in discos]
    descartados.sort(key=lambda d: (d.get("motivo") or "", d.get("fecha") or ""))

    return {
        "mes": mes,
        "discos": salida,
        "descartados": descartados,
        "estadisticas": {
            "artistas_rastreados": total,
            "de_los_tuyos": sum(1 for c in artistas.values() if c["relacion"] == "de_los_tuyos"),
            "orbita": sum(1 for c in artistas.values() if c["relacion"] == "órbita"),
            "solo_de_fuentes_externas": total - len(artistas),
            "encontrados_en_deezer": len(resultados),
            "no_encontrados_en_deezer": len(no_en_deezer),
            "buscados_en_musicbrainz": MAX_PETICIONES_MB - presupuesto[0],
            "externos_sin_deezer": [c["nombre"] for _, c in no_en_deezer
                                    if c["relacion"] == "internacional"][:20] or None,
            "discos_del_mes": len(salida),
            "singles_ignorados": singles,
            "calendarios_leidos": cal.get("leidos"),
            "peticiones": {
                "deezer": dz.peticiones - dz_antes,
                "musicbrainz": (type(mb).peticiones - mb_antes) if mb is not None else 0,
                "lastfm": (type(lf).peticiones - lf_antes) if lf is not None else 0,
                "calendarios": getattr(calendarios, "peticiones", 0) - cal_antes,
            },
            "peticiones_a_spotify": contar_spotify() - spotify_antes,
            "esperas_por_cuota_de_deezer": dz.esperas_por_cuota,
        },
        "avisos": avisos or None,
    }
