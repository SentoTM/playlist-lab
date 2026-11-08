"""Balance: qué tipo de propuesta funciona de verdad.

La huella dice qué pasó con cada pieza; esto dice qué tienen en común las
que prendieron. Al crear una lista cada pieza se etiqueta con su PAPEL (qué
hace en la lista) y su ORIGEN (de dónde salió la idea), y aquí se cruza con
la huella. Así se contesta con datos suyos a "¿el radar aporta algo o me
bastaría con mi criterio?".

Es correlación con muestras pequeñas: orienta, no demuestra.
"""
from .huella import TIRO_DEL_HILO
from .text import norm

PAPELES = {"ancla", "contexto", "salida", "puente", "temazo", "transicion",
           "puerta_oscura"}
ORIGENES = {"criterio", "radar", "prensa", "kexp", "listenbrainz", "similares",
            "atlas", "semilla", "emergentes", "otro"}
MUESTRA_MINIMA = 5


def _canon(valor) -> str:
    return norm(str(valor or "")).replace(" ", "_").replace("-", "_")


def _casa(fila: dict, pieza: str) -> bool:
    """Una etiqueta casa con su fila por el texto exacto de items o, si no,
    por artista y título."""
    if pieza == fila.get("input"):
        return True
    texto = pieza.split("|", 1)[0].strip()
    if texto.lower().startswith(("album:", "álbum:")):
        texto = texto.split(":", 1)[1].strip()
    artista, _, titulo = texto.replace(" — ", " – ").replace(" - ", " – ").partition(" – ")
    if norm(artista) != norm(fila.get("artist") or ""):
        return False
    return not titulo or norm(titulo) == norm(fila.get("album" if fila.get("type") == "album"
                                                      else "title") or "")


def aplicar_etiquetas(resueltos: list[dict], etiquetas: list[dict]) -> list[str]:
    """Anota papel y origen en cada fila resuelta. Nunca impide crear la
    lista: lo que no case o no se reconozca se avisa y ya está."""
    avisos, libres = [], list(resueltos)
    for e in etiquetas or []:
        pieza = str(e.get("pieza") or "").strip()
        fila = next((f for f in libres if pieza and f.get("input") == pieza), None) \
            or next((f for f in libres if pieza and _casa(f, pieza)), None)
        if not fila:
            avisos.append(f"Etiqueta sin pieza en la lista: {pieza or e}")
            continue
        libres.remove(fila)
        papel, origen = _canon(e.get("papel")), _canon(e.get("origen"))
        if papel:
            fila["papel"] = papel
            if papel not in PAPELES:
                avisos.append(f"Papel desconocido '{papel}' en {pieza}")
        if origen:
            fila["origen"] = origen
            if origen not in ORIGENES:
                avisos.append(f"Origen desconocido '{origen}' en {pieza}")
        if e.get("conocido"):
            fila["conocido"] = True
    return avisos


def _vacio() -> dict:
    return {"piezas": 0, "tocadas": 0, "discos": 0, "enteros": 0, "volvio": 0,
            "guardo": 0, "tiro_del_hilo": 0, "prendieron": 0, "arraigaron": 0}


def _sumar(grupo: dict, f: dict) -> None:
    grupo["piezas"] += 1
    grupo["tocadas"] += 1 if f.get("escuchas") else 0
    if f.get("tipo") == "album":
        grupo["discos"] += 1
        grupo["enteros"] += 1 if f.get("estado") == "entero" else 0
    grupo["volvio"] += 1 if (f.get("dias_con_escuchas") or 0) >= 2 else 0
    grupo["guardo"] += 1 if f.get("canciones_guardadas") else 0
    grupo["tiro_del_hilo"] += 1 if (f.get("otras_cosas_del_artista") or 0) >= TIRO_DEL_HILO else 0
    grupo["prendieron"] += 1 if f.get("prendio") else 0
    grupo["arraigaron"] += 1 if f.get("arraigo") else 0


def _tabla(grupos: dict) -> list[dict]:
    filas = []
    for nombre, g in grupos.items():
        n = g["piezas"]
        filas.append({"grupo": nombre, **g,
                      "pct_tocadas": round(100 * g["tocadas"] / n),
                      "pct_prendieron": round(100 * g["prendieron"] / n),
                      "muestra": "ok" if n >= MUESTRA_MINIMA else "poca"})
    filas.sort(key=lambda f: (f["muestra"] != "ok", -f["pct_prendieron"], -f["piezas"]))
    return filas


def resumir(listas: dict) -> dict:
    """Agrega la huella por origen, papel y tipo de pieza.

    Solo cuentan las piezas etiquetadas de listas que llegó a abrir: una lista
    entera sin tocar habla del momento, no de lo que llevaba dentro. Lo que
    aún es pronto tampoco cuenta, y lo que ya conocía queda fuera de la tabla
    de orígenes porque "tiró del hilo" no significaría nada.
    """
    por_origen, por_papel, por_tipo = {}, {}, {}
    sin_abrir, sin_etiquetar, pronto, usadas = [], 0, 0, 0
    for nombre, lista in listas.items():
        filas = lista.get("elementos") or []
        etiquetadas = [f for f in filas if f.get("papel") or f.get("origen")]
        if not etiquetadas:
            sin_etiquetar += 1
            continue
        if not any(f.get("escuchas") for f in filas):
            sin_abrir.append(nombre)
            continue
        usadas += 1
        for f in etiquetadas:
            if f.get("estado") == "aún es pronto":
                pronto += 1
                continue
            _sumar(por_tipo.setdefault(f.get("tipo") or "?", _vacio()), f)
            if f.get("papel"):
                _sumar(por_papel.setdefault(f["papel"], _vacio()), f)
            if f.get("origen") and not f.get("conocido") and f.get("papel") != "puente":
                _sumar(por_origen.setdefault(f["origen"], _vacio()), f)
    salida = {"listas_analizadas": usadas, "listas_sin_abrir": sin_abrir or None,
              "listas_sin_etiquetas": sin_etiquetar, "piezas_aun_pronto": pronto}
    if not usadas:
        return {**salida, "sin_datos": True,
                "nota": ("Aún no hay listas etiquetadas y escuchadas. Crea las listas con "
                         "create_playlist(etiquetas=…) y vuelve en unas semanas.")}
    return {**salida, "por_origen": _tabla(por_origen), "por_papel": _tabla(por_papel),
            "por_tipo": _tabla(por_tipo),
            "como_leerlo": (
                "'pct_prendieron' es la señal principal: volvió, guardó o tiró del hilo. "
                "Con muestra 'poca' no saques conclusiones. Es correlación: el orden en "
                "la lista y lo que le apetecía esa semana también pesan. Úsalo para "
                "ajustar proporciones, no para descartar una fuente.")}
