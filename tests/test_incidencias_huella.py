"""Last.fm con un solo scrobble y semillas que llegan con URI."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import semillas
from app.clients.lastfm import LastfmClient

SCROBBLE = {"artist": {"#text": "Fugazi"}, "album": {"#text": "Repeater"},
            "name": "Merchandise", "date": {"uts": "1794160000"}}
SONANDO = {"artist": {"#text": "Fugazi"}, "album": {"#text": "Repeater"},
           "name": "Blueprint", "@attr": {"nowplaying": "true"}}
ID_DISCO = "7AHbaRIYnilUwe981nZpmi"


def recientes(track):
    c = LastfmClient("clave", "usuario")
    respuesta = {"recenttracks": {"track": track, "@attr": {"totalPages": "1"}}}
    with mock.patch.object(c, "_get", return_value=respuesta):
        return c.recent_tracks(1)


class TestRecientes(unittest.TestCase):
    def test_un_solo_scrobble_llega_como_objeto(self):
        self.assertEqual([t["track"] for t in recientes(SCROBBLE)], ["Merchandise"])

    def test_solo_lo_que_suena_no_cuenta(self):
        self.assertEqual(recientes(SONANDO), [])

    def test_lista_y_vacio(self):
        self.assertEqual(len(recientes([SCROBBLE, SONANDO])), 1)
        self.assertEqual(recientes([]), [])


class TestPlantar(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        p = mock.patch.object(semillas, "RUTA", Path(tmp.name) / "s.json")
        p.start()
        self.addCleanup(p.stop)

    def test_con_prefijo_y_uri(self):
        s = semillas.plantar("L", f"album: Drive Like Jehu – Yank Crime | spotify:album:{ID_DISCO}", "h")
        self.assertEqual((s["artista"], s["obra"], s["tipo"]), ("Drive Like Jehu", "Yank Crime", "album"))

    def test_uri_de_disco_sin_prefijo(self):
        s = semillas.plantar("L", f"Drive Like Jehu – Yank Crime | spotify:album:{ID_DISCO}", "h")
        self.assertEqual((s["obra"], s["tipo"]), ("Yank Crime", "album"))

    def test_sin_uri_no_cambia(self):
        s = semillas.plantar("L", "Fugazi – Waiting Room", "h")
        self.assertEqual((s["artista"], s["obra"], s["tipo"]), ("Fugazi", "Waiting Room", "cancion"))


if __name__ == "__main__":
    unittest.main()
