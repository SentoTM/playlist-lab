"""Motor Last.fm: expande a partir de canciones semilla con track.getSimilar.

Las semillas pueden venir de tu top de Spotify y/o de tu top de Last.fm
(que incluye scrobbles de fuera de Spotify). Los resultados se resuelven
después a IDs de Spotify en el paso de resolución (main.py).
"""
from collections import defaultdict

from ..clients.lastfm import LastfmClient
from ..clients.spotify import SpotifyClient
from .core import Candidate, track_key


def generate(lf: LastfmClient, sp: SpotifyClient,
             use_lastfm_history: bool = True,
             n_seeds: int = 15) -> list[Candidate]:
    # --- semillas ---
    seeds: list[tuple[str, str, float]] = []  # (artist, track, seed_weight)

    for rank, t in enumerate(sp.top_tracks("short_term", n_seeds)):
        a = t["artists"][0]["name"] if t.get("artists") else ""
        seeds.append((a, t.get("name", ""), 1.0 - rank / (n_seeds * 2)))

    if use_lastfm_history and lf.username:
        # scrobbles recientes de Last.fm — incluye lo que escuchas fuera de Spotify
        for rank, t in enumerate(lf.user_top_tracks("3month", n_seeds)):
            seeds.append((t["artist"], t["name"], 0.9 - rank / (n_seeds * 2)))

    # dedupe de semillas
    seen = set()
    uniq_seeds = []
    for a, n, w in seeds:
        k = track_key(a, n)
        if k not in seen:
            seen.add(k)
            uniq_seeds.append((a, n, w))

    # --- expansión con similares ---
    scores: dict[str, Candidate] = {}
    reasons: dict[str, set[str]] = defaultdict(set)

    for artist, name, seed_w in uniq_seeds[: n_seeds * 2]:
        for sim in lf.similar_tracks(artist, name, limit=15):
            k = track_key(sim["artist"], sim["name"])
            if k in seen:  # no proponer las propias semillas
                continue
            add = seed_w * sim["match"]
            if k in scores:
                scores[k].score += add
            else:
                scores[k] = Candidate(
                    name=sim["name"], artist=sim["artist"],
                    score=add, source="lastfm")
            reasons[k].add(f"{name} ({artist})")

    for k, c in scores.items():
        srcs = list(reasons[k])[:2]
        c.reason = "similar a " + " y ".join(srcs)

    return list(scores.values())
