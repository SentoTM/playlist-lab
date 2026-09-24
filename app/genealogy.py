"""Genealogía: influencias y herederos de un disco, con evidencia.

Reparto de papeles, decidido a propósito:
- El MODELO propone. Las influencias concretas de un disco salen de
  entrevistas y reseñas ("mientras grabábamos esto escuchábamos…"), y a ese
  nivel de detalle nada gratuito le llega a lo que el modelo ha leído.
- Las HERRAMIENTAS acotan y respaldan. La similitud (Last.fm, ListenBrainz)
  NO sirve aquí: es simétrica y no tiene tiempo, así que da primos, no
  abuelos. Lo que sí sirve:
    * Cronología (MusicBrainz): una influencia es anterior al disco y un
      heredero es posterior. Regla dura que caza el error más típico.
    * Wikidata P737: influencias declaradas, con estructura.
    * Wikipedia: el párrafo del artículo donde se citan, con su fuente.

Cada enlace sale etiquetado: documentado / plausible (criterio del modelo) /
descartado por fechas / sin fecha. Así se ve qué tiene respaldo y qué no.
"""
import logging

from .clients.musicbrainz import MusicbrainzClient
from .clients.wikidata import WikidataClient
from .clients.wikipedia import WikipediaClient, _plano_simple
from .text import norm, parse_item

log = logging.getLogger("playlist_lab.genealogy")

# Una "influencia" publicada uno o dos años antes suele ser un contemporáneo
# de la misma escena: primo, no abuelo (IDLES respecto a Fontaines D.C.).
MARGEN_CONTEMPORANEO = 2


def _partir(ref: str) -> tuple[str, str]:
    """'Artista – Álbum' -> (artista, álbum); 'Artista' -> (artista, '')."""
    try:
        return parse_item(ref)
    except ValueError:
        return ref.strip(), ""


def _fecha(mb: MusicbrainzClient, artista: str, album: str) -> tuple[str, str]:
    """(fecha, de_que): la primera edición del disco o, sin disco, el año de
    inicio del artista."""
    try:
        if album:
            r = mb.find_release(artista, album) or {}
            if r.get("primera_publicacion"):
                return r["primera_publicacion"], "disco"
        a = mb.find_artist(artista) or {}
        return (a.get("activo_desde") or ""), "inicio del artista"
    except Exception as e:  # noqa: BLE001
        log.warning("MusicBrainz falló con %s – %s: %s", artista, album, e)
        return "", ""


def evidencia(artista: str, album: str, wd: WikidataClient,
              wiki: WikipediaClient, mb: MusicbrainzClient) -> dict:
    """Todo lo documentado sobre de dónde viene (y a quién llevó) un disco."""
    ficha = wd.buscar_artista(artista) or {}
    de_quien_bebe = wd.influido_por(ficha["qid"]) if ficha else []
    quien_bebe = wd.influyo_en(ficha["qid"]) if ficha else []
    art_disco = (wiki.frases_de_influencia(f"{album} {artista}", "álbum de")
                 if album else {})
    art_artista = wiki.frases_de_influencia(artista, "banda grupo musical")
    fecha, de_que = _fecha(mb, artista, album)
    return {
        "objetivo": {"artist": artista, "album": album or None,
                     "fecha": fecha or None, "fecha_de": de_que or None},
        "wikidata": {"entidad": ficha or None,
                     "de_quien_bebe": [x["nombre"] for x in de_quien_bebe],
                     "quien_bebe_de_el": [x["nombre"] for x in quien_bebe]},
        "wikipedia": {
            "disco": {k: v for k, v in art_disco.items() if k != "texto_plano"} or None,
            "artista": {k: v for k, v in art_artista.items() if k != "texto_plano"} or None,
        },
        "_textos": " ".join(x.get("texto_plano", "") for x in (art_disco, art_artista)),
    }


def comprobar(artista: str, album: str, candidatos: list[str], direccion: str,
              wd: WikidataClient, wiki: WikipediaClient, mb: MusicbrainzClient) -> dict:
    """Etiqueta cada candidato propuesto como influencia (direccion="antes")
    o como heredero (direccion="despues") de un disco."""
    antes = not direccion.lower().startswith("desp")
    ev = evidencia(artista, album, wd, wiki, mb)
    fecha_obj = (ev["objetivo"]["fecha"] or "")[:4]
    textos = ev.pop("_textos", "")
    lista_wd = {norm(n) for n in (ev["wikidata"]["de_quien_bebe"] if antes
                                  else ev["wikidata"]["quien_bebe_de_el"])}

    filas = []
    for ref in candidatos[:12]:
        c_art, c_album = _partir(ref)
        fecha, de_que = _fecha(mb, c_art, c_album)
        anio = fecha[:4]
        pruebas = []
        if norm(c_art) in lista_wd:
            pruebas.append("Wikidata lo registra como "
                           + ("influencia" if antes else "heredero"))
        nombre_plano = _plano_simple(c_art)
        if len(nombre_plano) > 3 and nombre_plano in textos:
            pruebas.append("se le menciona en el artículo de Wikipedia")
        # al revés: ¿el candidato declara esta influencia en su propia ficha?
        if not antes:
            try:
                suya = wd.buscar_artista(c_art)
                if suya and norm(artista) in {norm(x["nombre"]) for x in wd.influido_por(suya["qid"])}:
                    pruebas.append(f"su ficha de Wikidata cita a {artista} como influencia")
            except Exception:  # noqa: BLE001
                pass

        if not anio or not fecha_obj:
            etiqueta = "sin fecha (no se puede comprobar la cronología)"
        elif (antes and anio > fecha_obj) or (not antes and anio < fecha_obj):
            etiqueta = "descartado por fechas"
        elif anio == fecha_obj:
            etiqueta = "dudoso: mismo año" + (" (documentado)" if pruebas else "")
        elif abs(int(fecha_obj) - int(anio)) <= MARGEN_CONTEMPORANEO and not pruebas:
            etiqueta = ("contemporáneo: más primo que " +
                        ("influencia" if antes else "heredero") +
                        " (misma escena y época)")
        elif pruebas:
            etiqueta = "documentado"
        else:
            etiqueta = "plausible (criterio del modelo)"
        filas.append({"candidato": ref, "fecha": fecha or None,
                      "fecha_de": de_que or None, "etiqueta": etiqueta,
                      "pruebas": pruebas})

    cuenta = {}
    for f in filas:
        clave = f["etiqueta"].split(" (")[0].split(":")[0]
        cuenta[clave] = cuenta.get(clave, 0) + 1
    return {
        "objetivo": ev["objetivo"],
        "direccion": "influencias (antes)" if antes else "herederos (después)",
        "candidatos": filas,
        "resumen": cuenta,
        "evidencia_disponible": {k: v for k, v in ev.items() if k != "objetivo"},
        "como_usarlo": (
            "Quita lo 'descartado por fechas'. Lo 'documentado' puedes afirmarlo "
            "citando la fuente. Lo 'plausible' es criterio tuyo: preséntalo como "
            "tal ('suena a…', 'viene de la misma escuela que…'), no como un hecho. "
            "Mira también evidencia_disponible: Wikidata y Wikipedia pueden "
            "sugerir nombres que no habías pensado."),
    }
