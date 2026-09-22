"""Diagnóstico de las fuentes gratuitas: KEXP, ListenBrainz, MusicBrainz,
Last.fm, Wikipedia y los feeds de prensa.

Ninguna necesita cuota de Spotify, así que se puede ejecutar cuando quieras.
Dice cuáles responden y con qué pinta vienen los datos.

    .venv\\Scripts\\activate
    python scripts/diag_fuentes.py > diag_fuentes.txt 2>&1
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from app.clients.kexp import KexpClient  # noqa: E402
from app.clients.lastfm import LastfmClient  # noqa: E402
from app.clients.listenbrainz import ListenbrainzClient  # noqa: E402
from app.clients.musicbrainz import MusicbrainzClient  # noqa: E402
from app.clients.press import PressClient  # noqa: E402
from app.clients.statsfm import StatsfmClient  # noqa: E402
from app.clients.wikipedia import WikipediaClient  # noqa: E402


def seccion(titulo):
    print("\n" + "=" * 68 + f"\n{titulo}\n" + "=" * 68)


def muestra(etiqueta, valor, n=3):
    if not valor:
        print(f"  ⚠ {etiqueta}: VACÍO")
        return
    if isinstance(valor, list):
        print(f"  ✓ {etiqueta}: {len(valor)} elementos")
        for v in valor[:n]:
            print(f"      {v}")
    else:
        print(f"  ✓ {etiqueta}: {str(valor)[:300]}")


def main():
    seccion("KEXP — qué pincha una radio con criterio")
    k = KexpClient()
    muestra("emisiones últimas 48 h", k.plays(limit=5, desde_dias=2))
    muestra("artistas más pinchados (7 días)",
            k.artistas_mas_pinchados(desde_dias=7, muestras=200), 5)
    muestra("emisiones de Fontaines D.C.", k.emisiones_de("Fontaines D.C."), 2)

    seccion("ListenBrainz — novedades y similares")
    lb = ListenbrainzClient()
    muestra("novedades (21 días)", lb.novedades(21), 5)
    mb = MusicbrainzClient()
    ficha = mb.find_artist("Fontaines D.C.")
    muestra("ficha MusicBrainz", ficha)
    if ficha:
        muestra("similares por co-escucha", lb.similares(ficha["mbid"]), 5)

    seccion("MusicBrainz — sellos")
    muestra("ficha del sello Speedy Wunderground", mb.buscar_sello("Speedy Wunderground"))
    cat = mb.catalogo_sello("Speedy Wunderground")
    muestra("catálogo del sello", cat.get("publicaciones") if isinstance(cat, dict) else None, 5)
    muestra("sellos de Fontaines D.C.", mb.sellos_de("Fontaines D.C."))
    muestra("novedades de Wet Leg desde 2025", mb.recent_by_artist("Wet Leg", "2025-01-01"))

    seccion("Last.fm — etiquetas y audiencia")
    lf = LastfmClient(os.getenv("LASTFM_API_KEY", ""), os.getenv("LASTFM_USERNAME"))
    muestra("info de etiqueta 'crank wave'", lf.tag_info("crank wave"))
    muestra("artistas de 'post-punk' (página 3)", lf.tag_top_artists("post-punk", 10, 3), 5)
    muestra("audiencia de Gurriers", lf.artist_info("Gurriers"))

    seccion("stats.fm — tu historial")
    sf = StatsfmClient(os.getenv("STATSFM_USERNAME", ""))
    muestra("top artistas últimas semanas", sf.top_artists("weeks", 5), 5)

    seccion("Wikipedia")
    w = WikipediaClient()
    muestra("contexto de 'crank wave'", w.lookup("crank wave", "género musical"))
    muestra("contexto de Gurriers", w.lookup("Gurriers", "banda grupo musical"))

    seccion("Prensa (RSS)")
    res = PressClient().fetch(limit_per_source=2, since_days=30)
    print(f"  fuentes consultadas: {len(res['fuentes'])}")
    for aviso in res["warnings"]:
        print(f"  ⚠ {aviso}")
    muestra("artículos", [f"[{i['source']}] {i['title'][:60]}" for i in res["items"]], 6)

    print("\nListo. Pega la salida o dime que lea diag_fuentes.txt.")


if __name__ == "__main__":
    main()
