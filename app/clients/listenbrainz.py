"""ListenBrainz: novedades y similitudes de la fundación MetaBrainz.

API abierta y sin clave para los datos públicos. Aporta dos cosas que nos
faltaban gratis: un listado de lanzamientos recientes que no depende de
Spotify, y un cálculo de artistas similares con otra metodología que la de
Last.fm (que tira mucho a lo obvio), útil para contrastar.

Es best-effort: si cambian los endpoints, cada método degrada a vacío.
"""
import logging

import httpx

log = logging.getLogger("playlist_lab.listenbrainz")
API = "https://api.listenbrainz.org/1"
LABS = "https://labs.api.listenbrainz.org"
HEADERS = {"User-Agent": "playlist-lab/0.2 (uso personal)", "Accept": "application/json"}


class ListenbrainzClient:
    def __init__(self):
        self._http = httpx.Client(timeout=25, headers=HEADERS,
                                  follow_redirects=True)

    def _get(self, url: str, **params):
        try:
            resp = self._http.get(url, params=params)
            if resp.status_code != 200:
                log.warning("ListenBrainz %s en %s", resp.status_code, url)
                return None
            return resp.json()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("ListenBrainz falló en %s: %s", url, e)
            return None

    def novedades(self, dias: int = 21, limit: int = 80) -> list[dict]:
        """Lanzamientos recientes catalogados en MusicBrainz.

        Alternativa libre al listado de novedades de Spotify, que está
        cerrado a las apps nuevas.
        """
        data = self._get(f"{API}/explore/fresh-releases", days=min(dias, 90),
                         past="true", future="false", sort="release_date")
        if not data:
            return []
        releases = (data.get("payload") or {}).get("releases") or []
        out = []
        for r in releases:
            out.append({
                "artist": r.get("artist_credit_name"),
                "album": r.get("release_name"),
                "fecha": r.get("release_date"),
                "tipo": r.get("release_group_primary_type"),
                "oyentes_listenbrainz": r.get("listen_count"),
                "artist_mbid": (r.get("artist_mbids") or [None])[0],
            })
        out.sort(key=lambda r: (r.get("oyentes_listenbrainz") or 0), reverse=True)
        return [r for r in out if r["artist"]][:limit]

    def similares(self, artist_mbid: str, limit: int = 20) -> list[dict]:
        """Artistas similares por co-escucha real (no por etiquetas).

        Endpoint de laboratorio: puede cambiar sin aviso, así que degrada a
        lista vacía y el llamante se apoya en Last.fm.
        """
        if not artist_mbid:
            return []
        algoritmo = ("session_based_days_7500_session_300_contribution_5_"
                     "threshold_10_limit_100_filter_True_skip_30")
        data = self._get(f"{LABS}/similar-artists/json",
                         artist_mbids=artist_mbid, algorithm=algoritmo)
        if not isinstance(data, list):
            return []
        out = []
        for fila in data:
            nombre = fila.get("name") or fila.get("artist_name")
            if nombre:
                out.append({"artist": nombre,
                            "afinidad": fila.get("score"),
                            "mbid": fila.get("artist_mbid")})
        return out[:limit]
