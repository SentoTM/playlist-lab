"""Semillas: una pieza por lista que apunta hacia otro sitio.

La idea (acordada con él): nada de currículo. El gusto crece siguiendo sus
ganas; el sistema planta semillas y mira cuáles prenden. Una semilla es un
disco o canción de una lista que abre un HILO fuera de lo que pidió ("del
post-punk al afrobeat vía ESG"). La huella dice si prendió (volvió, guardó,
tiró del hilo) o si arraigó (sigue ahí semanas después). Las que prenden se
riegan: la siguiente tanda tira de ese hilo. Las que no, se secan sin
insistir. No es un veredicto: a lo mejor no era el momento.
"""
import datetime as dt
import json
import threading
from pathlib import Path

from .text import des_escapar, norm

RUTA = Path(__file__).resolve().parent.parent / "datos" / "semillas.json"
SECA_TRAS_DIAS = 21
_lock = threading.Lock()


def cargar() -> list[dict]:
    try:
        return json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar(datos: list[dict]) -> None:
    RUTA.parent.mkdir(exist_ok=True)
    RUTA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def plantar(lista: str, pieza: str, hilo: str) -> dict:
    """pieza: 'album: Artista – Álbum', 'Artista – Canción' o 'Artista'."""
    p = pieza.strip()
    es_album = p.lower().startswith(("album:", "álbum:"))
    texto = p.split(":", 1)[1].strip() if es_album else p
    for sep in (" – ", " — ", " - "):
        if sep in texto:
            artista, obra = [x.strip() for x in texto.split(sep, 1)]
            break
    else:
        artista, obra = texto, ""
    semilla = {"lista": des_escapar(lista), "fecha": dt.date.today().isoformat(),
               "artista": des_escapar(artista), "obra": des_escapar(obra),
               "tipo": "album" if es_album else ("cancion" if obra else "artista"),
               "hilo": des_escapar(hilo), "estado": "abierta", "senales": None}
    with _lock:
        datos = cargar()
        datos.append(semilla)
        _guardar(datos)
    return semilla


def actualizar(huella_listas: dict, hoy: dt.date | None = None) -> list[dict]:
    """Cruza las semillas con la huella y actualiza su estado."""
    hoy = hoy or dt.date.today()
    with _lock:
        datos = cargar()
        for s in datos:
            if s["estado"] in ("arraigó", "descartada"):
                continue
            vieja = (hoy - dt.date.fromisoformat(s["fecha"])).days >= SECA_TRAS_DIAS
            lista = huella_listas.get(s["lista"]) or {}
            fila = next((e for e in lista.get("elementos", [])
                         if norm(e.get("artista") or "") == norm(s["artista"])), None)
            if not fila:
                if vieja:     # lista borrada o fuera de la huella: no se riega
                    s["estado"] = "seca"
                continue
            s["senales"] = fila.get("senales")
            s["estado_escucha"] = fila.get("estado")
            if fila.get("arraigo"):
                s["estado"] = "arraigó"
            elif fila.get("prendio"):
                s["estado"] = "prendió"
            elif vieja:
                s["estado"] = "seca"
        _guardar(datos)
    return datos


def resumen(datos: list[dict]) -> dict:
    por_estado: dict[str, list] = {}
    for s in datos:
        por_estado.setdefault(s["estado"], []).append(
            {k: s.get(k) for k in ("artista", "obra", "hilo", "lista", "fecha",
                                   "estado_escucha", "senales")})
    return {
        "para_regar": (por_estado.get("arraigó", []) + por_estado.get("prendió", [])) or None,
        "abiertas": por_estado.get("abierta") or None,
        "secas": [f"{s['artista']} ({s['hilo']})" for s in por_estado.get("seca", [])] or None,
        "como_usarlo": (
            "PARA_REGAR: semillas que prendieron o arraigaron. En la próxima tanda "
            "tira de ESE HILO (no repitas el disco: da el siguiente paso del camino) "
            "y dile de qué semilla viene. ABIERTAS: aún sin señales, no insistas. "
            "SECAS: no prendieron en 3 semanas; no es un no, pero no las riegues. "
            "Planta una semilla nueva en cada lista con create_playlist(semilla=…, hilo=…)."),
    }
