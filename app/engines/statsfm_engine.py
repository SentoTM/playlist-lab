"""Motor stats.fm: usa tu historial completo de reproducciones.

Dos señales que tu top reciente de Spotify no da:
  1. Redescubrimiento — favoritos de toda la vida que NO están en tu top
     reciente: canciones que amabas y has dejado de escuchar.
  2. Artistas de fondo — artistas con muchos streams históricos cuyos
     temas menos obvios quizá no conoces (vía expansión en Spotify).
"""
from ..clients.spotify import SpotifyClient
from ..clients.statsfm import StatsfmClient
from .core import Candidate, from_spotify_track, track_key


def generate(sf: StatsfmClient, sp: SpotifyClient,
             recent_keys: set[str],
             rediscover_weight: float = 0.7) -> list[Candidate]:
    candidates: list[Candidate] = []

    lifetime = sf.top_tracks("lifetime", 150)
    if not lifetime:
        return []
    max_streams = max(t["streams"] for t in lifetime) or 1

    # 1) Redescubrimiento: top histórico que ya no suena en tu rotación actual
    for t in lifetime:
        k = track_key(t["artist"], t["name"])
        if k in recent_keys:
            continue
        score = rediscover_weight * (t["streams"] / max_streams)
        candidates.append(Candidate(
            name=t["name"], artist=t["artist"],
            spotify_id=t["spotify_id"],
            spotify_uri=f"spotify:track:{t['spotify_id']}" if t["spotify_id"] else None,
            score=score, source="statsfm",
            reason=f"redescubrimiento: {t['streams']} reproducciones históricas",
        ))

    # 2) Profundizar en artistas históricos: temas suyos que no están en tu historial
    lifetime_keys = {track_key(t["artist"], t["name"]) for t in lifetime}
    top_artists = sf.top_artists("lifetime", 12)
    max_a = max((a["streams"] for a in top_artists), default=1) or 1
    for a in top_artists:
        artist_id = a.get("spotify_id")
        if not artist_id:  # stats.fm suele traer el id; si no, buscamos por nombre
            found = sp.search_artist(a["name"], limit=1)
            if not found:
                continue
            artist_id = found[0]["id"]
        for t in sp.artist_top_tracks(artist_id):
            ta = t["artists"][0]["name"] if t.get("artists") else a["name"]
            k = track_key(ta, t.get("name", ""))
            if k in lifetime_keys or k in recent_keys:
                continue
            score = (1 - rediscover_weight) * (a["streams"] / max_a) * 0.8
            candidates.append(from_spotify_track(
                t, score, "statsfm",
                f"de {a['name']} ({a['streams']} streams tuyos), aún sin escuchar"))

    return candidates
