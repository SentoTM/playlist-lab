"""Retocar listas ya creadas: añadir, quitar, mover, renombrar y borrar.

Por qué existe: sin esto, cada retoque creaba una lista nueva y él tenía
que borrar la vieja a mano (pasó al meter Mogwai en la de Laxness).

Cómo funciona: se lee la lista, se calcula el orden nuevo aquí y se
reescribe entera. Solo se tocan listas que son suyas.
"""
import re

from . import library
from .clients.spotify import SpotifyClient
from .text import norm

_ID = re.compile(r"playlist[/:]([A-Za-z0-9]{22})")


def localizar(sp: SpotifyClient, lista: str) -> dict:
    """Una playlist SUYA por id, enlace o nombre (exacto o parcial único)."""
    texto = (lista or "").strip()
    m = _ID.search(texto)
    pid = m.group(1) if m else (texto if re.fullmatch(r"[A-Za-z0-9]{22}", texto) else None)
    yo = (sp.me() or {}).get("id")
    if pid:
        info = sp.playlist_info(pid)
        if not info:
            raise ValueError(f"No encuentro la playlist {pid}")
    else:
        mias = [p for p in sp.my_playlists() if (p.get("owner") or {}).get("id") == yo]
        exactas = [p for p in mias if norm(p.get("name", "")) == norm(texto)]
        parecidas = exactas or [p for p in mias if norm(texto) in norm(p.get("name", ""))]
        if not parecidas:
            raise ValueError(f"No tienes ninguna playlist que se llame como '{texto}'")
        if len(parecidas) > 1:
            nombres = ", ".join(f"«{p['name']}» ({p['id']})" for p in parecidas[:8])
            raise ValueError(f"Hay varias que encajan con '{texto}': {nombres}. "
                             "Pásame el id o el enlace de la que sea.")
        info = parecidas[0]
    if (info.get("owner") or {}).get("id") != yo:
        raise ValueError(f"«{info.get('name')}» no es tuya: Spotify solo deja "
                         "editar las listas que ha creado tu cuenta.")
    return info


def _fila(t: dict) -> dict:
    return {"uri": t.get("uri"), "title": t.get("name", ""),
            "artist": ", ".join(a.get("name", "") for a in t.get("artists") or []),
            "album": (t.get("album") or {}).get("name", ""),
            "ms": t.get("duration_ms") or 0}


def _casa(fila: dict, patron: str) -> bool:
    """'album: Artista – Disco', 'Artista – Canción' o solo 'Artista'."""
    p = patron.strip()
    es_album = p.lower().startswith(("album:", "álbum:"))
    if es_album:
        p = p.split(":", 1)[1].strip()
    try:
        artista, titulo = library.parse_item(p)
    except ValueError:
        artista, titulo = p, ""
    if norm(artista) not in norm(fila["artist"]):
        return False
    if not titulo:
        return True
    campo = fila["album"] if es_album else fila["title"]
    return norm(titulo) in norm(campo) or norm(campo).startswith(norm(titulo))


def editar(sp: SpotifyClient, lista: str, anadir: list[str], quitar: list[str],
           despues_de: str = "", al_principio: bool = False,
           nombre: str = "", descripcion: str = "") -> dict:
    info = localizar(sp, lista)
    pid = info["id"]
    actuales = [_fila(t) for t in sp.playlist_tracks(pid, 1000)]
    antes = len(actuales)

    quitadas, sin_casar = [], []
    for patron in quitar:
        casan = [f for f in actuales if _casa(f, patron)]
        if not casan:
            sin_casar.append(patron)
        quitadas += casan
        actuales = [f for f in actuales if not _casa(f, patron)]

    nuevas, no_resueltas, resueltos = [], [], []
    if anadir:
        res = library.resolve_ordered(sp, anadir)
        no_resueltas = res["unresolved"]
        resueltos = res["resolved"]
        nuevas = [{"uri": u} for u in res["uris"]]

    if nuevas:
        if al_principio:
            pos = 0
        elif despues_de:
            idx = [i for i, f in enumerate(actuales) if _casa(f, despues_de)]
            if not idx:
                raise ValueError(f"No encuentro '{despues_de}' en la lista para "
                                 "colocar detrás lo nuevo. No he tocado nada.")
            pos = idx[-1] + 1
        else:
            pos = len(actuales)
        actuales = actuales[:pos] + nuevas + actuales[pos:]

    if quitar or nuevas:
        sp.replace_playlist_items(pid, [f["uri"] for f in actuales if f.get("uri")])
    sp.update_playlist_details(pid, nombre or None, descripcion[:300] if descripcion else None)

    return {
        "playlist": nombre or info.get("name"), "id": pid,
        "url": (info.get("external_urls") or {}).get("spotify"),
        "canciones_antes": antes, "canciones_ahora": len(actuales),
        "quitadas": [f"{f['artist']} – {f['title']}" for f in quitadas][:40] or None,
        "no_encontradas_para_quitar": sin_casar or None,
        "anadidas": [r["input"] for r in resueltos] or None,
        "no_resueltas": no_resueltas or None,
        "renombrada": bool(nombre), "resueltos": resueltos,
    }


def borrar(sp: SpotifyClient, lista: str, confirmar: bool) -> dict:
    info = localizar(sp, lista)
    n = len(sp.playlist_tracks(info["id"], 1000))
    if not confirmar:
        return {"pendiente_de_confirmar": True, "playlist": info.get("name"),
                "id": info["id"], "canciones": n,
                "nota": ("Pregúntale si de verdad quiere borrarla y, si dice que sí, "
                         "vuelve a llamar con confirmar=True y el id. Se puede "
                         "recuperar desde spotify.com → Cuenta → Recuperar playlists.")}
    sp.unfollow_playlist(info["id"])
    return {"borrada": True, "playlist": info.get("name"), "id": info["id"],
            "nota": "Recuperable desde spotify.com → Cuenta → Recuperar playlists."}
