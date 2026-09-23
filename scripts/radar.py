"""Pasa el radar de novedades y emergentes sin necesidad de Claude.

Pensado para programarlo (Programador de tareas de Windows, una vez por
semana): así, cuando pidas un menú, el radar ya está fresco.

    .venv\\Scripts\\activate
    python scripts/radar.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")

    from app import cache, radar, taste
    from app.clients.kexp import KexpClient
    from app.clients.lastfm import LastfmClient
    from app.clients.listenbrainz import ListenbrainzClient
    from app.clients.musicbrainz import MusicbrainzClient
    from app.clients.statsfm import StatsfmClient
    from app.notes import cargar as notas, vetados

    lf = LastfmClient(os.getenv("LASTFM_API_KEY", ""), os.getenv("LASTFM_USERNAME"))
    sf = StatsfmClient(os.getenv("STATSFM_USERNAME", "")) if os.getenv("STATSFM_USERNAME") else None
    t0 = time.time()

    def paso(texto):
        print(f"[{time.time() - t0:5.0f} s] {texto}", flush=True)

    paso("leyendo lo que ya conoces (sin tocar Spotify)")
    hay, conocidos = cache.obtener("known", 7 * 24 * 3600)
    if not hay:
        _, biblio = cache.obtener("biblioteca", 30 * 24 * 3600)
        conocidos = taste.known_artists(sf, lf, biblio or {})
    conocidos = dict(conocidos)
    artistas = notas()["artistas"]
    for clave in vetados():
        conocidos.setdefault(clave, {"artist": artistas[clave]["artista"]})

    datos = radar.actualizar(lf, MusicbrainzClient(), ListenbrainzClient(),
                             KexpClient(), sf, conocidos, paso)
    tri = [c for c in datos["candidatos"] if c.get("triangulado")]
    paso(f"hecho: {len(datos['candidatos'])} candidatos, {len(tri)} triangulados")
    print("\nLos diez mejores:")
    for c in datos["candidatos"][:10]:
        print(f"  {c['puntos']:5.1f}  {c['artist']:28} {', '.join(c['fuentes'])}")
    for f in datos.get("fallos_ultima_pasada") or []:
        print(f"  [!] {f}")


if __name__ == "__main__":
    main()
