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
from collections import Counter

from .text import des_escapar, norm

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
    lista = des_escapar(lista)
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


def revisar(resueltos: list[dict]) -> dict:
    """Revisión final de una lista ya resuelta, antes de crearla.

    Es el único punto por el que pasa toda lista (resolve y create_playlist),
    así que aquí se comprueba lo que vet_candidates comprobaría si el modelo
    se lo ha saltado: artistas repetidos, ya propuestos antes y concentración
    en una misma década. Sin peticiones extra: usa lo que ya devolvió Spotify.
    """
    artistas = [r.get("artist") for r in resueltos if r.get("artist")]
    n = len(artistas)
    repetidos = [a for a, v in Counter(artistas).items() if v > 1]
    ya = {a: listas_de(a)[:3] for a in dict.fromkeys(artistas) if listas_de(a)}
    decadas = Counter(f"{r['year'][:3]}0s" for r in resueltos
                      if (r.get("year") or "")[:4].isdigit())
    avisos = []
    if repetidos:
        avisos.append("Artistas repetidos en la lista: " + ", ".join(repetidos))
    if ya:
        avisos.append(f"{len(ya)} de {len(set(artistas))} artistas ya te los propuse en otras "
                      "listas: ¿es a propósito o estás tirando de lo de siempre?")
    if n >= 5 and decadas:
        dec, veces = decadas.most_common(1)[0]
        if veces / n >= 0.6:
            avisos.append(f"{veces} de {n} son de los {dec}; si no lo pidió, abre el abanico")
    return {"ya_propuestos": ya or None, "decadas": dict(sorted(decadas.items())),
            "avisos": avisos or None}
