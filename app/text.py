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
