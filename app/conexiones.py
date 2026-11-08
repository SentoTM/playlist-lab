"""Conexiones comprobadas entre dos artistas, cada dato con su fuente.

Sirve para contar cómo se relacionan dos grupos sin tirar de memoria. Busca
por separado, porque no valen lo mismo:

- Caminos de personas (MusicBrainz): quién tocó con quién. Es lo más sólido.
- Influencias declaradas y productores compartidos (Wikidata).
- Mismo sello (MusicBrainz): dato real, pero el vínculo más débil.

No encontrar nada no significa que no exista: la cobertura es desigual.
"""
import re

from .clients.musicbrainz import MusicbrainzClient
from .clients.wikidata import WikidataClient
from .text import clave, norm

MAX_CONSULTAS = 60
MAX_CAMINOS = 5
_UUID = re.compile(r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$", re.I)
_PISTA = re.compile(r"^(?P<nombre>.+?)\s*\((?P<pista>[^()]+)\)\s*$")
_SIN_SELLO = {"[no label]", "not on label", "self-released", "self released"}

# Tipos de relación que conectan de verdad. El texto va según el sentido que
# marca MusicBrainz: "forward" = el artista consultado es el sujeto.
_FRASES = {
    "member of band": "{s} fue miembro de {o}{p}",
    "collaboration": "{s} participó en el proyecto {o}{p}",
    "subgroup": "{s} surgió como subgrupo de {o}{p}",
    "supporting musician": "{s} tocó como músico de apoyo con {o}{p}",
    "instrumental supporting musician": "{s} tocó como músico de apoyo con {o}{p}",
    "vocal supporting musician": "{s} cantó como apoyo con {o}{p}",
    "is person": "{s} también actúa como {o}",
    "artist rename": "{s} pasó a llamarse {o}",
    "tribute": "{s} es un homenaje a {o}",
}
# Sin sentido fiable en el texto: se enuncian de forma simétrica
_SIMETRICAS = {
    "sibling": "{s} y {o} son hermanos",
    "married": "{s} y {o} han sido pareja",
    "involved with": "{s} y {o} han sido pareja",
    "parent": "{s} y {o} son familia (padre o madre e hijo o hija)",
    "teacher": "{s} y {o} tienen relación de maestro y alumno",
}


def _periodo(rel: dict) -> str:
    desde, hasta = (rel.get("begin") or "")[:4], (rel.get("end") or "")[:4]
    if desde and hasta:
        return f" ({desde}–{hasta})" if desde != hasta else f" ({desde})"
    if desde:
        return f" (desde {desde})"
    return f" (hasta {hasta})" if hasta else ""


def _url_mb(mbid: str) -> str:
    return f"https://musicbrainz.org/artist/{mbid}/relationships"


def aristas(artista: dict) -> list[dict]:
    """Las relaciones que conectan, a partir de la respuesta de MusicBrainz."""
    propio, salida = artista.get("name") or "?", []
    for rel in artista.get("relations") or []:
        otro = rel.get("artist") or {}
        tipo = rel.get("type")
        if not otro.get("id") or (tipo not in _FRASES and tipo not in _SIMETRICAS):
            continue
        if tipo in _SIMETRICAS:
            hecho = _SIMETRICAS[tipo].format(s=propio, o=otro.get("name"))
        else:
            s, o = propio, otro.get("name")
            if rel.get("direction") == "backward":
                s, o = o, s
            hecho = _FRASES[tipo].format(s=s, o=o, p=_periodo(rel))
        salida.append({"id": otro["id"], "nombre": otro.get("name"), "hecho": hecho,
                       "fuente": "MusicBrainz", "url": _url_mb(artista.get("id") or otro["id"])})
    return salida


def buscar_caminos(origen: str, destino: str, vecinos, max_saltos: int = 4,
                   max_consultas: int = MAX_CONSULTAS, paso=None) -> dict:
    """Búsqueda en anchura desde los dos extremos, nivel a nivel.

    `vecinos(id)` devuelve sus aristas o None si la fuente no respondió.
    Se amplía siempre el lado con menos nodos pendientes: cuesta mucho menos
    que recorrer todo desde un extremo.
    """
    padres = ({origen: None}, {destino: None})
    frontera = ([origen], [destino])
    consultas, fallos, saltos, agotado = 0, 0, 0, False

    def camino(cruce: str) -> list[dict]:
        ida, n = [], cruce
        while padres[0][n]:
            n, arista = padres[0][n]
            ida.insert(0, arista)
        vuelta, n = [], cruce
        while padres[1][n]:
            n, arista = padres[1][n]
            vuelta.append(arista)
        return ida + vuelta

    while saltos < max_saltos and frontera[0] and frontera[1] and not agotado:
        lado = 0 if len(frontera[0]) <= len(frontera[1]) else 1
        nueva = []
        for nodo in frontera[lado]:
            if consultas >= max_consultas:
                agotado = True
                break
            consultas += 1
            if paso:
                paso(f"consulta {consultas} de {max_consultas} como mucho")
            lista = vecinos(nodo)
            if lista is None:
                fallos += 1
                continue
            for arista in lista:
                if arista["id"] not in padres[lado]:
                    padres[lado][arista["id"]] = (nodo, arista)
                    nueva.append(arista["id"])
        frontera = (nueva, frontera[1]) if lado == 0 else (frontera[0], nueva)
        saltos += 1
        cruces = [n for n in nueva if n in padres[1 - lado]]
        if cruces:
            return {"caminos": [camino(n) for n in cruces[:MAX_CAMINOS]],
                    "consultas": consultas, "fallos": fallos, "completa": True}
    # Solo es búsqueda completa si se miró todo lo que tocaba sin fallos.
    return {"caminos": [], "consultas": consultas, "fallos": fallos,
            "completa": not agotado and not fallos}


def _separar(ref: str) -> tuple[str, str]:
    m = _PISTA.match(ref.strip())
    return (m["nombre"].strip(), m["pista"].strip()) if m else (ref.strip(), "")


def _texto_ficha(c: dict) -> str:
    return norm(" ".join(str(x) for x in (c.get("desambiguacion"), c.get("zona"), c.get("pais"),
                                          c.get("desde"), " ".join(c.get("tags") or [])) if x))


def identificar(ref: str, mb: MusicbrainzClient) -> dict:
    """El artista exacto. Admite MBID o 'Nombre (pista)' para los homónimos."""
    ref = (ref or "").strip()
    if _UUID.match(ref):
        return {"ficha": {"artist": None, "mbid": ref}, "homonimos": [], "avisos": []}
    nombre, pista = _separar(ref)
    candidatos = mb.buscar_artistas(nombre)
    exactos = [c for c in candidatos if clave(c["artist"]) == clave(nombre)]
    avisos = []
    if not exactos:
        aproximados = [c for c in candidatos if c.get("score", 0) >= 85]
        if not aproximados:
            return {"error": f"No encuentro a '{ref}' en MusicBrainz"}
        exactos = aproximados[:1]
        avisos.append(f"'{nombre}' no aparece tal cual: uso {exactos[0]['artist']}")
    elegido = exactos[0]
    if pista:
        palabras = [p for p in re.split(r"[\s,]+", norm(pista)) if p]
        puntos = [sum(p in _texto_ficha(c) for p in palabras) for c in exactos]
        if max(puntos):
            elegido = exactos[puntos.index(max(puntos))]
        else:
            avisos.append(f"La pista '{pista}' no coincide con ninguno: uso el primero")
    otros = [c for c in exactos if c["mbid"] != elegido["mbid"]]
    if otros and not pista:
        avisos.append(f"Hay {len(otros) + 1} artistas llamados '{nombre}'. Comprueba que "
                      "es el correcto; si no, usa 'Nombre (ciudad o género)' o su mbid.")
    return {"ficha": elegido, "homonimos": otros[:5], "avisos": avisos}


def _qid(artista: dict) -> str:
    for rel in artista.get("relations") or []:
        recurso = (rel.get("url") or {}).get("resource") or ""
        if rel.get("type") == "wikidata" or "wikidata.org/wiki/" in recurso:
            return recurso.rsplit("/", 1)[-1]
    return ""


def _spotify(artista: dict) -> str | None:
    for rel in artista.get("relations") or []:
        recurso = (rel.get("url") or {}).get("resource") or ""
        if "open.spotify.com/artist/" in recurso:
            return recurso
    return None


def _wd(texto: str, qid: str) -> dict:
    return {"hecho": texto, "fuente": "Wikidata", "url": f"https://www.wikidata.org/wiki/{qid}"}


def influencias(a: str, qa: str, b: str, qb: str, wd: WikidataClient) -> list[dict]:
    de_a, de_b = wd.influido_por(qa), wd.influido_por(qb)
    ids_a, ids_b = {x["qid"]: x["nombre"] for x in de_a}, {x["qid"]: x["nombre"] for x in de_b}
    salida = []
    if qb in ids_a:
        salida.append(_wd(f"{b} figura como influencia de {a}", qa))
    if qa in ids_b:
        salida.append(_wd(f"{a} figura como influencia de {b}", qb))
    for qid in [q for q in ids_a if q in ids_b][:8]:
        salida.append(_wd(f"{ids_a[qid]} figura como influencia de {a} y de {b}", qid))
    return salida


def productores(a: str, qa: str, b: str, qb: str, wd: WikidataClient) -> list[dict]:
    def agrupar(filas):
        grupos: dict[str, dict] = {}
        for f in filas:
            g = grupos.setdefault(f["qid"], {"nombre": f["nombre"], "discos": []})
            if f["obra"] not in g["discos"]:
                g["discos"].append(f["obra"])
        return grupos

    de_a, de_b = agrupar(wd.productores(qa)), agrupar(wd.productores(qb))
    salida = []
    if qb in de_a:
        salida.append(_wd(f"{b} produjo {', '.join(de_a[qb]['discos'][:3])} de {a}", qa))
    if qa in de_b:
        salida.append(_wd(f"{a} produjo {', '.join(de_b[qa]['discos'][:3])} de {b}", qb))
    for qid in [q for q in de_a if q in de_b and q not in (qa, qb)][:8]:
        salida.append(_wd(f"{de_a[qid]['nombre']} produjo {', '.join(de_a[qid]['discos'][:3])} "
                          f"de {a} y {', '.join(de_b[qid]['discos'][:3])} de {b}", qid))
    return salida


def sellos_comunes(a: dict, b: dict, mb: MusicbrainzClient) -> list[dict]:
    de_a, de_b = mb.sellos_por_id(a["mbid"]), mb.sellos_por_id(b["mbid"])
    claves_b = {norm(s) for s in de_b}
    return [{"hecho": f"{a['artist']} y {b['artist']} han publicado en {s}",
             "fuente": "MusicBrainz", "url": _url_mb(a["mbid"])}
            for s in de_a if norm(s) in claves_b and norm(s) not in _SIN_SELLO][:5]


def conectar(ref_a: str, ref_b: str, mb: MusicbrainzClient, wd: WikidataClient,
             max_saltos: int = 4, paso=None) -> dict:
    ida, vuelta = identificar(ref_a, mb), identificar(ref_b, mb)
    for r in (ida, vuelta):
        if r.get("error"):
            return {"error": r["error"]}
    a, b = dict(ida["ficha"]), dict(vuelta["ficha"])
    if a["mbid"] == b["mbid"]:
        return {"error": "Los dos nombres corresponden al mismo artista."}

    memo: dict[str, dict | None] = {}

    def datos(mbid: str):
        if mbid not in memo:
            memo[mbid] = mb.relaciones(mbid)
        return memo[mbid]

    def vecinos(mbid: str):
        d = datos(mbid)
        return None if d is None else aristas(d)

    avisos = ida["avisos"] + vuelta["avisos"]
    busqueda = buscar_caminos(a["mbid"], b["mbid"], vecinos,
                              max(1, min(max_saltos, 6)), paso=paso)
    da, db = datos(a["mbid"]) or {}, datos(b["mbid"]) or {}
    a["artist"], b["artist"] = a["artist"] or da.get("name"), b["artist"] or db.get("name")
    a["spotify"], b["spotify"] = _spotify(da), _spotify(db)
    qa, qb = _qid(da), _qid(db)
    a["wikidata"], b["wikidata"] = qa or None, qb or None

    infl, prod = [], []
    if qa and qb:
        if paso:
            paso("consultando Wikidata")
        infl = influencias(a["artist"], qa, b["artist"], qb, wd)
        prod = productores(a["artist"], qa, b["artist"], qb, wd)
    else:
        avisos.append("Sin ficha de Wikidata enlazada: no se han mirado influencias ni productores.")
    if paso:
        paso("mirando sellos")
    sellos = sellos_comunes(a, b, mb)

    caminos = [{"saltos": len(c), "via": [x["nombre"] for x in c[:-1]],
                "hechos": [{k: x[k] for k in ("hecho", "fuente", "url")} for x in c]}
               for c in busqueda["caminos"]]
    if busqueda["fallos"]:
        avisos.append(f"MusicBrainz no respondió en {busqueda['fallos']} consultas: "
                      "puede faltar algún camino.")
    return {
        "conectados": bool(caminos or infl or prod or sellos),
        "a": {**a, "homonimos": ida["homonimos"] or None},
        "b": {**b, "homonimos": vuelta["homonimos"] or None},
        "caminos": caminos, "influencias": infl, "productores": prod, "mismo_sello": sellos,
        "cobertura": {"consultas_musicbrainz": busqueda["consultas"],
                      "busqueda_completa": busqueda["completa"],
                      "max_saltos": max_saltos},
        "avisos": avisos or None,
        "como_usarlo": (
            "Cada 'hecho' se puede afirmar citando su fuente. Los caminos de personas son "
            "lo más sólido; un sello compartido es un dato real, pero una relación débil. "
            "Una conexión larga rara vez merece contarse. Si no sale nada, no afirmes que "
            "no existe: la cobertura es desigual."),
    }
