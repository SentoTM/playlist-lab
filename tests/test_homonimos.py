"""Homónimos en resolve, sin red."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import cache, homonimos, library

UK, DC = "u" * 8, "d" * 8


class FakeMB:
    def __init__(self, con_enlace=True):
        self.con_enlace = con_enlace

    def buscar_artistas(self, nombre):
        return [{"artist": "Embrace", "mbid": UK, "score": 100,
                 "desambiguacion": "UK rock band", "zona": "Huddersfield", "tags": []},
                {"artist": "Embrace", "mbid": DC, "score": 100,
                 "desambiguacion": "US hardcore band", "zona": "Washington, D.C.", "tags": []}]

    def relaciones(self, mbid):
        rels = [{"type": "free streaming",
                 "url": {"resource": f"https://open.spotify.com/artist/sp{mbid}"}}]
        return {"id": mbid, "name": "Embrace", "relations": rels if self.con_enlace else []}


class FakeSpotify:
    def artist_albums(self, artista_id, limit=20, artist_name=None, max_paginas=4):
        return [{"id": f"disco-{artista_id}", "name": "Embrace", "album_type": "album",
                 "total_tracks": 16, "release_date": "1987"}]

    def search_track(self, consulta, limit=3):
        return [{"id": "t-uk", "name": "Dance of Days", "artists": [{"id": f"sp{UK}"}]},
                {"id": "t-dc", "name": "Dance of Days", "artists": [{"id": f"sp{DC}"}]}]


class ConCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(cache, "ARCHIVO", Path(tmp.name) / "c.json"),
                  mock.patch.object(cache, "_memoria", None)):
            p.start()
            self.addCleanup(p.stop)


class TestPreparar(ConCache):
    def test_disco_del_artista_correcto(self):
        original = "album: Embrace (Washington) – Embrace"
        lista, originales, fuera = homonimos.preparar(FakeSpotify(), [original], "", FakeMB())
        self.assertEqual(lista, [f"Embrace – Embrace | spotify:album:disco-sp{DC}"])
        self.assertEqual(originales[lista[0]], original)
        self.assertEqual(fuera, [])

    def test_cancion_filtra_por_artista(self):
        lista, _, _ = homonimos.preparar(FakeSpotify(), ["Embrace (hardcore) – Dance of Days"],
                                         "", FakeMB())
        self.assertTrue(lista[0].endswith("spotify:track:t-dc"))

    def test_sin_enlace_queda_sin_resolver(self):
        lista, _, fuera = homonimos.preparar(FakeSpotify(), ["album: Embrace (Washington) – Embrace"],
                                             "", FakeMB(con_enlace=False))
        self.assertEqual(lista, [])
        self.assertEqual(fuera[0]["type"], "album")

    def test_sin_pista_no_toca_nada(self):
        items = ["album: Fugazi – Repeater", "Hoover – Electrolux | spotify:track:abc"]
        self.assertEqual(homonimos.preparar(FakeSpotify(), items, "", FakeMB())[0], items)

    def test_parentesis_que_no_es_pista_se_respeta(self):
        item = "album: Embrace (xyz) – Embrace"
        self.assertEqual(homonimos.preparar(FakeSpotify(), [item], "", FakeMB())[0], [item])


class FakeBusqueda:
    def search_album(self, q, limit=10):
        return [{"id": "uk", "name": "Embrace", "album_type": "album", "total_tracks": 9,
                 "release_date": "2025", "artists": [{"id": "a1", "name": "Embrace"}]},
                {"id": "dc", "name": "Embrace", "album_type": "album", "total_tracks": 16,
                 "release_date": "1987", "artists": [{"id": "a2", "name": "Embrace"}]}]


class TestAviso(unittest.TestCase):
    def test_detecta_homonimos_en_la_busqueda(self):
        self.assertEqual(library.find_album(FakeBusqueda(), "Embrace", "Embrace")["_homonimos"], 2)

    def test_mismo_artista_no_avisa(self):
        sp = mock.Mock()
        sp.search_album.return_value = [
            {"id": "a", "name": "Repeater", "album_type": "album", "total_tracks": 11,
             "release_date": "1990", "artists": [{"id": "f", "name": "Fugazi"}]},
            {"id": "b", "name": "Repeater", "album_type": "album", "total_tracks": 14,
             "release_date": "2004", "artists": [{"id": "f", "name": "Fugazi"}]}]
        self.assertNotIn("_homonimos", library.find_album(sp, "Fugazi", "Repeater"))

    def test_aviso_en_la_fila(self):
        fila = {}
        library._aviso_homonimo(fila, {"homonimos": 2}, "Embrace")
        self.assertIn("2 artistas", fila["aviso_homonimo"])
        fila = {}
        library._aviso_homonimo(fila, {}, "Fugazi")
        self.assertEqual(fila, {})


if __name__ == "__main__":
    unittest.main()
