"""Diagnóstico de las fuentes gratuitas: KEXP, ListenBrainz, MusicBrainz,
Last.fm, stats.fm, Wikipedia y los feeds de prensa.

Ninguna gasta cuota de Spotify, así que se puede ejecutar cuando quieras.

Enseña el progreso en pantalla según avanza y a la vez lo guarda en
diag_fuentes.txt. Algunas fuentes son lentas a propósito (MusicBrainz solo
admite una petición por segundo), así que tarda un par de minutos: si ves
que avanza, no está colgado.

    .venv\\Scripts\\activate
    python scripts/diag_fuentes.py
"""
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# La consola de Windows no siempre sabe UTF-8: que no reviente por un acento
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

SALIDA = ROOT / "diag_fuentes.txt"
_log = open(SALIDA, "w", encoding="utf-8")
T0 = time.time()


def out(texto: str = "") -> None:
    """A pantalla y a fichero, sin búfer: si se corta, lo hecho queda."""
    print(texto, flush=True)
    _log.write(texto + "\n")
    _log.flush()


def seccion(titulo: str) -> None:
    out("\n" + "=" * 68)
    out(f"{titulo}   [{time.time() - T0:5.0f} s]")
    out("=" * 68)


def prueba(etiqueta: str, fn, n: int = 3) -> None:
    """Ejecuta una comprobación, mide lo que tarda y nunca corta el resto."""
    out(f"  ... {etiqueta}")
    t = time.time()
    try:
        valor = fn()
    except Exception as e:  # noqa: BLE001
        out(f"  [ERROR] {etiqueta}: {type(e).__name__}: {e}")
        out("          " + traceback.format_exc().strip().splitlines()[-1])
        return
    dur = time.time() - t
    if not valor:
        out(f"  [VACIO] {etiqueta} ({dur:.1f} s)")
        return
    if isinstance(valor, list):
        out(f"  [OK]    {etiqueta}: {len(valor)} elementos ({dur:.1f} s)")
        for v in valor[:n]:
            out(f"            {str(v)[:220]}")
    else:
        out(f"  [OK]    {etiqueta} ({dur:.1f} s): {str(valor)[:300]}")


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    from app.clients.kexp import KexpClient
    from app.clients.lastfm import LastfmClient
    from app.clients.listenbrainz import ListenbrainzClient
    from app.clients.musicbrainz import MusicbrainzClient
    from app.clients.press import PressClient
    from app.clients.statsfm import StatsfmClient
    from app.clients.wikipedia import WikipediaClient

    out(f"Diagnóstico de fuentes gratuitas — {time.strftime('%Y-%m-%d %H:%M')}")
    out("Tarda un par de minutos. Mientras veas '...' avanzar, está trabajando.")

    seccion("1. KEXP — qué pincha una radio con criterio")
    k = KexpClient()
    prueba("emisiones de las últimas 48 h", lambda: k.plays(limit=5, desde_dias=2))
    prueba("artistas más pinchados esta semana",
           lambda: k.artistas_mas_pinchados(desde_dias=7, muestras=100), 5)
    prueba("emisiones de Fontaines D.C. (último año)",
           lambda: k.emisiones_de("Fontaines D.C."), 2)

    seccion("2. ListenBrainz — novedades y similares")
    lb = ListenbrainzClient()
    prueba("novedades de las últimas 3 semanas", lambda: lb.novedades(21), 5)
    mb = MusicbrainzClient()
    ficha = {}

    def _ficha():
        ficha.update(mb.find_artist("Fontaines D.C.") or {})
        return ficha
    prueba("ficha de Fontaines D.C. en MusicBrainz", _ficha)
    if ficha.get("mbid"):
        prueba("similares por co-escucha", lambda: lb.similares(ficha["mbid"]), 5)

    seccion("3. MusicBrainz — sellos y novedades (1 petición/segundo)")
    prueba("ficha del sello Speedy Wunderground",
           lambda: mb.buscar_sello("Speedy Wunderground"))
    prueba("catálogo de Speedy Wunderground",
           lambda: (mb.catalogo_sello("Speedy Wunderground") or {}).get("publicaciones"), 5)
    prueba("sellos de Fontaines D.C.", lambda: mb.sellos_de("Fontaines D.C."))
    prueba("novedades de Wet Leg desde 2025",
           lambda: mb.recent_by_artist("Wet Leg", "2025-01-01"))

    seccion("4. Last.fm — etiquetas y audiencia")
    lf = LastfmClient(os.getenv("LASTFM_API_KEY", ""), os.getenv("LASTFM_USERNAME"))
    prueba("etiqueta 'crank wave'", lambda: lf.tag_info("crank wave"))
    prueba("artistas de 'post-punk' (página 3)",
           lambda: lf.tag_top_artists("post-punk", 10, 3), 5)
    prueba("audiencia de Gurriers", lambda: lf.artist_info("Gurriers"))

    seccion("5. stats.fm — tu historial")
    sf = StatsfmClient(os.getenv("STATSFM_USERNAME", ""))
    prueba("tus artistas de las últimas semanas",
           lambda: sf.top_artists("weeks", 5), 5)

    seccion("6. Wikipedia")
    w = WikipediaClient()
    prueba("contexto de 'crank wave'", lambda: w.lookup("crank wave", "género musical"))
    prueba("contexto de Gurriers", lambda: w.lookup("Gurriers", "banda grupo musical"))

    seccion("7. Prensa (RSS)")

    def _prensa():
        res = PressClient().fetch(limit_per_source=2, since_days=30)
        out(f"          fuentes consultadas: {len(res['fuentes'])}")
        for aviso in res["warnings"]:
            out(f"          [!] {aviso}")
        return [f"[{i['source']}] {i['title'][:60]}" for i in res["items"]]
    prueba("artículos del último mes", _prensa, 6)

    out(f"\nListo en {time.time() - T0:.0f} s. Resultado guardado en diag_fuentes.txt")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        out("\n[CORTADO] Interrumpido a mano; lo de arriba sí se completó.")
    finally:
        _log.close()
