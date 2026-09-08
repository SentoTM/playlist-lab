"""Selector de álbumes diarios: 5 categorías, ~1 hora máximo por álbum.

Categorías:
  modern    — de tus gustos, últimos 5 años, artista que no conoces
  classic   — de tus gustos, anterior a 2000, artista que no conoces
  adjacent  — género vecino a tu perfil (p. ej. rock/punk → metal)
  distant   — género lejano: la sorpresa (jazz, electrónica, pop…)
  essential — un imprescindible de cualquier género
"""
import datetime as dt
import random
from dataclasses import dataclass, field

from ..clients.lastfm import LastfmClient
from ..clients.spotify import SpotifyClient
from ..clients.statsfm import StatsfmClient
from ..engines.core import norm
from .essentials import ESSENTIALS
from .genre_map import adjacent_families, distant_families, FAMILY_TAGS, profile_families

MAX_MINUTES = 72
MIN_MINUTES = 18
MIN_TRACKS = 5
CATEGORIES = ("modern", "classic", "adjacent", "distant", "essential")

CATEGORY_LABEL = {
    "modern": "🆕 Moderno similar",
    "classic": "🕰 Clásico similar",
    "adjacent": "↔️ Género adyacente",
    "distant": "🎲 Sorpresa lejana",
    "essential": "⭐ Imprescindible",
}


@dataclass
class AlbumPick:
    category: str
    name: str
    artist: str
    spotify_id: str
    release_year: int | None
    minutes: int
    n_tracks: int
    reason: str
    image: str | None = None
    track_uris: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "category": self.category, "label": CATEGORY_LABEL[self.category],
            "album": self.name, "artist": self.artist, "year": self.release_year,
            "minutes": self.minutes, "tracks": self.n_tracks,
            "reason": self.reason, "spotify_id": self.spotify_id, "image": self.image,
        }


class TasteProfile:
    """Qué conoces (artistas) y qué escuchas (familias de género)."""

    def __init__(self, sp: SpotifyClient, lf: LastfmClient | None,
                 sf: StatsfmClient | None):
        self.sp, self.lf, self.sf = sp, lf, sf
        self.known_artists: set[str] = set()
        self.top_artist_names: list[str] = []
        genres: list[str] = []

        for rng in ("short_term", "medium_term", "long_term"):
            for a in sp.top_artists(rng, 50):
                self.known_artists.add(norm(a["name"]))
                genres.extend(a.get("genres", []))
                if rng != "long_term" and a["name"] not in self.top_artist_names:
                    self.top_artist_names.append(a["name"])

        if lf and lf.username:
            for a in lf.user_top_artists("overall", 200):
                self.known_artists.add(norm(a["name"]))
            for a in lf.user_top_artists("12month", 30):
                if a["name"] not in self.top_artist_names:
                    self.top_artist_names.append(a["name"])

        if sf:
            for a in sf.top_artists("lifetime", 200):
                self.known_artists.add(norm(a["name"]))

        self.families = profile_families(genres)

    def knows_artist(self, name: str) -> bool:
        if norm(name) in self.known_artists:
            return True
        # comprobación fina vía Last.fm (si está configurado): >8 scrobbles = lo conoces
        if self.lf and self.lf.username:
            try:
                return self.lf.user_artist_playcount(name) > 8
            except Exception:
                return False
        return False


def _resolve_album(sp: SpotifyClient, artist: str, album: str) -> AlbumPick | None:
    """Busca el álbum en Spotify y valida duración/nº de pistas."""
    results = sp.search_album(f"album:{album} artist:{artist}", limit=2) \
        or sp.search_album(f"{album} {artist}", limit=2)
    for r in results:
        r_artist = r["artists"][0]["name"] if r.get("artists") else ""
        if norm(r_artist) != norm(artist):
            continue
        return _validate_album(sp, r["id"], category="", reason="")
    return None


def _validate_album(sp: SpotifyClient, album_id: str,
                    category: str, reason: str) -> AlbumPick | None:
    try:
        full = sp.album(album_id)
    except Exception:
        return None
    tracks = full.get("tracks", {}).get("items", [])
    if len(tracks) < MIN_TRACKS:
        return None
    minutes = round(sum(t.get("duration_ms", 0) for t in tracks) / 60000)
    if not (MIN_MINUTES <= minutes <= MAX_MINUTES):
        return None
    year = None
    rd = full.get("release_date", "")
    if rd[:4].isdigit():
        year = int(rd[:4])
    images = full.get("images") or []
    artist = full["artists"][0]["name"] if full.get("artists") else ""
    return AlbumPick(
        category=category, name=full.get("name", ""), artist=artist,
        spotify_id=album_id, release_year=year, minutes=minutes,
        n_tracks=len(tracks), reason=reason,
        image=images[-1]["url"] if images else None,
        track_uris=[t["uri"] for t in tracks if t.get("uri")],
    )


def _similar_unknown_artists(profile: TasteProfile, rng: random.Random,
                             n_seeds: int = 8, per_seed: int = 12) -> list[tuple[str, str]]:
    """[(artista_similar_desconocido, artista_semilla_tuyo)]"""
    if not profile.lf:
        return []
    seeds = profile.top_artist_names[:20]
    rng.shuffle(seeds)
    out, seen = [], set()
    for seed in seeds[:n_seeds]:
        for sim in profile.lf.similar_artists(seed, limit=per_seed):
            k = norm(sim["name"])
            if k in seen or k in profile.known_artists:
                continue
            seen.add(k)
            out.append((sim["name"], seed))
    rng.shuffle(out)
    return out


