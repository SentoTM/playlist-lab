"""Generación de las playlists diarias de álbumes (lunes a viernes).

Uso como CLI:
    python -m app.weekly preview            # los 5 álbumes de hoy, sin crear nada
    python -m app.weekly today              # crea la playlist de hoy
    python -m app.weekly week               # crea las 5 playlists de la próxima semana laboral
    python -m app.weekly week --start 2026-09-14 --dry-run
"""
import argparse
import datetime as dt
import json

from .albums.selector import AlbumPick, TasteProfile, pick_day_albums
from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyClient
from .clients.statsfm import StatsfmClient

WEEKDAYS_ES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def playlist_name(date: dt.date) -> str:
    return f"💿 {WEEKDAYS_ES[date.weekday()]} {date.strftime('%d/%m')} — 5 álbumes"


def playlist_description(picks: list[AlbumPick]) -> str:
    parts = [f"{p.to_dict()['label'].split(' ', 1)[1]}: {p.artist} – {p.name}"
             for p in picks]
    desc = "Playlist Lab · " + " | ".join(parts)
    return desc[:300]  # límite de Spotify


def build_day(sp: SpotifyClient, lf: LastfmClient | None, sf: StatsfmClient | None,
              date: dt.date, variant: int = 0, create: bool = False,
              exclude_album_ids: set[str] | None = None,
              profile: TasteProfile | None = None) -> dict:
    picks, warnings = pick_day_albums(sp, lf, sf, date, variant,
                                      exclude_album_ids, profile)
    result = {
        "date": date.isoformat(),
        "name": playlist_name(date),
        "albums": [p.to_dict() for p in picks],
        "total_minutes": sum(p.minutes for p in picks),
        "warnings": warnings,
        "created": None,
    }
    if create and picks:
        uris = [uri for p in picks for uri in p.track_uris]
        playlist = sp.create_playlist(playlist_name(date),
                                      playlist_description(picks), uris)
        result["created"] = {
            "id": playlist["id"],
            "url": playlist.get("external_urls", {}).get("spotify"),
        }
    return result


def next_monday(today: dt.date | None = None) -> dt.date:
    today = today or dt.date.today()
    return today + dt.timedelta(days=(7 - today.weekday()) % 7 or 7)


def build_week(sp: SpotifyClient, lf: LastfmClient | None, sf: StatsfmClient | None,
               start: dt.date | None = None, variant: int = 0,
               create: bool = True) -> dict:
    """Cinco días (L-V) desde `start` (por defecto el próximo lunes).

    Comparte el TasteProfile entre días (una sola pasada de red por tu perfil)
    y evita repetir álbumes dentro de la semana.
    """
    if start is None:
        today = dt.date.today()
        start = today if today.weekday() == 0 else next_monday(today)
    profile = TasteProfile(sp, lf, sf)
    used: set[str] = set()
    days = []
    for i in range(5):
        date = start + dt.timedelta(days=i)
        day = build_day(sp, lf, sf, date, variant, create, used, profile)
        used |= {a["spotify_id"] for a in day["albums"]}
        days.append(day)
    return {"start": start.isoformat(), "days": days}


# ---------- CLI ----------

def _clients():
    import os
    from pathlib import Path
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    port = os.getenv("PORT", "8888")
    sp = SpotifyClient(os.getenv("SPOTIFY_CLIENT_ID", ""),
                       f"http://127.0.0.1:{port}/callback")
    if not sp.authenticated:
        raise SystemExit("Sin sesión de Spotify: arranca la web (uvicorn app.main:app "
                         f"--port {port}) y haz login una vez.")
    lf = (LastfmClient(os.getenv("LASTFM_API_KEY", ""),
                       os.getenv("LASTFM_USERNAME") or None)
          if os.getenv("LASTFM_API_KEY") else None)
    sf = (StatsfmClient(os.getenv("STATSFM_USERNAME", ""))
          if os.getenv("STATSFM_USERNAME") else None)
    return sp, lf, sf


def main():
    ap = argparse.ArgumentParser(description="Playlists diarias de 5 álbumes")
    ap.add_argument("command", choices=["preview", "today", "week"])
    ap.add_argument("--start", help="Lunes de inicio (YYYY-MM-DD) para 'week'")
    ap.add_argument("--variant", type=int, default=0,
                    help="Cambia la 'tirada' del mismo día/semana")
    ap.add_argument("--dry-run", action="store_true",
                    help="No crear playlists, solo mostrar")
    args = ap.parse_args()

    sp, lf, sf = _clients()
    if args.command in ("preview", "today"):
        res = build_day(sp, lf, sf, dt.date.today(), args.variant,
                        create=(args.command == "today" and not args.dry_run))
    else:
        start = dt.date.fromisoformat(args.start) if args.start else None
        res = build_week(sp, lf, sf, start, args.variant,
                         create=not args.dry_run)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
