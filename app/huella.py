"""Huella: qué pasó de verdad con cada cosa que se le propuso.

Por qué existe: escucha sobre todo mientras trabaja y no siempre tiene ganas
de dar su opinión. Pero su escucha habla por él: si un disco lo acabó, si
volvió a él otro día, si se guardó una canción o si después tiró del hilo
con otros discos del mismo artista. Todo eso sale de los scrobbles de
Last.fm (con fecha y disco) y de las canciones guardadas en Spotify (una
petición). Sin esfuerzo por su parte.

La huella no sustituye a su opinión: la complementa. "Lo escuchó tres veces"
no dice si le gustó, pero "no pasó de la pista 3" dice bastante.
"""
import datetime as dt
import json
import re
import threading
from collections import defaultdict
from pathlib import Path

from . import historial, notes
from .text import des_escapar, norm

RUTA = Path(__file__).resolve().parent.parent / "datos" / "listas.json"
RUTA_SCROBBLES = RUTA.with_name("scrobbles.json")
ARRAIGO_DIAS = 14     # volver a algo pasadas dos semanas es la señal más fuerte
_lock = threading.Lock()

ENTERO = 0.8          # fracción de pistas distintas para contar "entero"
DIAS_DE_GRACIA = 3    # antes de esto, "sin tocar" es "aún es pronto"
TIRO_DEL_HILO = 3     # escuchas de otros discos del artista


# ---------- registro de listas ----------

def cargar_listas() -> dict:
    if not RUTA.exists():
        return {}
    try:
        return json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registrar_lista(nombre: str, resueltos: list[dict], url: str = "") -> None:
    """Guarda qué llevaba cada lista creada, con su fecha."""
    nombre = des_escapar(nombre)
    elementos = []
    for r in resueltos:
        if r.get("type") == "album":
            elementos.append({"tipo": "album", "artista": r.get("artist"),
                              "album": r.get("album"), "pistas": r.get("n_tracks")})
        else:
            elementos.append({"tipo": "cancion", "artista": r.get("artist"),
                              "cancion": r.get("title"), "album": r.get("album")})
    with _lock:
        datos = cargar_listas()
        datos[nombre] = {"fecha": dt.date.today().isoformat(), "url": url,
                         "elementos": elementos}
        RUTA.parent.mkdir(exist_ok=True)
        RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                        encoding="utf-8")


def _todas() -> dict:
    """Listas registradas + las anteriores a este registro, reconstruidas
    de las notas (discos) y del historial (artistas de listas de canciones)."""
    listas = cargar_listas()
    for v in notes.cargar().get("albumes", {}).values():
        nota = v.get("nota") or ""
        if "«" not in nota:
            continue
        nombre = nota.split("«", 1)[1].split("»", 1)[0]
        if nombre in listas and not listas[nombre].get("_reconstruida"):
            continue
        l = listas.setdefault(nombre, {"fecha": v.get("desde"), "elementos": [],
                                       "_reconstruida": True})
        l["elementos"].append({"tipo": "album", "artista": v.get("artista"),
                               "album": v.get("album"), "pistas": None})
    for fila in historial.cargar().values():
        for l in fila.get("listas", []):
            if l["nombre"] in listas:
                continue
            listas.setdefault(l["nombre"], {"fecha": l["fecha"], "elementos": [],
                                            "_reconstruida": True, "_solo_artistas": True})
    for fila in historial.cargar().values():
        for l in fila.get("listas", []):
            destino = listas.get(l["nombre"])
            if destino and destino.get("_solo_artistas"):
                destino["elementos"].append({"tipo": "artista", "artista": fila["artista"]})
    return listas


# ---------- scrobbles: almacén incremental ----------

