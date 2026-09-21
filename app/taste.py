"""Perfil de gustos: lo que la IA necesita saber de ti antes de proponer.

Resumen compacto de fuentes que no se solapan:
  - Spotify: tops por periodo (4 semanas, 6 meses, años) con géneros, y la
    biblioteca guardada, que es otra señal: guardar es decidir, no repetir.
  - stats.fm: historial completo (lifetime) con géneros.

Last.fm queda fuera del perfil a propósito: al scrobblear solo desde Spotify,
sus tops duplican los de Spotify y alargan el contexto sin añadir señal. Su
valor está en known_artists/check_known, donde sí es irreemplazable (playcount
de CUALQUIER artista, no solo de los tops).
"""
from collections import Counter

from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyClient
from .clients.statsfm import StatsfmClient
from .text import norm

RANGES = {"short_term": "4 semanas", "medium_term": "6 meses", "long_term": "años"}


def _artist_entries(items: list[dict], key: str, limit: int) -> list[dict]:
    out = []
    for a in items[:limit]:
        e = {"artist": a["name"], key: a.get(key)}
        if a.get("genres"):
            e["genres"] = a["genres"][:4]
        out.append(e)
    return out


def taste_profile(sp: SpotifyClient, lf: LastfmClient | None, sf: StatsfmClient | None,
                  artists_per_range: int = 20, tracks_per_range: int = 15) -> dict:
    """Resumen de gustos por periodo, géneros agregados y señales de cambio."""
    genres: Counter = Counter()
    out: dict = {"spotify": {}, "statsfm": None}

    for rng, label in RANGES.items():
        artists = sp.top_artists(rng, 50)
        for w, a in enumerate(artists):
            for g in a.get("genres", []):
                genres[g] += (50 - w) / 50  # los de arriba pesan más
        tracks = sp.top_tracks(rng, tracks_per_range)
        out["spotify"][label] = {
            "artists": [{"artist": a["name"], "genres": a.get("genres", [])[:4]}
                        for a in artists[:artists_per_range]],
            "tracks": [f"{(t.get('artists') or [{}])[0].get('name', '')} – {t.get('name', '')}"
                       for t in tracks],
        }

    if sf:
        top = sf.top_artists("lifetime", 40)
        for w, a in enumerate(top):
            for g in a.get("genres", []):
                genres[g] += 0.5 * (40 - w) / 40
        out["statsfm"] = {
            "top_artistas_historico": [
                {"artist": a["name"], "streams": a["streams"], "genres": a["genres"][:3]}
                for a in top[:30]],
            "top_canciones_historico": [
                f"{t['artist']} – {t['name']} ({t['streams']} reproducciones)"
                for t in sf.top_tracks("lifetime", 20)],
        }

    try:
        out["biblioteca"] = library(sp, 400)
    except Exception:  # noqa: BLE001
        out["biblioteca"] = None

    # Señales de cambio: artistas nuevos en el corto plazo que no están en el largo
    short = {a["artist"] for a in out["spotify"]["4 semanas"]["artists"]}
    long_ = {a["artist"] for a in out["spotify"]["años"]["artists"]}
    out["fase_actual"] = sorted(short - long_)
    out["generos_principales"] = [g for g, _ in genres.most_common(25)]
    return out


def library(sp: SpotifyClient, max_tracks: int = 600) -> dict:
    """Tu biblioteca: lo que has GUARDADO, no lo que has repetido.

    Guardar es una decisión deliberada; los tops son solo repetición. Dos
    señales distintas: aquí aparecen discos que aprecias aunque no suenen a
    diario, y artistas que un top nunca mostraría.
    """
    tracks = sp.all_saved_tracks(max_tracks)
    albums = sp.saved_albums(300)
    por_artista: Counter = Counter()
    for t in tracks:
        for a in t.get("artists") or []:
            if a.get("name"):
                por_artista[a["name"]] += 1
    albums_rows = [{
        "artist": (a.get("artists") or [{}])[0].get("name", ""),
        "album": a.get("name", ""),
        "year": (a.get("release_date") or "")[:4],
        "guardado": (a.get("_added_at") or "")[:10],
    } for a in albums]
    albums_rows.sort(key=lambda r: r["guardado"], reverse=True)
    return {
        "canciones_guardadas": len(tracks),
        "albumes_guardados": len(albums),
        "artistas_mas_guardados": [{"artist": n, "canciones": c}
                                   for n, c in por_artista.most_common(30)],
        "albumes_recientes_en_tu_biblioteca": albums_rows[:25],
    }


def playlists(sp: SpotifyClient, mine_only: bool = True) -> list[dict]:
    """Tus playlists: cómo organizas tú la música (temas, estados de ánimo,
    proyectos). Los nombres dicen mucho sobre para qué usas cada cosa."""
    me = sp.me().get("id")
    out = []
    for pl in sp.my_playlists():
        if mine_only and (pl.get("owner") or {}).get("id") != me:
            continue
        out.append({
            "nombre": pl.get("name"),
            "descripcion": pl.get("description") or "",
            "canciones": (pl.get("tracks") or {}).get("total", 0),
            "id": pl.get("id"),
            "publica": pl.get("public"),
        })
    return out


def known_artists(sp: SpotifyClient, lf: LastfmClient | None,
                  sf: StatsfmClient | None) -> dict[str, dict]:
    """Todos los artistas que conoces, con la fuente y la magnitud.

    Cruza cinco señales: tops de Spotify, biblioteca guardada, artistas que
    sigues, scrobbles de Last.fm e historial de stats.fm. Es lo que usa
    check_known para no proponerte algo que ya tienes.
    """
    known: dict[str, dict] = {}

    def entry(name: str) -> dict:
        return known.setdefault(norm(name), {"artist": name})

    for rng in RANGES:
        for i, a in enumerate(sp.top_artists(rng, 50)):
            e = entry(a["name"])
            e["spotify_rank"] = min(e.get("spotify_rank", 999), i + 1)

    for t in sp.all_saved_tracks(600):
        for a in t.get("artists") or []:
            if a.get("name"):
                e = entry(a["name"])
                e["canciones_guardadas"] = e.get("canciones_guardadas", 0) + 1
    for a in sp.saved_albums(300):
        for art in a.get("artists") or []:
            if art.get("name"):
                entry(art["name"])["album_guardado"] = True
    for a in sp.followed_artists(300):
        if a.get("name"):
            entry(a["name"])["lo_sigues"] = True
    if lf and lf.username:
        for a in lf.user_top_artists("overall", 300):
            entry(a["name"])["lastfm_plays"] = a["playcount"]
    if sf:
        for a in sf.top_artists("lifetime", 300):
            entry(a["name"])["statsfm_streams"] = a["streams"]
    return known
