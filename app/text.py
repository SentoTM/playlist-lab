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
