"""Modelo común de candidatos y utilidades compartidas por los motores."""
import random
import re
import unicodedata
from dataclasses import dataclass, field


def norm(s: str) -> str:
    """Normaliza para deduplicar: minúsculas, sin acentos, sin (feat...) ni - remaster."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*[\(\[].*?(feat|with|remaster|version|edit|live|deluxe).*?[\)\]]", "", s)
    s = re.sub(r"\s*-\s*(remaster(ed)?|live|radio edit|single version).*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def track_key(artist: str, name: str) -> str:
    return f"{norm(artist)}::{norm(name)}"


@dataclass
class Candidate:
    """Una canción candidata a entrar en la playlist."""
    name: str
    artist: str
    spotify_id: str | None = None
    spotify_uri: str | None = None
    score: float = 0.0
    source: str = ""          # motor que la propuso
    reason: str = ""          # explicación legible ("similar a X en Last.fm")
    album_image: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return track_key(self.artist, self.name)


def from_spotify_track(t: dict, score: float, source: str, reason: str) -> Candidate:
    artists = t.get("artists") or []
    images = (t.get("album") or {}).get("images") or []
    return Candidate(
        name=t.get("name", ""),
        artist=artists[0].get("name", "") if artists else "",
        spotify_id=t.get("id"),
        spotify_uri=t.get("uri"),
        score=score,
        source=source,
        reason=reason,
        album_image=images[-1]["url"] if images else None,
    )


def blend(pools: dict[str, tuple[float, list[Candidate]]],
          size: int,
          exclude_keys: set[str],
          per_artist_max: int = 2,
          seed: int | None = None) -> list[Candidate]:
    """Mezcla los candidatos de varios motores.

    pools: {nombre_motor: (peso, candidatos)}. Los scores de cada motor se
    normalizan a [0,1] antes de aplicar el peso, para que ningún motor domine
    solo por su escala. Si la misma canción aparece en varios motores, suma
    puntuaciones (señal de consenso). Selección por muestreo ponderado para
    que cada generación varíe un poco, con tope de canciones por artista.
    """
    rng = random.Random(seed)
    merged: dict[str, Candidate] = {}

    for engine, (weight, candidates) in pools.items():
        if not candidates or weight <= 0:
            continue
        top = max(c.score for c in candidates) or 1.0
        for c in candidates:
            if c.key in exclude_keys:
                continue
            weighted = weight * (c.score / top)
            if c.key in merged:
                existing = merged[c.key]
                existing.score += weighted
                existing.source += f"+{engine}" if engine not in existing.source else ""
                if not existing.spotify_uri and c.spotify_uri:
                    existing.spotify_uri, existing.spotify_id = c.spotify_uri, c.spotify_id
            else:
                c.score = weighted
                merged[c.key] = c

    pool = list(merged.values())
    chosen: list[Candidate] = []
    artist_count: dict[str, int] = {}

    while pool and len(chosen) < size * 3:  # margen: algunos no se resolverán en Spotify
        total = sum(max(c.score, 0.001) for c in pool)
        r = rng.uniform(0, total)
        acc = 0.0
        pick_idx = 0
        for i, c in enumerate(pool):
            acc += max(c.score, 0.001)
            if acc >= r:
                pick_idx = i
                break
        c = pool.pop(pick_idx)
        a = norm(c.artist)
        if artist_count.get(a, 0) >= per_artist_max:
            continue
        artist_count[a] = artist_count.get(a, 0) + 1
        chosen.append(c)

    return chosen
