"""Normalización de texto para comparar nombres de artistas y canciones."""
import re
import unicodedata


def norm(s: str) -> str:
    """Minúsculas, sin acentos, sin (feat...) ni sufijos tipo '- remaster'."""
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*[\(\[].*?(feat|with|remaster|version|edit|live|deluxe).*?[\)\]]", "", s)
    s = re.sub(r"\s*-\s*(remaster(ed)?|live|radio edit|single version).*$", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clave(nombre: str) -> str:
    """Clave para casar el MISMO artista escrito de formas distintas.

    Más agresiva que `norm`: quita tildes, mayúsculas, el artículo "The" del
    principio y la puntuación, porque las fuentes no se ponen de acuerdo:
    stats.fm dice "Basht.", Deezer "Basht"; "MAQUINA." frente a "Maquina";
    "Fontaines D.C." frente a "Fontaines DC"; "The Murder Capital" frente a
    "Murder Capital". "&" y "and"/"y" cuentan igual.
    """
    s = unicodedata.normalize("NFKD", (nombre or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    s = re.sub(r"[^\w\s]", "", s)            # puntos, apóstrofes, exclamaciones…
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^the ", "", s)
    s = re.sub(r"\b(and|y)\b", "and", s)
    return s.replace(" ", "")


# Lo que añade una edición a un título: paréntesis o corchetes y coletillas
# tras un guion ("moisturizer (deluxe)", "X - 20th Anniversary Edition").
_COLETILLA = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")
_TRAS_GUION = re.compile(r"\s+[-–—]\s+.*$")


def titulo_base(titulo: str) -> str:
    """El título sin la coletilla de edición, para encontrar el disco original."""
    t = _COLETILLA.sub("", titulo or "")
    t = _TRAS_GUION.sub("", t)
    return clave(t) or clave(titulo)


def parse_item(item: str) -> tuple[str, str]:
    """'Artista – Título' (guion, guion largo o ' - ') → (artista, título)."""
    for sep in (" – ", " — ", " - "):
        if sep in item:
            a, t = item.split(sep, 1)
            return a.strip(), t.strip()
    raise ValueError(f"Formato no reconocido (usa 'Artista – Título'): {item!r}")


_ESCAPE = re.compile(r"\\u([0-9a-fA-F]{4})")


def des_escapar(s: str) -> str:
    """Convierte '\\u00e9' literal en 'é'. A veces el modelo del chat manda
    las tildes escapadas y acaban así en el nombre de la playlist."""
    return _ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), s or "")
