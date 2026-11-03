"""Graba respuestas REALES de Deezer para la prueba de aceptación offline.

    python scripts/grabar_fixtures.py

Pide a Deezer (sin clave, sin Spotify) la búsqueda, la discografía y las
fichas de septiembre y octubre de 2026 de los artistas de la prueba de
aceptación, y las deja en tests/fixtures/deezer_real.json con el mismo
formato que deezer.json. Con ese archivo presente, los tests comprueban
también los filtros contra datos de verdad (TestAceptacionReal).
"""
import json
import sys
import time
from pathlib import Path

import httpx

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from app.text import clave  # noqa: E402

ARTISTAS = [
    "Arde Bogotá", "LA MILAGROSA", "Basht.", "Lori Meyers", "Fontaines D.C.", "La 126",
    "Viva Belgrado", "Niños", "Dummy", "Pardoner", "Gilla Band", "Gurriers", "Adult DVD",
    "Aiko el grupo", "Kasabian", "Bloc Party", "Protomartyr", "Amyl and The Sniffers",
    "Wet Leg", "Viagra Boys", "Squid", "IDLES",
]
MESES = ("2026-09", "2026-10")


def main() -> None:
    http = httpx.Client(timeout=20, headers={"User-Agent": "playlist-lab/0.3 (uso personal)"})
    salida: dict = {}

    def get(path: str, **params):
        time.sleep(0.15)   # muy por debajo de las 50 cada 5 s
        datos = http.get(f"https://api.deezer.com{path}", params=params).json()
        clave_fixture = f"{path}?q={params['q']}" if "q" in params else path
        salida[clave_fixture] = datos
        return datos

    for nombre in ARTISTAS:
        busqueda = get("/search/artist", q=nombre, limit=10)
        exactos = [a for a in busqueda.get("data") or [] if clave(a["name"]) == clave(nombre)]
        print(f"{nombre}: {len(exactos)} en Deezer con ese nombre")
        for a in exactos[:3]:
            discos = get(f"/artist/{a['id']}/albums", limit=50, index=0)
            for d in discos.get("data") or []:
                if (d.get("release_date") or "")[:7] in MESES:
                    get(f"/album/{d['id']}")
    destino = RAIZ / "tests" / "fixtures" / "deezer_real.json"
    destino.write_text(json.dumps(salida, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Guardado en {destino} ({len(salida)} respuestas)")


if __name__ == "__main__":
    main()
