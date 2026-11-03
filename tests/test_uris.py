"""resolve y create_playlist con URIs: lo ya resuelto no se vuelve a buscar."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import cache, library

ID_DISCO = "4aawyAB9vmqN3uQ7FjRGTy"
ID_CANCION = "0VjIjW4GlUZAMYd2vXMi3b"


class FakeSpotify:
    """Spotify de mentira que cuenta y prohíbe buscar."""

    def __init__(self):
        self.llamadas = []

    def album(self, album_id):
        self.llamadas.append(("album", album_id))
        return {"id": album_id, "name": "Dopamine Chamber", "release_date": "2026-10-16",
                "artists": [{"name": "Fontaines D.C."}],
                "external_urls": {"spotify": f"https://open.spotify.com/album/{album_id}"},
                "tracks": {"items": [{"name": f"Canción {i}", "uri": f"spotify:track:{i:022d}",
                                      "duration_ms": 200000} for i in range(10)]}}

    def __getattr__(self, nombre):
        if nombre.startswith("search"):
            raise AssertionError(f"No debía buscar en Spotify ({nombre})")
        raise AttributeError(nombre)


class TestURIs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(cache, "ARCHIVO", Path(tmp.name) / "c.json"),
                  mock.patch.object(cache, "_memoria", None)):
            p.start()
            self.addCleanup(p.stop)

    def test_separar(self):
        self.assertEqual(library.separar_uri(f"Fontaines D.C. – Dopamine Chamber | spotify:album:{ID_DISCO}"),
                         ("Fontaines D.C. – Dopamine Chamber", ("album", ID_DISCO)))
        self.assertEqual(library.separar_uri(f"https://open.spotify.com/intl-es/track/{ID_CANCION}?si=x")[1],
                         ("track", ID_CANCION))
        self.assertEqual(library.separar_uri("Lori Meyers – DISONANCIA"),
                         ("Lori Meyers – DISONANCIA", None))

    def test_ordenado_sin_buscar(self):
        sp = FakeSpotify()
        res = library.resolve_ordered(sp, [
            f"album: Fontaines D.C. – Dopamine Chamber | spotify:album:{ID_DISCO}",
            f"Niños – Bravos | spotify:track:{ID_CANCION}"])
        self.assertEqual(sp.llamadas, [("album", ID_DISCO)])   # una sola petición
        self.assertEqual(len(res["uris"]), 11)
        self.assertEqual(res["resolved"][0]["uri"], f"spotify:album:{ID_DISCO}")
        self.assertEqual(res["resolved"][1]["artist"], "Niños")
        self.assertFalse(res["unresolved"])

    def test_por_separado_y_memorizado(self):
        sp = FakeSpotify()
        for _ in range(2):   # resolve y después create_playlist
            res = library.resolve_items(sp, [f"spotify:album:{ID_DISCO}"],
                                        [f"spotify:track:{ID_CANCION}"])
        self.assertEqual(sp.llamadas, [("album", ID_DISCO)])
        self.assertEqual([r["type"] for r in res["resolved"]], ["track", "album"])


if __name__ == "__main__":
    unittest.main()
