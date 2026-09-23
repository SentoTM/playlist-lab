"""Lo que el usuario quiere vigilar: sellos y artistas.

Un sello es un filtro de gusto humano y en el indie las escenas se organizan
por sello, así que seguir unos cuantos es la forma más barata de enterarse de
lo nuevo con criterio. Vive en datos/seguimiento.json, editable a mano.
"""
import json
import os
import threading
from pathlib import Path

ARCHIVO = Path(__file__).resolve().parents[1] / "datos" / "seguimiento.json"
_lock = threading.Lock()

# Punto de partida razonable para su gusto; él lo ajusta cuando quiera.
INICIAL = {
    "sellos": [
        "Speedy Wunderground", "Nice Swan Records", "Partisan Records",
        "Rough Trade Records", "Sub Pop", "Dirty Hit", "Heavenly Recordings",
        "Elefant Records", "Subterfuge Records", "Sonido Muchacho",
    ],
    "artistas": [],
    # Etiquetas que el radar recorre además de los géneros que salen de tu
    # historial (que vienen casi todos en inglés y dejaban corto el
    # castellano). Nombres de etiqueta tal como se usan en Last.fm.
    "etiquetas": ["spanish indie", "indie español", "rock en español",
                  "spanish punk", "latin indie"],
    "nota": ("Sellos, artistas y etiquetas que el radar vigila. Añade o "
             "quita con follow/unfollow o editando este fichero."),
}


def cargar() -> dict:
    if not ARCHIVO.exists():
        return dict(INICIAL)
    try:
        datos = json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(INICIAL)
    datos.setdefault("sellos", [])
    datos.setdefault("artistas", [])
    datos.setdefault("etiquetas", list(INICIAL["etiquetas"]))
    return datos


def _guardar(datos: dict) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, ARCHIVO)


def _clave(tipo: str) -> str:
    if tipo.startswith("sello"):
        return "sellos"
    if tipo.startswith("etiqueta") or tipo.startswith("genero") or tipo.startswith("género"):
        return "etiquetas"
    return "artistas"


def seguir(tipo: str, nombre: str) -> dict:
    clave = _clave(tipo)
    with _lock:
        datos = cargar()
        if nombre.lower() not in (n.lower() for n in datos[clave]):
            datos[clave].append(nombre)
            _guardar(datos)
    return datos


def dejar(tipo: str, nombre: str) -> dict:
    clave = _clave(tipo)
    with _lock:
        datos = cargar()
        datos[clave] = [n for n in datos[clave] if n.lower() != nombre.lower()]
        _guardar(datos)
    return datos
