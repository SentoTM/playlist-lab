"""Cliente de MusicBrainz: verificación de hechos.

API pública, sin clave; solo exige un User-Agent identificable y como mucho
una petición por segundo. Sirve para confirmar lo que un modelo de lenguaje
tiende a inventarse con aplomo: año exacto de publicación, sello, país,
formación de un grupo y discografía real.
"""
import threading
import time

import httpx

API = "https://musicbrainz.org/ws/2"
HEADERS = {"User-Agent": "playlist-lab/0.2 (uso personal; https://github.com/SentoTM/playlist-lab)",
           "Accept": "application/json"}


class MusicbrainzClient:
    def __init__(self):
        self._http = httpx.Client(timeout=20, headers=HEADERS)
        self._lock = threading.Lock()
        self._last = 0.0

    def _get(self, path: str, **params) -> dict:
        """GET con el rate limit de 1 req/s que pide MusicBrainz."""
        with self._lock:
            wait = 1.05 - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
        try:
            resp = self._http.get(f"{API}{path}", params={"fmt": "json", **params})
            if resp.status_code != 200:
                return {}
            return resp.json()
        except (httpx.HTTPError, ValueError):
            return {}

    def find_artist(self, name: str) -> dict | None:
        """Artista: país, años de actividad, tipo y etiquetas de la comunidad."""
        data = self._get("/artist", query=f'artist:"{name}"', limit=3)
        for a in data.get("artists", []):
            if a.get("score", 0) < 80:
                continue
            span = a.get("life-span") or {}
            return {
                "artist": a.get("name"),
                "disambiguation": a.get("disambiguation"),
                "type": a.get("type"),
                "country": a.get("country"),
                "activo_desde": span.get("begin"),
                "activo_hasta": span.get("end"),
                "separado": bool(span.get("ended")),
                "tags": [t["name"] for t in (a.get("tags") or [])[:8]],
                "mbid": a.get("id"),
            }
        return None

    def find_release(self, artist: str, album: str) -> dict | None:
        """Álbum: primera publicación real (no la reedición), sello y formato."""
        data = self._get("/release-group",
                         query=f'releasegroup:"{album}" AND artist:"{artist}"', limit=3)
        for rg in data.get("release-groups", []):
            if rg.get("score", 0) < 80:
                continue
            return {
                "album": rg.get("title"),
                "artist": ", ".join(c["name"] for c in (rg.get("artist-credit") or [])
                                    if isinstance(c, dict) and c.get("name")),
                "primera_publicacion": rg.get("first-release-date"),
                "tipo": rg.get("primary-type"),
                "subtipos": rg.get("secondary-types") or [],
                "mbid": rg.get("id"),
            }
        return None

    def artist_relations(self, artist: str) -> dict:
        """Formación y parentesco: miembros, grupos en los que también tocan
        y de qué otros proyectos vienen. Es el mapa de una escena."""
        a = self.find_artist(artist)
        if not a:
            return {}
        data = self._get(f"/artist/{a['mbid']}", inc="artist-rels")
        miembros, otros_grupos = [], []
        for rel in data.get("relations", []):
            target = (rel.get("artist") or {}).get("name")
            if not target:
                continue
            tipo = rel.get("type")
            if tipo in ("member of band", "collaboration", "founder"):
                (miembros if rel.get("direction") == "backward" else otros_grupos
                 ).append({"nombre": target, "relacion": tipo,
                           "desde": (rel.get("begin") or "")[:4],
                           "hasta": (rel.get("end") or "")[:4]})
        return {"artist": a["artist"], "miembros": miembros[:20],
                "tambien_en": otros_grupos[:20]}

    def artists_from(self, area: str, tag: str = "", limit: int = 40) -> list[dict]:
        """Artistas de un país o ciudad, opcionalmente filtrados por etiqueta.

        `area` admite país ('Spain'), ciudad ('Manchester') o región.
        """
        query = f'area:"{area}"' + (f' AND tag:"{tag}"' if tag else "")
        data = self._get("/artist", query=query, limit=limit)
        out = []
        for a in data.get("artists", []):
            span = a.get("life-span") or {}
            out.append({
                "artist": a.get("name"),
                "desambiguacion": a.get("disambiguation"),
                "zona": ((a.get("begin-area") or {}).get("name")
                         or (a.get("area") or {}).get("name")),
                "activo_desde": (span.get("begin") or "")[:4],
                "separado": bool(span.get("ended")),
                "tags": [t["name"] for t in (a.get("tags") or [])[:5]],
            })
        return out

    def recent_by_artist(self, artist: str, desde: str, limit: int = 15) -> list[dict]:
        """Álbumes y EPs de un artista publicados desde `desde` (YYYY-MM-DD).

        Alternativa gratuita a preguntarle a Spotify por la discografía: aquí
        la fecha es la de PRIMERA edición y no gasta cuota. A cambio,
        MusicBrainz limita a una petición por segundo y algún lanzamiento muy
        reciente puede tardar días en aparecer catalogado.
        """
        data = self._get("/release-group",
                         query=f'artist:"{artist}" AND firstreleasedate:[{desde} TO *]',
                         limit=limit)
        out = []
        for rg in data.get("release-groups", []):
            if rg.get("score", 0) < 70 or rg.get("secondary-types"):
                continue
            credito = ", ".join(c["name"] for c in (rg.get("artist-credit") or [])
                                if isinstance(c, dict) and c.get("name"))
            fecha = rg.get("first-release-date") or ""
            if fecha < desde:
                continue
            out.append({"artist": credito or artist, "album": rg.get("title"),
                        "fecha": fecha, "tipo": rg.get("primary-type")})
        out.sort(key=lambda r: r["fecha"], reverse=True)
        return out

    def releases_by_tag(self, tag: str, year_from: int | None = None,
                        year_to: int | None = None, limit: int = 60) -> list[dict]:
        """Álbumes de un género en una franja de años, por fecha real de
        publicación (no la de la reedición que devuelve Spotify)."""
        query = f'tag:"{tag}" AND primarytype:album'
        if year_from or year_to:
            query += f' AND firstreleasedate:[{year_from or 1900} TO {year_to or 2100}]'
        data = self._get("/release-group", query=query, limit=limit)
        out = []
        for rg in data.get("release-groups", []):
            if rg.get("secondary-types"):
                continue
            out.append({
                "artist": ", ".join(c["name"] for c in (rg.get("artist-credit") or [])
                                    if isinstance(c, dict) and c.get("name")),
                "album": rg.get("title"),
                "fecha": rg.get("first-release-date"),
            })
        out.sort(key=lambda r: r["fecha"] or "")
        return out

    def buscar_sello(self, nombre: str) -> dict | None:
        """Ficha de un sello: país, años y tipo."""
        data = self._get("/label", query=f'label:"{nombre}"', limit=3)
        for l in data.get("labels", []):
            if l.get("score", 0) < 80:
                continue
            span = l.get("life-span") or {}
            return {"sello": l.get("name"), "tipo": l.get("type"),
                    "pais": l.get("country"), "desde": (span.get("begin") or "")[:4],
                    "disambiguation": l.get("disambiguation"), "mbid": l.get("id")}
        return None

    def catalogo_sello(self, nombre: str, desde: str = "", limit: int = 60) -> dict:
        """Qué publica un sello. Un buen sello es un filtro de gusto humano:
        si te gustan tres de sus discos, el cuarto tiene papeletas."""
        sello = self.buscar_sello(nombre)
        if not sello:
            return {"error": f"No encuentro el sello '{nombre}' en MusicBrainz"}
        # El listado no viene ordenado por fecha: sin paginar, lo reciente
        # puede quedarse fuera. Se recorre entero (con tope) y se ordena aquí.
        releases: list[dict] = []
        for offset in range(0, 400, 100):
            data = self._get("/release", label=sello["mbid"], limit=100,
                             offset=offset, inc="artist-credits")
            pagina = data.get("releases", [])
            releases.extend(pagina)
            if len(pagina) < 100:
                break
        vistos, salida = set(), []
        for r in releases:
            artista = ", ".join(c["artist"]["name"]
                                for c in (r.get("artist-credit") or [])
                                if isinstance(c, dict) and c.get("artist"))
            fecha = r.get("date") or ""
            clave = (artista.lower(), (r.get("title") or "").lower())
            if clave in vistos or (desde and fecha < desde):
                continue
            vistos.add(clave)
            salida.append({"artist": artista, "album": r.get("title"),
                           "fecha": fecha, "pais": r.get("country")})
        salida.sort(key=lambda r: r["fecha"] or "", reverse=True)
        return {"sello": sello, "publicaciones": salida[:limit],
                "total_en_catalogo": len(salida)}

    def novedades_sello(self, nombre: str, desde: str, limit: int = 60) -> dict:
        """Lo que ha publicado un sello DESDE una fecha.

        El catálogo completo (catalogo_sello) no viene ordenado por fecha, y en
        sellos grandes —Rough Trade, Sub Pop, Partisan, con miles de
        referencias— las primeras páginas son todo fondo antiguo: lo reciente
        nunca llegaba. Aquí se pregunta directamente por fecha con la
        búsqueda (laid = id del sello, date = rango), que sí lo permite.
        """
        sello = self.buscar_sello(nombre)
        if not sello:
            return {"error": f"No encuentro el sello '{nombre}' en MusicBrainz"}
        data = self._get("/release",
                         query=f'laid:{sello["mbid"]} AND date:[{desde} TO *]',
                         limit=min(limit, 100))
        vistos, salida = set(), []
        for r in data.get("releases", []):
            artista = ", ".join(
                (c.get("name") or (c.get("artist") or {}).get("name") or "")
                for c in (r.get("artist-credit") or []) if isinstance(c, dict))
            titulo = r.get("title") or ""
            fecha = r.get("date") or ""
            clave = (artista.lower(), titulo.lower())
            if not artista or clave in vistos or fecha < desde:
                continue
            vistos.add(clave)
            salida.append({"artist": artista, "album": titulo, "fecha": fecha,
                           "tipo": (r.get("release-group") or {}).get("primary-type")})
        salida.sort(key=lambda r: r["fecha"], reverse=True)
        return {"sello": sello, "publicaciones": salida}

    def sellos_de(self, artist: str, album: str = "") -> list[str]:
        """Con qué sellos ha publicado un artista: la puerta de entrada a una
        escena, porque los sellos agrupan por afinidad, no por algoritmo."""
        consulta = f'artist:"{artist}"' + (f' AND release:"{album}"' if album else "")
        # ojo: las búsquedas no admiten 'inc' (MusicBrainz responde 400); la
        # información de sello ya viene incluida en el resultado
        data = self._get("/release", query=consulta, limit=40)
        sellos: dict[str, int] = {}
        for r in data.get("releases", []):
            for info in r.get("label-info", []):
                nombre = (info.get("label") or {}).get("name")
                if nombre and nombre != "[no label]":
                    sellos[nombre] = sellos.get(nombre, 0) + 1
        return [n for n, _ in sorted(sellos.items(), key=lambda x: -x[1])][:8]

    def discography(self, artist: str, limit: int = 50) -> list[dict]:
        """Álbumes de estudio del artista, por fecha. Detecta huecos y rarezas."""
        a = self.find_artist(artist)
        if not a:
            return []
        data = self._get("/release-group", artist=a["mbid"],
                         type="album", limit=limit)
        out = []
        for rg in data.get("release-groups", []):
            if rg.get("secondary-types"):  # fuera recopilatorios, directos, remixes
                continue
            out.append({"album": rg.get("title"),
                        "fecha": rg.get("first-release-date"),
                        "tipo": rg.get("primary-type")})
        out.sort(key=lambda r: r["fecha"] or "9999")
        return out
