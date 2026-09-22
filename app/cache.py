"""Caché en disco: no volver a pagar por lo que ya sabemos.

Spotify en modo desarrollo tiene cuota por desarrollador, y reconstruir el
perfil de lo que el usuario conoce cuesta unas 30 peticiones. Guardarlo solo
en memoria significa pagarlas otra vez en cada reinicio del servidor MCP —y
el servidor se reinicia cada vez que se toca el código—. Esto lo persiste en
datos/cache.json con caducidad por entrada.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("playlist_lab.cache")
ARCHIVO = Path(__file__).resolve().parents[1] / "datos" / "cache.json"
_lock = threading.Lock()
_memoria: dict | None = None


def _leer() -> dict:
    global _memoria
    if _memoria is None:
        try:
            _memoria = json.loads(ARCHIVO.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _memoria = {}
    return _memoria


def _escribir(datos: dict) -> None:
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    temporal = ARCHIVO.with_suffix(".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(temporal, ARCHIVO)


def obtener(clave: str, ttl: float) -> tuple[bool, object]:
    """(hay_valor, valor). No devuelve nada si caducó."""
    with _lock:
        entrada = _leer().get(clave)
    if not entrada or time.time() - entrada.get("t", 0) > ttl:
        return False, None
    return True, entrada.get("v")


def guardar(clave: str, valor) -> None:
    with _lock:
        datos = _leer()
        datos[clave] = {"t": time.time(), "v": valor}
        try:
            _escribir(datos)
        except OSError as e:
            log.warning("No se pudo guardar la caché: %s", e)


def recordar(clave: str, ttl: float, fn):
    """Devuelve lo cacheado o calcula, guarda y devuelve."""
    hay, valor = obtener(clave, ttl)
    if hay:
        return valor
    valor = fn()
    guardar(clave, valor)
    return valor


def olvidar(clave: str) -> None:
    with _lock:
        datos = _leer()
        if datos.pop(clave, None) is not None:
            try:
                _escribir(datos)
            except OSError:
                pass


def estado() -> dict:
    with _lock:
        datos = _leer()
    ahora = time.time()
    return {clave: f"hace {round((ahora - e.get('t', 0)) / 60)} min"
            for clave, e in datos.items()}
