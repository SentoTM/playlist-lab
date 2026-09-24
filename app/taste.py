"""Perfil de gustos: lo que la IA necesita saber de ti antes de proponer.

PRESUPUESTO DE FUENTES. La cuota de Spotify en modo desarrollo se agota con
facilidad y es el cuello de botella de todo, así que el perfil se construye
sobre fuentes gratuitas y Spotify se reserva para el final (resolver y crear):

  - stats.fm es la fuente principal: en UNA petición devuelve artistas con
    número de escuchas, géneros y hasta el id de Spotify, y admite rangos
    (weeks | months | lifetime). Cubre lo que antes pedíamos a los tops de
    Spotify, gratis.
  - Spotify solo aporta lo que nadie más tiene: la biblioteca guardada
    (guardar es decidir, repetir no). Cuesta ~18 peticiones, así que se
    cachea en disco varios días: cambia despacio.
  - Last.fm queda fuera del perfil porque duplica lo demás; su valor está en
    known_artists, donde es irreemplazable (escuchas de CUALQUIER artista).
"""
from collections import Counter

from .clients.lastfm import LastfmClient
from .clients.spotify import SpotifyClient
from .clients.statsfm import StatsfmClient
from .text import norm

RANGES = {"short_term": "4 semanas", "medium_term": "6 meses", "long_term": "años"}
# stats.fm cubre lo mismo sin gastar cuota de Spotify
RANGOS_STATSFM = {"weeks": "últimas semanas", "months": "últimos meses",
                  "lifetime": "siempre"}


def _artist_entries(items: list[dict], key: str, limit: int) -> list[dict]:
    out = []
    for a in items[:limit]:
        e = {"artist": a["name"], key: a.get(key)}
        if a.get("genres"):
            e["genres"] = a["genres"][:4]
        out.append(e)
    return out


def taste_profile(sf: StatsfmClient | None, biblioteca: dict | None = None,
                  artists_per_range: int = 20, tracks_per_range: int = 15) -> dict:
    """Resumen de gustos por periodo, géneros agregados y señales de cambio.

    Sin una sola petición a Spotify: todo sale de stats.fm salvo la
    biblioteca, que se le pasa ya cacheada.
    """
    genres: Counter = Counter()
    out: dict = {"por_periodo": {}, "fuente": "stats.fm (historial completo)"}
    if not sf:
        return {"error": "stats.fm no está configurado y es la fuente del perfil"}

    por_rango: dict[str, list] = {}
    for rango, label in RANGOS_STATSFM.items():
        artistas = sf.top_artists(rango, 50)
        por_rango[label] = artistas
        peso = 1.0 if rango != "lifetime" else 0.5
        for w, a in enumerate(artistas):
            for g in a.get("genres", []):
                genres[g] += peso * (50 - w) / 50  # los de arriba pesan más
        out["por_periodo"][label] = {
            "artistas": [{"artist": a["name"], "escuchas": a["streams"],
                          "generos": a.get("genres", [])[:4]}
                         for a in artistas[:artists_per_range]],
            "canciones": [f"{t['artist']} – {t['name']}"
                          for t in sf.top_tracks(rango, tracks_per_range)],
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

    out["biblioteca"] = biblioteca

    # Señales de cambio: quién ha entrado ahora y no venía de largo
    corto = {a["name"] for a in por_rango["últimas semanas"][:artists_per_range]}
    largo = {a["name"] for a in por_rango["siempre"][:artists_per_range]}
    out["fase_actual"] = sorted(corto - largo)
    out["generos_principales"] = [g for g, _ in genres.most_common(25)]
    out["nota"] = ("Periodos de stats.fm, que recoge todo tu historial de "
                   "Spotify. 'fase_actual' son los que suenan ahora y no "
                   "estaban en tu histórico: suele ser la pista más útil.")
    return out


def library(sp: SpotifyClient, max_tracks: int = 600) -> dict:
    # ~18 peticiones a Spotify: cachear varios días, no llamar en caliente
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
    try:
        seguidos = [a["name"] for a in sp.followed_artists(300) if a.get("name")]
    except Exception:  # noqa: BLE001
        seguidos = []
    return {
        "canciones_guardadas": len(tracks),
        "albumes_guardados": len(albums),
        "artistas_mas_guardados": [{"artist": n, "canciones": c}
                                   for n, c in por_artista.most_common(40)],
        "albumes_recientes_en_tu_biblioteca": albums_rows[:25],
        "artistas_seguidos": seguidos,
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


def known_artists(sf: StatsfmClient | None, lf: LastfmClient | None,
                  biblioteca: dict | None = None) -> dict[str, dict]:
    """Todos los artistas que conoces, con la fuente y la magnitud.

    Sin peticiones a Spotify: stats.fm (historial completo, 1 petición por
    tanda de 300), Last.fm (todo lo scrobbleado) y la biblioteca guardada
    que se le pasa ya cacheada. Es lo que usa check_known para no
    proponerte algo que ya tienes.
    """
    known: dict[str, dict] = {}

    def entry(name: str) -> dict:
        return known.setdefault(norm(name), {"artist": name})

    for fuente in (biblioteca or {}).get("artistas_mas_guardados", []):
        entry(fuente["artist"])["canciones_guardadas"] = fuente["canciones"]
    for fila in (biblioteca or {}).get("albumes_recientes_en_tu_biblioteca", []):
        if fila.get("artist"):
            entry(fila["artist"])["album_guardado"] = True
    for nombre in (biblioteca or {}).get("artistas_seguidos", []):
        entry(nombre)["lo_sigues"] = True
    if lf and lf.username:
        for a in lf.user_top_artists("overall", 300):
            entry(a["name"])["lastfm_plays"] = a["playcount"]
    if sf:
        for a in sf.top_artists("lifetime", 300):
            entry(a["name"])["statsfm_streams"] = a["streams"]
    # Lo reciente: quien has descubierto estas semanas aún no está en los
    # tops de siempre, pero ya lo conoces.
    if lf and lf.username:
        try:
            for a in lf.user_top_artists("1month", 200):
                e = entry(a["name"])
                e["lastfm_plays"] = max(e.get("lastfm_plays") or 0, a["playcount"])
        except Exception:  # noqa: BLE001
            pass
    if sf:
        try:
            for a in sf.top_artists("weeks", 100):
                e = entry(a["name"])
                e["statsfm_streams"] = max(e.get("statsfm_streams") or 0, a["streams"])
        except Exception:  # noqa: BLE001
            pass
    return known
