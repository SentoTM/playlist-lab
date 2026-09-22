"""Tus opiniones: lo que la app no puede deducir de tus escuchas.

Los datos de Spotify dicen qué has escuchado, no qué te pareció. Un disco
que pusiste una vez y odiaste y otro que no has vuelto a poner porque te lo
sabes de memoria se ven exactamente igual desde fuera. Esto guarda el juicio
que solo tú puedes dar, para que no se pierda al cerrar la conversación y
para que no te vuelvan a proponer lo mismo.

Se guarda en datos/notas.json (fuera de git: es tuyo). Escritura atómica,
porque el servidor MCP puede estar atendiendo varias cosas a la vez.
"""
import datetime as dt
import json
import os
import threading
from pathlib import Path

from .text import norm

ARCHIVO = Path(__file__).resolve().parents[1] / "datos" / "notas.json"
_lock = threading.Lock()

# Los veredictos son los suyos, no una escala genérica: para él una
# recomendación NO fracasa por no gustarle, así que "sin pena ni gloria" y
# "no es para mí pero lo entiendo" no descartan nada — siguen siendo
# candidatos a una segunda escucha.
VEREDICTOS = {
    "me encanta": "favorito; profundizar en esa dirección y usarlo de referencia",
    "me gusta": "buena dirección",
    "sin pena ni gloria": "no le atravesó; no es mala música, cabe revisitarlo",
    "no es para mí pero lo entiendo": ("no le gusta pero entiende por qué importa; "
                                       "para él esto es un éxito, no un fallo"),
    "no es lo mío": "evitar salvo que el encargo lo pida expresamente",
    "nunca más": "vetado: no proponer jamás",
    "pendiente": "quiere escucharlo, aún sin juicio",
    "escuchado": "ya lo ha escuchado; no ofrecerlo como novedad",
}
VETOS = {"nunca más"}                 # veto duro
EVITAR = {"no es lo mío"}             # evitar, pero no es un veto absoluto
YA_VISTOS = VETOS | EVITAR | {"escuchado"}


def _vacio() -> dict:
    return {"artistas": {}, "albumes": {}, "generales": []}


def cargar() -> dict:
    if not ARCHIVO.exists():
        return _vacio()
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _vacio()
    for clave, defecto in (("artistas", {}), ("albumes", {}), ("generales", [])):
        datos.setdefault(clave, defecto)
    return datos


def _guardar(datos: dict) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    temporal = ARCHIVO.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    os.replace(temporal, ARCHIVO)


def _clave_album(artista: str, album: str) -> str:
    return f"{norm(artista)}::{norm(album)}"


def anotar(tipo: str, sujeto: str, veredicto: str = "", nota: str = "",
           album: str = "") -> dict:
    """Guarda una opinión. tipo: artista | album | general.

    Vuelve a escribir sobre la anterior si ya había una del mismo sujeto,
    conservando la fecha en que se dijo por primera vez.
    """
    if veredicto and veredicto not in VEREDICTOS:
        raise ValueError(f"Veredicto no válido: {veredicto!r}. "
                         f"Usa uno de: {', '.join(VEREDICTOS)}")
    hoy = dt.date.today().isoformat()
    with _lock:
        datos = cargar()
        if tipo == "general":
            datos["generales"].append({"nota": nota or sujeto, "fecha": hoy})
            entrada = datos["generales"][-1]
        else:
            if tipo == "album":
                clave = _clave_album(sujeto, album)
                base = {"artista": sujeto, "album": album}
                coleccion = datos["albumes"]
            else:
                clave = norm(sujeto)
                base = {"artista": sujeto}
                coleccion = datos["artistas"]
            anterior = coleccion.get(clave, {})
            entrada = {**base,
                       "veredicto": veredicto or anterior.get("veredicto", ""),
                       "nota": nota or anterior.get("nota", ""),
                       "desde": anterior.get("desde", hoy),
                       "actualizado": hoy}
            coleccion[clave] = entrada
        _guardar(datos)
    return entrada


def olvidar(tipo: str, sujeto: str, album: str = "") -> bool:
    """Borra una nota. Devuelve si había algo que borrar."""
    with _lock:
        datos = cargar()
        coleccion = datos["albumes"] if tipo == "album" else datos["artistas"]
        clave = _clave_album(sujeto, album) if tipo == "album" else norm(sujeto)
        existia = coleccion.pop(clave, None) is not None
        if existia:
            _guardar(datos)
    return existia


def listar() -> dict:
    """Todas las notas, agrupadas por veredicto para leerlas de un vistazo."""
    datos = cargar()
    por_veredicto: dict[str, list] = {}
    for entrada in datos["artistas"].values():
        por_veredicto.setdefault(entrada.get("veredicto") or "sin veredicto",
                                 []).append(entrada)
    return {
        "artistas_por_veredicto": por_veredicto,
        "albumes": list(datos["albumes"].values()),
        "notas_generales": datos["generales"],
        "total": (len(datos["artistas"]) + len(datos["albumes"])
                  + len(datos["generales"])),
    }


def para(nombres: list[str]) -> dict[str, dict]:
    """Notas de unos artistas concretos (clave: el nombre tal cual se pidió)."""
    datos = cargar()["artistas"]
    return {n: datos[norm(n)] for n in nombres if norm(n) in datos}


def vetados() -> dict[str, str]:
    """Artistas que no deben salir en descubrimiento: {clave: veredicto}.

    Incluye los vetados y los evitados, pero NO los que simplemente no le
    llegaron: esos siguen siendo candidatos a una segunda escucha.
    """
    datos = cargar()["artistas"]
    return {k: v["veredicto"] for k, v in datos.items()
            if v.get("veredicto") in (VETOS | EVITAR)}


def albumes_escuchados() -> set[str]:
    """Álbumes que ya ha escuchado (clave normalizada artista::album)."""
    datos = cargar()["albumes"]
    return {k for k, v in datos.items()
            if v.get("veredicto") and v["veredicto"] != "pendiente"}
