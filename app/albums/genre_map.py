"""Mapa de familias de géneros y adyacencias.

Spotify etiqueta artistas con micro-géneros ("madrid indie", "skate punk"…).
Los agrupamos en familias, y definimos qué familias son *adyacentes* entre
sí para poder elegir un álbum "cercano pero distinto" y otro "lejano".
"""

# familia -> palabras clave que la identifican en los géneros de Spotify/Last.fm
FAMILY_KEYWORDS: dict[str, list[str]] = {
    "rock":       ["rock", "grunge", "britpop", "garage", "psych", "shoegaze", "post-rock"],
    "punk":       ["punk", "hardcore", "emo", "ska", "oi", "riot grrrl"],
    "metal":      ["metal", "thrash", "doom", "sludge", "djent", "metalcore", "black metal", "death metal"],
    "indie":      ["indie", "lo-fi", "alternative", "art pop", "dream pop", "slacker"],
    "electronic": ["electro", "techno", "house", "edm", "idm", "synth", "ambient", "drum and bass", "trance", "dubstep"],
    "hiphop":     ["hip hop", "rap", "trap", "grime", "drill", "boom bap"],
    "jazz":       ["jazz", "bebop", "bossa", "swing", "fusion"],
    "pop":        ["pop", "boy band", "girl group", "dance pop", "k-pop"],
    "folk":       ["folk", "singer-songwriter", "americana", "country", "bluegrass", "acoustic"],
    "soul":       ["soul", "funk", "r&b", "rnb", "motown", "disco", "gospel"],
    "blues":      ["blues"],
    "classical":  ["classical", "orchestra", "baroque", "opera", "piano", "compositional"],
    "latin":      ["latin", "reggaeton", "salsa", "cumbia", "flamenco", "bachata", "rumba"],
    "reggae":     ["reggae", "dub", "dancehall"],
    "world":      ["afrobeat", "world", "celtic", "balkan", "fado"],
}

# adyacencias entre familias (grafo no dirigido)
ADJACENCY: dict[str, set[str]] = {
    "rock":       {"punk", "metal", "indie", "blues", "folk"},
    "punk":       {"rock", "metal", "indie", "reggae"},
    "metal":      {"rock", "punk"},
    "indie":      {"rock", "punk", "pop", "folk", "electronic"},
    "electronic": {"indie", "pop", "hiphop"},
    "hiphop":     {"soul", "electronic", "reggae"},
    "jazz":       {"blues", "soul", "classical", "world"},
    "pop":        {"indie", "electronic", "soul"},
    "folk":       {"rock", "indie", "blues", "world"},
    "soul":       {"blues", "jazz", "hiphop", "pop"},
    "blues":      {"rock", "jazz", "soul", "folk"},
    "classical":  {"jazz", "world"},
    "latin":      {"world", "pop", "reggae"},
    "reggae":     {"punk", "hiphop", "latin", "world"},
    "world":      {"latin", "jazz", "folk", "reggae", "classical"},
}

# tags de Last.fm representativos por familia, para tag.getTopAlbums
FAMILY_TAGS: dict[str, list[str]] = {
    "rock":       ["rock", "classic rock", "psychedelic rock", "garage rock"],
    "punk":       ["punk", "punk rock", "post-punk", "hardcore punk"],
    "metal":      ["metal", "heavy metal", "thrash metal", "stoner rock"],
    "indie":      ["indie", "indie rock", "alternative", "shoegaze"],
    "electronic": ["electronic", "techno", "house", "ambient", "idm"],
    "hiphop":     ["hip-hop", "rap", "trip-hop"],
    "jazz":       ["jazz", "bebop", "jazz fusion", "vocal jazz"],
    "pop":        ["pop", "synthpop", "dance"],
    "folk":       ["folk", "singer-songwriter", "americana", "country"],
    "soul":       ["soul", "funk", "rnb", "disco"],
    "blues":      ["blues", "blues rock"],
    "classical":  ["classical", "contemporary classical"],
    "latin":      ["latin", "flamenco", "reggaeton"],
    "reggae":     ["reggae", "dub", "ska"],
    "world":      ["world music", "afrobeat"],
}


def family_of(genre_label: str) -> str | None:
    """Familia a la que pertenece un género de Spotify/Last.fm (o None)."""
    g = genre_label.lower()
    best, best_len = None, 0
    for family, keywords in FAMILY_KEYWORDS.items():
        for kw in keywords:
            if kw in g and len(kw) > best_len:
                best, best_len = family, len(kw)
    return best


def profile_families(genre_labels: list[str]) -> dict[str, int]:
    """Cuenta cuántas veces aparece cada familia en una lista de géneros."""
    counts: dict[str, int] = {}
    for g in genre_labels:
        fam = family_of(g)
        if fam:
            counts[fam] = counts.get(fam, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def adjacent_families(profile: dict[str, int]) -> list[str]:
    """Familias vecinas de tu perfil en las que apenas escuchas."""
    core = {f for f, c in profile.items() if c >= max(profile.values(), default=1) * 0.25}
    total = sum(profile.values()) or 1
    out = set()
    for fam in core:
        out |= ADJACENCY.get(fam, set())
    # adyacente = vecina pero con poca presencia en tu perfil (<10%)
    return sorted(f for f in out if profile.get(f, 0) / total < 0.10)


def distant_families(profile: dict[str, int]) -> list[str]:
    """Familias ni en tu perfil ni adyacentes a él: la sorpresa."""
    core = set(profile.keys())
    near = set()
    for fam in core:
        near |= ADJACENCY.get(fam, set())
    return sorted(f for f in FAMILY_KEYWORDS if f not in core and f not in near) or \
           sorted(f for f in FAMILY_KEYWORDS if f not in core)
