"""Atlas e itinerario: viajes por TODO su gusto, no solo por lo último.

Por qué existe: si casi todo lo que escucha son las listas que le hacemos,
la huella solo mide cómo le han ido esas listas, y dejar que ella decida
el destino de la semana acaba en una madriguera. Así que el MOTOR de la
tanda semanal es su historial completo (stats.fm de siempre), agrupado en
territorios; una rotación decide qué territorio toca y con qué tipo de
viaje. La huella y las semillas solo ajustan lo de dentro.
"""
import datetime as dt
import json
import math
import threading
from collections import defaultdict
from pathlib import Path

from .text import norm

RUTA = Path(__file__).resolve().parent.parent / "datos" / "rutas.json"
_lock = threading.Lock()

# Familias de géneros, en orden de prioridad: un artista va a la primera
# familia con la que casan más de sus géneros. El castellano va primero
# porque para él la escena de aquí es un territorio en sí mismo.
FAMILIAS = [
    ("Indie y rock en castellano", ["spanish", "espanol", "español", "latin indie",
                                    "rock en espanol", "movida", "valencian", "catalan",
                                    "galician", "basque", "argentin", "chilean", "mexican"]),
    ("Metal y sus ramas", ["metal", "doom", "sludge", "stoner", "djent", "grindcore"]),
    ("Post-punk, new wave y alrededores", ["post-punk", "new wave", "no wave", "coldwave",
                                           "darkwave", "gothic", "goth", "crank wave",
                                           "egg punk", "art punk", "minimal wave"]),
    ("Punk, hardcore y emo", ["punk", "hardcore", "emo", "riot grrrl", "oi"]),
    ("Kraut, psicodelia y progresivo", ["kraut", "psych", "space rock", "progressive",
                                        "prog", "neo-psychedelic"]),
    ("Electrónica y baile", ["electronic", "techno", "house", "idm", "ambient", "synth",
                             "electro", "trip hop", "downtempo", "drum and bass",
                             "breakbeat", "dance"]),
    ("Hip hop y rap", ["hip hop", "rap", "trap", "grime", "drill"]),
    ("Jazz, soul, funk y groove", ["jazz", "soul", "funk", "r&b", "afrobeat", "disco",
                                   "gospel", "blues"]),
    ("Folk, cantautores y raíces", ["folk", "singer-songwriter", "cantautor", "americana",
                                    "country", "bluegrass"]),
    ("Clásica, bandas sonoras y contemporánea", ["classical", "soundtrack", "orchestral",
                                                 "modern classical", "minimalism", "score"]),
    ("Músicas del mundo", ["flamenco", "cumbia", "reggae", "dub", "world", "afro",
                           "bossa", "samba", "fado", "tropical"]),
    ("Shoegaze, dream pop y post-rock", ["shoegaze", "dream pop", "slowcore", "sadcore",
                                         "post-rock", "ethereal"]),
    ("Guitarras británicas: britpop, garage y Madchester",
     ["britpop", "madchester", "garage rock", "sheffield", "manchester", "permanent wave",
      "modern rock", "indie rock"]),
    ("Grunge, noise y alternativo de los 90", ["grunge", "noise rock", "alternative rock",
                                               "math rock", "post-hardcore", "nu metal"]),
    ("Indie, alternativo y guitarras", ["indie", "alternative", "lo-fi", "noise", "garage",
                                        "rock"]),
    ("Pop", ["pop"]),
]

TIPOS_DE_VIAJE = [
    ("genealogía", "De dónde viene y a dónde fue: raíces antes, herederos después "
                   "(influence_evidence y check_lineage)."),
    ("escena", "Una escena o ciudad concreta dentro del territorio: quién tocaba con "
               "quién, salas, sellos (explore_scene, artist_context)."),
    ("época", "Un año o un lustro concreto del territorio, lo grande y lo que se "
              "quedó en los márgenes (explore_era)."),
    ("sello", "Un sello clave del territorio por dentro (labels_of, label_catalog)."),
    ("universo", "El universo de uno de SUS grupos de ese territorio: miembros, "
                 "proyectos paralelos, influencias y quien vino después."),
    ("cruce", "La misma energía de ese territorio buscada en otro género u otro país: "
              "el rasgo, no la etiqueta."),
]


_CASTELLANO = FAMILIAS[0]


def _familia(generos: list[str]) -> str | None:
    """Familia de un artista a partir de sus etiquetas EN ORDEN (la primera,
    la más votada en Last.fm, es la que manda).

    - Si alguna etiqueta dice que es de aquí (spanish, español…), va a
      castellano: Spotify etiqueta a Vetusta Morla o Alcalá Norte solo como
      'indie rock', y así se perdía la escena de aquí.
    - Si no, gana la primera etiqueta que case con alguna familia, probando
      las familias en orden (las genéricas, 'indie' o 'pop', al final).
    """
    etiquetas = [norm(x) for x in generos if x]
    if not etiquetas:
        return None
    if any(norm(c) in e for e in etiquetas for c in _CASTELLANO[1] + ["spain"]):
        return _CASTELLANO[0]
    for e in etiquetas:
        for nombre, claves in FAMILIAS[1:]:
            if any(norm(c) in e for c in claves):
                return nombre
    return None


