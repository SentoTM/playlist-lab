"""Trabajos en segundo plano para las consultas que no caben en una llamada.

Algunas herramientas (novedades de la órbita, emergentes) hacen cientos de
peticiones y tardan más de lo que aguanta el cliente MCP, que corta al
minuto. En vez de recortar la calidad, el trabajo se lanza en un hilo y la
herramienta espera un rato; si no ha terminado, responde "sigo en ello" y
la siguiente llamada idéntica recoge el resultado ya hecho.

La clave identifica el trabajo, así que dos llamadas con los mismos
parámetros comparten el mismo cálculo en vez de duplicarlo.
"""
import logging
import threading
import time

log = logging.getLogger("playlist_lab.jobs")

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
TTL = 1800  # media hora: un resultado más viejo se recalcula


def _estado_publico(key: str, job: dict, esperado: float) -> dict:
    if job["estado"] == "listo":
        out = dict(job["resultado"]) if isinstance(job["resultado"], dict) \
            else {"resultado": job["resultado"]}
        out["calculado_en_segundos"] = round(job["terminado"] - job["iniciado"], 1)
        return out
    if job["estado"] == "error":
        return {"error": job["error"],
                "nota": "El cálculo falló; revisa la configuración o reintenta."}
    return {
        "estado": "en_curso",
        "segundos_transcurridos": round(time.time() - job["iniciado"]),
        "vuelve_a_llamar": True,
        "nota": (f"Sigo reuniendo los datos (llevo {esperado:.0f} s esperando). "
                 "Vuelve a llamar a esta misma herramienta con los MISMOS "
                 "parámetros dentro de un momento: el trabajo continúa y la "
                 "próxima llamada devolverá el resultado."),
    }


def run_or_wait(key: str, fn, wait_seconds: float = 40.0) -> dict:
    """Devuelve el resultado, o "en curso" si aún no está listo."""
    ahora = time.time()
    with _lock:
        job = _jobs.get(key)
        if job and job["estado"] == "listo" and ahora - job["terminado"] > TTL:
            job = None  # caducado
        if job is None:
            job = {"estado": "en_curso", "iniciado": ahora,
                   "terminado": None, "resultado": None, "error": None}
            _jobs[key] = job
            arrancar = True
        else:
            arrancar = False

    if arrancar:
        def _run():
            try:
                resultado = fn()
                with _lock:
                    job.update(estado="listo", resultado=resultado,
                               terminado=time.time())
            except Exception as e:  # noqa: BLE001
                log.exception("Trabajo %s falló", key)
                with _lock:
                    job.update(estado="error", error=f"{type(e).__name__}: {e}",
                               terminado=time.time())
        threading.Thread(target=_run, daemon=True, name=f"job:{key}").start()

    limite = time.time() + wait_seconds
    while time.time() < limite:
        with _lock:
            if job["estado"] != "en_curso":
                break
        time.sleep(0.5)

    with _lock:
        return _estado_publico(key, job, time.time() - job["iniciado"])