def scrobbles_desde(lf, desde: int) -> list[dict]:
    """Scrobbles desde `desde`, guardados en disco y pedidos solo los nuevos.

    Sin esto, mirar dos meses atrás a alguien que escucha mucho supone miles
    de scrobbles por consulta, y con un tope de páginas se perdían justo los
    primeros días de cada lista. Así cada consulta trae solo lo último.
    """
    try:
        datos = json.loads(RUTA_SCROBBLES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        datos = {"desde": None, "filas": []}
    filas = datos["filas"]
    tengo_desde = datos.get("desde")
    ultimo = max((f[0] for f in filas), default=0)
    if tengo_desde is None or desde < tengo_desde:
        # hace falta historia más antigua: se pide el hueco que falta
        hasta_hueco = tengo_desde or 0
        viejos = [t for t in lf.recent_tracks(desde, max_paginas=100)
                  if not hasta_hueco or t["uts"] < hasta_hueco]
        filas += [[t["uts"], t["artist"], t["album"], t["track"]] for t in viejos]
        datos["desde"] = desde
    nuevos = lf.recent_tracks(ultimo + 1, max_paginas=100) if ultimo else []
    filas += [[t["uts"], t["artist"], t["album"], t["track"]] for t in nuevos]
    vistos, limpias = set(), []
    for f in sorted(filas):
        clave = (f[0], f[3])
        if clave not in vistos:
            vistos.add(clave)
            limpias.append(f)
    datos["filas"] = limpias
    RUTA_SCROBBLES.parent.mkdir(exist_ok=True)
    RUTA_SCROBBLES.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return [{"uts": f[0], "artist": f[1], "album": f[2], "track": f[3]}
            for f in limpias if f[0] >= desde]


# ---------- cálculo ----------

def _k(s: str) -> str:
    """Clave laxa: 'Public Image Ltd.' y 'Public Image Ltd' son lo mismo."""
    return re.sub(r"[^a-z0-9]", "", norm(s or ""))


def _mismo_album(a: str, b: str) -> bool:
    a, b = _k(a), _k(b)
    return bool(a and b) and (a == b or a.startswith(b) or b.startswith(a))


def _ts(fecha: str) -> int:
    return int(dt.datetime.fromisoformat(fecha).timestamp())


def calcular(scrobbles: list[dict], guardadas: list[dict], listas: dict,
             hoy: dt.date | None = None) -> dict:
    hoy = hoy or dt.date.today()
    por_artista = defaultdict(list)
    for s in scrobbles:
        por_artista[_k(s["artist"])].append(s)
    guardadas_por_artista = defaultdict(list)
    for g in guardadas:
        guardadas_por_artista[_k(g["artist"])].append(g)

    salida = {}
    for nombre, lista in listas.items():
        fecha = lista.get("fecha") or hoy.isoformat()
        desde = _ts(fecha)
        dias = (hoy - dt.date.fromisoformat(fecha)).days
        filas = []
        for e in lista["elementos"]:
            art = _k(e.get("artista"))
            suyas = [s for s in por_artista.get(art, []) if s["uts"] >= desde]
            guardo = [g for g in guardadas_por_artista.get(art, [])
                      if g["added_at"][:10] >= fecha]
            fila = {"artista": e.get("artista"), "tipo": e["tipo"]}
            if e["tipo"] == "album":
                del_disco = [s for s in suyas if _mismo_album(s["album"], e["album"])]
                otros = [s for s in suyas if s not in del_disco]
                distintas = {_k(s["track"]) for s in del_disco}
                fila.update(album=e["album"], escuchas=len(del_disco),
                            pistas_distintas=len(distintas), pistas=e.get("pistas"))
                guardo = [g for g in guardo if _mismo_album(g["album"], e["album"])] or guardo
            elif e["tipo"] == "cancion":
                del_disco = [s for s in suyas if _k(s["track"]) == _k(e.get("cancion"))]
                otros = [s for s in suyas if s not in del_disco]
                fila.update(cancion=e.get("cancion"), escuchas=len(del_disco))
            else:
                del_disco, otros = suyas, []
                fila.update(escuchas=len(suyas))
            dias_distintos = sorted({dt.date.fromtimestamp(s["uts"]).isoformat()
                                     for s in del_disco})
            fila["dias_con_escuchas"] = len(dias_distintos)
            fila["otras_cosas_del_artista"] = len(otros)
            fila["canciones_guardadas"] = [g["track"] for g in guardo][:5] or None

            ult_propia = dias_distintos[-1] if dias_distintos else None
            ult_otros = (dt.date.fromtimestamp(max(s["uts"] for s in otros)).isoformat()
                         if otros else None)
            fila["ultima_escucha"] = max(filter(None, [ult_propia, ult_otros]), default=None)
            senales = []
            inicio = dt.date.fromisoformat(fecha)
            if ult_propia and (dt.date.fromisoformat(ult_propia) - inicio).days >= ARRAIGO_DIAS:
                semanas = (dt.date.fromisoformat(ult_propia) - inicio).days // 7
                senales.append(f"ARRAIGÓ: sigue volviendo a esto {semanas} semanas después")
                fila["arraigo"] = True
            elif ult_otros and (dt.date.fromisoformat(ult_otros) - inicio).days >= ARRAIGO_DIAS:
                semanas = (dt.date.fromisoformat(ult_otros) - inicio).days // 7
                senales.append(f"ARRAIGÓ EL ARTISTA: {semanas} semanas después escucha otras cosas suyas")
                fila["arraigo"] = True
            if len(dias_distintos) >= 2:
                senales.append(f"volvió otro día ({len(dias_distintos)} días distintos)")
            if guardo:
                senales.append("se guardó " + ", ".join(g["track"] for g in guardo[:3]))
            if len(otros) >= TIRO_DEL_HILO:
                senales.append(f"tiró del hilo: {len(otros)} escuchas de otras cosas del artista")

            if e["tipo"] == "album":
                n = e.get("pistas") or 0
                if not del_disco:
                    estado = ("guardó algo sin scrobble" if guardo
                              else "aún es pronto" if dias < DIAS_DE_GRACIA else "sin tocar")
                elif n and len(distintas) / n >= ENTERO:
                    estado = "entero"
                elif n:
                    estado = f"a medias ({len(distintas)}/{n} pistas)"
                else:
                    estado = f"escuchado ({len(distintas)} pistas distintas)"
            else:
                estado = ("escuchado" if del_disco else "guardó algo sin scrobble" if guardo
                          else "sin tocar" if dias >= DIAS_DE_GRACIA else "aún es pronto")
            fila["estado"] = estado
            fila["prendio"] = bool(senales)
            fila["senales"] = senales or None
            filas.append(fila)
        salida[nombre] = {
            "fecha": fecha, "url": lista.get("url"),
            "resumen": {
                "prendieron": [f["album"] if f.get("album") else f["artista"]
                               for f in filas if f["prendio"]],
                "arraigaron": [f["album"] if f.get("album") else f["artista"]
                               for f in filas if f.get("arraigo")],
                "enteros": sum(1 for f in filas if f["estado"] == "entero"),
                "a_medias": sum(1 for f in filas if f["estado"].startswith("a medias")),
                "sin_tocar": sum(1 for f in filas if f["estado"] == "sin tocar"),
            },
            "elementos": filas,
        }
    return salida


def huella(lf, sp=None, lista: str = "", dias: int = 180) -> dict:
    listas = _todas()
    if lista:
        elegidas = {k: v for k, v in listas.items() if norm(lista) in norm(k)}
        if not elegidas:
            return {"error": f"No encuentro la lista '{lista}'",
                    "listas": sorted(listas, key=lambda k: listas[k].get("fecha") or "")}
        listas = elegidas
    limite = (dt.date.today() - dt.timedelta(days=dias)).isoformat()
    listas = {k: v for k, v in listas.items() if (v.get("fecha") or "") >= limite}
    if not listas:
        return {"error": f"No hay listas de los últimos {dias} días"}
    desde = min(v["fecha"] for v in listas.values())
    avisos = []
    scrobbles = scrobbles_desde(lf, _ts(desde))
    guardadas = []
    if sp is not None:
        try:
            guardadas = sp.saved_tracks_since(desde)
        except Exception as e:  # noqa: BLE001
            avisos.append(f"Sin canciones guardadas de Spotify: {e}")
    res = calcular(scrobbles, guardadas, listas)
    return {"listas": res, "scrobbles_revisados": len(scrobbles), "avisos": avisos or None,
            "como_leerlo": (
                "Es lo que HIZO, no lo que opina. 'prendio' = volvió otro día, se "
                "guardó algo o tiró del hilo del artista: son las semillas que "
                "han agarrado, y de ahí conviene seguir. 'arraigaron' = sigue "
                "volviendo semanas después: es lo que de verdad ha entrado en su "
                "gusto, más fuerte que cualquier veredicto en caliente. 'a medias' o 'sin tocar' "
                "no es un veredicto: pregúntale solo si viene a cuento. Si da su "
                "opinión, guárdala con rate.")}
