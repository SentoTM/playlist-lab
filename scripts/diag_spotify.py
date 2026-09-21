"""Diagnóstico de los endpoints de Spotify con tu token real.

Spotify ha ido cerrando endpoints a las apps nuevas y no lo documenta bien;
esto prueba uno a uno los que usa Playlist Lab y muestra el código y el
mensaje exacto, para saber qué sigue vivo y con qué parámetros.

    .venv\\Scripts\\activate
    python scripts/diag_spotify.py > diag_spotify.txt 2>&1
"""
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.clients.spotify import SpotifyClient  # noqa: E402

API = "https://api.spotify.com/v1"


def main():
    import os
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    sp = SpotifyClient(os.getenv("SPOTIFY_CLIENT_ID", ""),
                       "http://127.0.0.1:8888/callback")
    if not sp.authenticated:
        raise SystemExit("Sin sesión: arranca setup.bat y haz login primero.")

    sp._request("GET", "/me")  # fuerza refresco si hace falta
    token = sp._token["access_token"]
    http = httpx.Client(timeout=20,
                        headers={"Authorization": f"Bearer {token}"})

    me = http.get(f"{API}/me").json()
    country = me.get("country") or "ES"
    print(f"Usuario: {me.get('display_name')} | país: {country} | "
          f"producto: {me.get('product')}")
    print(f"Scopes del token: {sp._token.get('scope', '(no guardado)')}\n")

    # id de un artista conocido para las pruebas
    r = http.get(f"{API}/search", params={"q": "Fontaines D.C.", "type": "artist",
                                          "limit": 1}).json()
    artist_id = r["artists"]["items"][0]["id"]
    print(f"Artista de prueba: {artist_id} (Fontaines D.C.)\n")

    pruebas = [
        ("albums sin parámetros", f"/artists/{artist_id}/albums", {}),
        ("albums limit", f"/artists/{artist_id}/albums", {"limit": 20}),
        ("albums include_groups=album", f"/artists/{artist_id}/albums",
         {"include_groups": "album"}),
        ("albums include_groups=album,single", f"/artists/{artist_id}/albums",
         {"include_groups": "album,single"}),
        ("albums market=from_token", f"/artists/{artist_id}/albums",
         {"market": "from_token"}),
        (f"albums market={country}", f"/artists/{artist_id}/albums",
         {"market": country, "include_groups": "album,single", "limit": 20}),
        ("top-tracks from_token", f"/artists/{artist_id}/top-tracks",
         {"market": "from_token"}),
        (f"top-tracks market={country}", f"/artists/{artist_id}/top-tracks",
         {"market": country}),
        ("varios artistas (popularity)", "/artists", {"ids": artist_id}),
        ("new-releases", "/browse/new-releases", {"limit": 5}),
        (f"new-releases country={country}", "/browse/new-releases",
         {"limit": 5, "country": country}),
        ("me/following (artistas seguidos)", "/me/following",
         {"type": "artist", "limit": 5}),
        ("me/player/currently-playing", "/me/player/currently-playing", {}),
        ("me/albums (guardados)", "/me/albums", {"limit": 2}),
        ("me/playlists", "/me/playlists", {"limit": 2}),
    ]

    for nombre, path, params in pruebas:
        try:
            resp = http.get(f"{API}{path}", params=params)
        except httpx.HTTPError as e:
            print(f"  {nombre:36} ERROR de red: {e}")
            continue
        estado = resp.status_code
        detalle = ""
        if estado == 200:
            try:
                data = resp.json()
            except ValueError:
                data = {}
            if isinstance(data, dict):
                for clave in ("items", "tracks", "artists", "albums"):
                    v = data.get(clave)
                    if isinstance(v, list):
                        detalle = f"{len(v)} elementos"
                        break
                    if isinstance(v, dict) and isinstance(v.get("items"), list):
                        detalle = f"{len(v['items'])} elementos"
                        break
                if not detalle and data:
                    detalle = "respuesta ok"
                if path == "/artists" and data.get("artists"):
                    a = data["artists"][0]
                    detalle += (f" | popularity={a.get('popularity')} "
                                f"genres={a.get('genres')}")
            elif estado == 204:
                detalle = "sin contenido"
        else:
            try:
                detalle = json.dumps(resp.json().get("error", {}), ensure_ascii=False)
            except ValueError:
                detalle = resp.text[:160]
        print(f"  {nombre:36} {estado}  {detalle}")

    print("\nListo. Si generaste diag_spotify.txt, avísame y lo leo yo.")


if __name__ == "__main__":
    main()