def _pick_similar_era(sp: SpotifyClient, profile: TasteProfile, rng: random.Random,
                      category: str, year_min: int | None, year_max: int | None,
                      exclude: set[str], used_artists: set[str],
                      budget: int = 14) -> AlbumPick | None:
    """Álbum de un artista similar desconocido, dentro de un rango de años."""
    for artist_name, seed in _similar_unknown_artists(profile, rng):
        if budget <= 0:
            break
        if norm(artist_name) in used_artists:
            continue
        found = sp.search_artist(artist_name, limit=1)
        if not found:
            continue
        albums = [a for a in sp.artist_albums(found[0]["id"], limit=30)
                  if a.get("album_type") == "album"]
        rng.shuffle(albums)
        for a in albums:
            y = a.get("release_date", "")[:4]
            if not y.isdigit():
                continue
            y = int(y)
            if (year_min and y < year_min) or (year_max and y > year_max):
                continue
            if a["id"] in exclude:
                continue
            budget -= 1
            pick = _validate_album(sp, a["id"], category,
                                   f"similar a {seed}, que escuchas mucho")
            if pick and not profile.knows_artist(pick.artist):
                return pick
            if budget <= 0:
                break
    return None


def _pick_by_family(sp: SpotifyClient, profile: TasteProfile, rng: random.Random,
                    category: str, families: list[str],
                    exclude: set[str], used_artists: set[str],
                    budget: int = 14) -> AlbumPick | None:
    """Álbum bien valorado de una familia de género dada (vía tags de Last.fm)."""
    if not profile.lf or not families:
        return None
    family = rng.choice(families)
    tags = FAMILY_TAGS.get(family, [family])
    tag = rng.choice(tags)
    albums = profile.lf.tag_top_albums(tag, limit=50, page=rng.randint(1, 3))
    rng.shuffle(albums)
    for a in albums:
        if budget <= 0:
            break
        if norm(a["artist"]) in used_artists or profile.knows_artist(a["artist"]):
            continue
        budget -= 1
        pick = _resolve_album(sp, a["artist"], a["name"])
        if pick and pick.spotify_id not in exclude:
            pick.category = category
            pick.reason = f"género {family} (tag «{tag}»), fuera de tu órbita habitual"
            return pick
    return None


def _pick_essential(sp: SpotifyClient, profile: TasteProfile, rng: random.Random,
                    exclude: set[str], used_artists: set[str]) -> AlbumPick | None:
    pool = list(ESSENTIALS)
    rng.shuffle(pool)
    fallback = None
    for artist, album, family in pool:
        if norm(artist) in used_artists:
            continue
        pick = _resolve_album(sp, artist, album)
        if not pick or pick.spotify_id in exclude:
            continue
        pick.category = "essential"
        pick.reason = f"clásico unánime ({family})"
        if profile.knows_artist(artist):
            fallback = fallback or pick  # conocido pero válido, por si no hay mejor
            continue
        return pick
    return fallback


def pick_day_albums(sp: SpotifyClient, lf: LastfmClient | None,
                    sf: StatsfmClient | None,
                    date: dt.date, variant: int = 0,
                    exclude_album_ids: set[str] | None = None,
                    profile: TasteProfile | None = None) -> tuple[list[AlbumPick], list[str]]:
    """Los 5 álbumes de un día. Determinista por (fecha, variant)."""
    exclude = set(exclude_album_ids or set())
    profile = profile or TasteProfile(sp, lf, sf)
    warnings: list[str] = []
    this_year = dt.date.today().year
    picks: list[AlbumPick] = []
    used_artists: set[str] = set()

    def add(pick: AlbumPick | None, category: str):
        if pick is None:
            warnings.append(f"No encontré álbum para la categoría «{category}» hoy")
            return
        if norm(pick.artist) in used_artists:
            warnings.append(f"Descarté un duplicado de artista en «{category}»")
            return
        used_artists.add(norm(pick.artist))
        exclude.add(pick.spotify_id)
        picks.append(pick)

    seed_base = f"{date.isoformat()}#{variant}"
    r = lambda cat: random.Random(f"{seed_base}:{cat}")

    if lf is None:
        warnings.append("Sin Last.fm configurado solo puedo elegir el imprescindible; "
                        "las otras categorías necesitan LASTFM_API_KEY")

    add(_pick_similar_era(sp, profile, r("modern"), "modern",
                          year_min=this_year - 5, year_max=None,
                          exclude=exclude, used_artists=used_artists), "modern")
    add(_pick_similar_era(sp, profile, r("classic"), "classic",
                          year_min=None, year_max=1999,
                          exclude=exclude, used_artists=used_artists), "classic")
    add(_pick_by_family(sp, profile, r("adjacent"), "adjacent",
                        adjacent_families(profile.families),
                        exclude, used_artists), "adjacent")
    add(_pick_by_family(sp, profile, r("distant"), "distant",
                        distant_families(profile.families),
                        exclude, used_artists), "distant")
    add(_pick_essential(sp, profile, r("essential"), exclude, used_artists), "essential")

    return picks, warnings
