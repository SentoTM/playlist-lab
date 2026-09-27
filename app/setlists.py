"""De muchos setlists a un setlist típico, para preparar un concierto.

Por qué existe: en la lista de Vetusta Morla el modelo tuvo que suponer el
setlist. Con setlist.fm se sabe qué canciones caen casi siempre, en qué
orden, con cuáles abren y cierran, y cuáles son sorpresa de una noche.
"""
import datetime as dt
from collections import Counter, defaultdict

from .text import norm

FIJA = 0.7        # sale en el 70 % o más de los conciertos
HABITUAL = 0.4


def _fecha(s: dict) -> str:
    d = s.get("eventDate") or ""          # dd-MM-yyyy
    try:
        return dt.datetime.strptime(d, "%d-%m-%Y").date().isoformat()
    except ValueError:
        return d


def _canciones(s: dict) -> list[dict]:
    out = []
    for bloque in ((s.get("sets") or {}).get("set") or []):
        bis = bool(bloque.get("encore"))
        for c in bloque.get("song") or []:
            if c.get("tape") or not c.get("name"):
                continue       # las cintas de entrada o salida no las tocan
            out.append({"titulo": c["name"], "bis": bis,
                        "version_de": (c.get("cover") or {}).get("name"),
                        "con": (c.get("with") or {}).get("name")})
    return out


def resumir(setlists: list[dict], gira: str = "", ultimos: int = 15) -> dict:
    giras = Counter((s.get("tour") or {}).get("name") for s in setlists
                    if (s.get("tour") or {}).get("name"))
    candidatos = [s for s in setlists if _canciones(s)]
    if gira:
        candidatos = [s for s in candidatos
                      if norm(gira) in norm((s.get("tour") or {}).get("name") or "")]
    candidatos = candidatos[:ultimos]
    if not candidatos:
        return {"conciertos_con_setlist": 0, "giras_recientes": dict(giras.most_common(5)),
                "aviso": ("No hay setlists con canciones para eso. Si la gira es nueva, "
                          "prueba sin 'gira' para usar la anterior, y dilo.")}

    n = len(candidatos)
    veces, posiciones, bises, info = Counter(), defaultdict(list), Counter(), {}
    aperturas, cierres = Counter(), Counter()
    for s in candidatos:
        canciones = _canciones(s)
        vistas = set()
        for i, c in enumerate(canciones):
            clave = norm(c["titulo"])
            if clave in vistas:
                continue
            vistas.add(clave)
            veces[clave] += 1
            posiciones[clave].append(i / max(1, len(canciones) - 1))
            bises[clave] += c["bis"]
            info.setdefault(clave, c)
        aperturas[norm(canciones[0]["titulo"])] += 1
        cierres[norm(canciones[-1]["titulo"])] += 1

    def fila(clave):
        c = info[clave]
        return {"titulo": c["titulo"], "frecuencia": f"{veces[clave]}/{n}",
                "en_bis": bises[clave] > veces[clave] / 2,
                **({"version_de": c["version_de"]} if c["version_de"] else {})}

    tipico = [k for k in veces if veces[k] / n >= HABITUAL]
    tipico.sort(key=lambda k: (bises[k] > veces[k] / 2,
                               sum(posiciones[k]) / len(posiciones[k])))
    rarezas = [k for k in veces if veces[k] == 1 and n >= 4]
    ultimo = candidatos[0]
    venue = ultimo.get("venue") or {}
    return {
        "conciertos_con_setlist": n,
        "periodo": f"{_fecha(candidatos[-1])} → {_fecha(candidatos[0])}",
        "giras_recientes": dict(giras.most_common(5)),
        "setlist_tipico": [fila(k) | {"fija": veces[k] / n >= FIJA} for k in tipico],
        "suele_abrir": [info[k]["titulo"] for k, _ in aperturas.most_common(2)],
        "suele_cerrar": [info[k]["titulo"] for k, _ in cierres.most_common(2)],
        "sorpresas_de_una_noche": [info[k]["titulo"] for k in rarezas][:10] or None,
        "ultimo_concierto": {
            "fecha": _fecha(ultimo),
            "lugar": f"{venue.get('name', '')}, {(venue.get('city') or {}).get('name', '')}",
            "gira": (ultimo.get("tour") or {}).get("name"),
            "canciones": [c["titulo"] for c in _canciones(ultimo)],
            "url": ultimo.get("url"),
        },
        "fuente": "setlist.fm (citar al usar estos datos)",
        "como_usarlo": (
            "El setlist típico va en el orden medio de la gira, con los bises al "
            "final. 'fija' = sale en el 70 % o más. Para una lista de previa, "
            "respeta ese arco y di que es el típico, no el de su noche. Resuelve "
            "las canciones con resolve: si el título de setlist.fm no casa, prueba "
            "sin paréntesis."),
    }
