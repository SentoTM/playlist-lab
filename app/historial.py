"""Historial de lo ya propuesto: memoria contra los atractores.

Por qué existe: un modelo tiende a volver a los mismos nombres (los más
citados de cada escena). Sin memoria de lo que ya propuso, cada
conversación empieza de cero y los repite. Aquí queda qué artistas han
entrado en qué listas, para que vet_candidates lo avise.
"""
import datetime as dt
import json
import threading
from pathlib import Path

from . import notes
from .text import norm

RUTA = Path(__file__).resolve().parent.parent / "datos" / "propuestos.json"
_lock = threading.Lock()


def cargar() -> dict:
    if not RUTA.exists():
        return {}
    try:
        return json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def registrar(artistas: list[str], lista: str) -> None:
    hoy = dt.date.today().isoformat()
    with _lock:
        datos = cargar()
        for a in dict.fromkeys(artistas):
            if not a:
                continue
            fila = datos.setdefault(norm(a), {"artista": a, "listas": []})
            if not any(l["nombre"] == lista for l in fila["listas"]):
                fila["listas"].append({"nombre": lista, "fecha": hoy})
        RUTA.parent.mkdir(exist_ok=True)
        RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=1),
                        encoding="utf-8")


def listas_de(nombre: str) -> list[str]:
    """Listas en las que ya entró este artista (historial + notas antiguas)."""
    fila = cargar().get(norm(nombre)) or {}
    listas = [l["nombre"] for l in fila.get("listas", [])]
    # Las listas anteriores a este historial están en las notas ("En la lista «X»")
    for v in notes.cargar().get("albumes", {}).values():
        nota = v.get("nota") or ""
        if norm(v.get("artista") or "") == norm(nombre) and "«" in nota:
            nombre_lista = nota.split("«", 1)[1].split("»", 1)[0]
            if nombre_lista not in listas:
                listas.append(nombre_lista)
    return listas
