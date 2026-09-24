"""Sube tus datos locales (notas, historial, radar, token de Spotify…) al
servidor de Railway, o baja una copia de lo que hay allí.

    python scripts/subir_datos.py            # sube todo
    python scripts/subir_datos.py --bajar    # baja datos.zip (copia de seguridad)

Lee PLAYLIST_LAB_URL y ADMIN_TOKEN del .env.
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[1]
load_dotenv(RAIZ / ".env")
URL = (os.getenv("PLAYLIST_LAB_URL") or "").rstrip("/")
TOKEN = os.getenv("ADMIN_TOKEN") or ""
FICHEROS = ["notas.json", "perfil.md", "cache.json", "prensa.json", "radar.json",
            "seguimiento.json", "propuestos.json", "listas.json", "scrobbles.json"]

if not URL or not TOKEN:
    sys.exit("Falta PLAYLIST_LAB_URL o ADMIN_TOKEN en el .env")
cabeceras = {"Authorization": f"Bearer {TOKEN}"}

if "--bajar" in sys.argv:
    r = httpx.get(f"{URL}/admin/copia", headers=cabeceras, timeout=60)
    r.raise_for_status()
    destino = RAIZ / "datos_servidor.zip"
    destino.write_bytes(r.content)
    print(f"Copia guardada en {destino}")
    sys.exit(0)

subidos = 0
for nombre in FICHEROS + ["token.json"]:
    ruta = RAIZ / ("token.json" if nombre == "token.json" else f"datos/{nombre}")
    if not ruta.exists():
        print(f"  (no hay {nombre}, se salta)")
        continue
    r = httpx.put(f"{URL}/admin/datos/{nombre}", content=ruta.read_bytes(),
                  headers=cabeceras, timeout=120)
    if r.status_code != 200:
        print(f"  ERROR con {nombre}: {r.status_code} {r.text[:200]}")
        continue
    print(f"  subido {nombre} ({r.json()['bytes']:,} bytes)")
    subidos += 1
print(f"Hecho: {subidos} ficheros en {URL}")
