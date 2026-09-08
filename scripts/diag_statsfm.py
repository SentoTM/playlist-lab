"""Diagnóstico de la API interna de stats.fm.

No depende de nada fuera de la librería estándar: puedes ejecutarlo con
cualquier Python 3.10+ sin activar el venv.

    python scripts/diag_statsfm.py                 # usa STATSFM_USERNAME de .env
    python scripts/diag_statsfm.py mi_usuario      # o pásalo por argumento

Llama a los endpoints que usa app/clients/statsfm.py, muestra el código HTTP,
un extracto de la respuesta y lo que el cliente extraería de ella. Pega la
salida completa en el chat para ajustar el cliente.
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.stats.fm/api/v1"
HEADERS = {"User-Agent": "playlist-lab/0.1 (uso personal)", "Accept": "application/json"}


def username_from_env() -> str:
    env = Path(__file__).resolve().parents[1] / ".env"
    if not env.exists():
        return ""
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("STATSFM_USERNAME="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def get(path: str, **params):
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        status = e.code
    except Exception as e:  # red, DNS, timeout...
        print(f"  GET {url}\n  ERROR de red: {e!r}")
        return None, None
    try:
        data = json.loads(body)
    except ValueError:
        data = body
    print(f"  GET {url}\n  HTTP {status}")
    return status, data


def excerpt(data, limit=900) -> str:
    text = json.dumps(data, ensure_ascii=False, indent=1) if not isinstance(data, str) else data
    return text if len(text) <= limit else text[:limit] + f"\n  ... ({len(text)} chars en total)"


def section(title: str):
    print("\n" + "=" * 70 + f"\n{title}\n" + "=" * 70)


def main():
    user = sys.argv[1] if len(sys.argv) > 1 else username_from_env()
    if not user:
        raise SystemExit("Indica el usuario: python scripts/diag_statsfm.py <usuario>")
    print(f"Usuario stats.fm: {user}")

    section("1. Perfil (comprueba que existe y cómo se identifica)")
    status, data = get(f"/users/{user}")
    print(excerpt(data))
    if status == 200 and isinstance(data, dict):
        item = data.get("item") or {}
        print(f"\n  -> id interno: {item.get('id')} | customId: {item.get('customId')} "
              f"| displayName: {item.get('displayName')}")

    section("2. Privacidad (qué partes del perfil son públicas)")
    status, data = get(f"/users/{user}/privacy")
    print(excerpt(data))

    section("3. Top tracks lifetime (lo que usa el motor de redescubrimiento)")
    for params in ({"range": "lifetime", "limit": 5},
                   {"timeRange": "lifetime", "limit": 5},
                   {"range": "lifetime"}):
        status, data = get(f"/users/{user}/top/tracks", **params)
        if status == 200:
            break
        print(excerpt(data, 300))
    if status == 200 and isinstance(data, dict):
        items = data.get("items") or []
        print(f"  items devueltos: {len(items)}")
        if items:
            print("  primer item completo:")
            print(excerpt(items[0], 1500))
            print("\n  -> lo que extraería el cliente:")
            for it in items:
                tr = it.get("track") or {}
                arts = tr.get("artists") or []
                ext = tr.get("externalIds") or {}
                print(f"     {tr.get('name')!r} — {arts[0].get('name') if arts else None!r} "
                      f"| spotify: {(ext.get('spotify') or [None])[0]} "
                      f"| streams: {it.get('streams')} | playedMs: {it.get('playedMs')}")
    else:
        print(excerpt(data))

    section("4. Top artists lifetime (motor + filtro de 'artistas conocidos')")
    status, data = get(f"/users/{user}/top/artists", range="lifetime", limit=5)
    if status == 200 and isinstance(data, dict):
        items = data.get("items") or []
        print(f"  items devueltos: {len(items)}")
        if items:
            print(excerpt(items[0], 1000))
            print("\n  -> lo que extraería el cliente:")
            for it in items:
                ar = it.get("artist") or {}
                print(f"     {ar.get('name')!r} | streams: {it.get('streams')} "
                      f"| playedMs: {it.get('playedMs')}")
    else:
        print(excerpt(data))

    section("5. Límite alto (el selector pide 200 artistas y el motor 150 tracks)")
    status, data = get(f"/users/{user}/top/artists", range="lifetime", limit=200)
    if status == 200 and isinstance(data, dict):
        print(f"  artistas devueltos con limit=200: {len(data.get('items') or [])}")
    status, data = get(f"/users/{user}/top/tracks", range="lifetime", limit=150)
    if status == 200 and isinstance(data, dict):
        print(f"  tracks devueltos con limit=150: {len(data.get('items') or [])}")

    section("6. Otros rangos (por si queremos 'lo que ya no escuchas' más fino)")
    for r in ("weeks", "months"):
        status, data = get(f"/users/{user}/top/tracks", range=r, limit=3)
        if status == 200 and isinstance(data, dict):
            print(f"  range={r}: {len(data.get('items') or [])} items")

    print("\nListo. Pega toda esta salida en el chat.")


if __name__ == "__main__":
    main()