def construir(artistas: list[dict], etiquetas_extra=None) -> dict:
    """artistas: [{'name','streams','genres'}] (stats.fm de siempre).
    etiquetas_extra(nombre) → etiquetas de Last.fm para los que no traen géneros."""
    territorios: dict[str, dict] = defaultdict(lambda: {"streams": 0, "artistas": [],
                                                       "generos": defaultdict(int)})
    extra = {}
    if etiquetas_extra:
        from concurrent.futures import ThreadPoolExecutor

        def seguro(nombre):
            try:
                return etiquetas_extra(nombre) or []
            except Exception:  # noqa: BLE001
                return []
        with ThreadPoolExecutor(max_workers=8) as pool:
            extra = dict(zip([a["name"] for a in artistas],
                             pool.map(seguro, [a["name"] for a in artistas])))
    for a in artistas:
        # Last.fm primero (ordenadas por votos), luego los géneros de Spotify
        generos = list(extra.get(a["name"]) or []) + list(a.get("genres") or [])
        fam = _familia(generos) or "Sin clasificar"
        t = territorios[fam]
        t["streams"] += a.get("streams") or 0
        t["artistas"].append({"artist": a["name"], "streams": a.get("streams") or 0})
        for g in generos[:4]:
            t["generos"][g] += 1
    total = sum(t["streams"] for t in territorios.values()) or 1
    out = {}
    for nombre, t in sorted(territorios.items(), key=lambda kv: -kv[1]["streams"]):
        out[nombre] = {
            "peso": round(100 * t["streams"] / total, 1),
            "artistas": [x["artist"] for x in sorted(t["artistas"], key=lambda x: -x["streams"])],
            "generos": [g for g, _ in sorted(t["generos"].items(), key=lambda kv: -kv[1])[:8]],
        }
    return out


def cargar_rutas() -> list[dict]:
    try:
        return json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def registrar(territorio: str, tipo: str, titulo: str, anclas: list[str]) -> dict:
    viaje = {"fecha": dt.date.today().isoformat(), "territorio": territorio,
             "tipo": tipo, "titulo": titulo, "anclas": anclas}
    with _lock:
        datos = cargar_rutas()
        datos.append(viaje)
        RUTA.parent.mkdir(exist_ok=True)
        RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    return viaje


def siguiente(atlas: dict, hoy: dt.date | None = None) -> dict:
    """El próximo viaje: territorio, tipo y puntos de partida."""
    hoy = hoy or dt.date.today()
    rutas = cargar_rutas()
    ultima = {}
    for r in rutas:
        ultima[r["territorio"]] = max(ultima.get(r["territorio"], ""), r["fecha"])
    usadas = {a for r in rutas for a in r.get("anclas", [])}

    def dias(terr):
        f = ultima.get(terr)
        return (hoy - dt.date.fromisoformat(f)).days if f else 120

    candidatos = {k: v for k, v in atlas.items()
                  if k != "Sin clasificar" and len(v["artistas"]) >= 3 and dias(k) >= 14}
    if not candidatos:
        candidatos = {k: v for k, v in atlas.items() if k != "Sin clasificar"}
    # Peso con raíz: los territorios grandes vuelven más, pero los pequeños
    # también llegan. El tiempo sin visitar empuja a rotar.
    def puntos(k):
        return math.sqrt(atlas[k]["peso"] + 1) * (1 + dias(k) / 14)
    territorio = max(candidatos, key=puntos)

    tipos_usados = [r["tipo"] for r in rutas]
    def ultimo_uso(t):
        return max((i for i, x in enumerate(tipos_usados) if x == t), default=-1)
    tipo, como = min(TIPOS_DE_VIAJE, key=lambda tc: ultimo_uso(tc[0]))

    anclas = [a for a in atlas[territorio]["artistas"] if a not in usadas][:5] \
        or atlas[territorio]["artistas"][:5]
    return {
        "territorio": territorio,
        "peso_en_tu_historial": f"{atlas[territorio]['peso']} %",
        "ultima_visita": ultima.get(territorio) or "nunca",
        "tipo_de_viaje": tipo, "como": como,
        "puntos_de_partida": anclas,
        "generos_del_territorio": atlas[territorio]["generos"],
        "viajes_anteriores": [f"{r['fecha']} · {r['territorio']} · {r['tipo']} · {r['titulo']}"
                              for r in rutas[-6:]] or None,
        "instrucciones": (
            "Monta el viaje por ESTE territorio con ESTE tipo, arrancando de sus propios "
            "grupos (puntos de partida) hacia lo que no conoce. La huella y las semillas "
            "solo ajustan: como mucho un día para regar una semilla que prendió. Al crear "
            "las listas, registra el viaje con journey_done."),
    }
