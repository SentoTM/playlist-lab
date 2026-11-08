"""Presupuesto de Spotify y status corto, sin red."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app import cache
from app.clients.spotify import SpotifyPresupuesto, _Presupuesto


class TestPresupuesto(unittest.TestCase):
    def llenar(self, p, n):
        for _ in range(n):
            p.gastar("GET", "/artists/x/albums")

    def test_frena_al_llegar_al_limite(self):
        p = _Presupuesto(limite=2, reserva=1)
        self.llenar(p, 2)
        with self.assertRaises(SpotifyPresupuesto) as e:
            p.gastar("GET", "/artists/x/albums")
        self.assertIn("Spotify sigue limitando la app", str(e.exception))

    def test_reserva_para_resolver(self):
        p = _Presupuesto(limite=2, reserva=1)
        self.llenar(p, 2)
        p.gastar("GET", "/search")
        with self.assertRaises(SpotifyPresupuesto):
            p.gastar("GET", "/albums/x")

    def test_escribir_nunca_se_frena(self):
        p = _Presupuesto(limite=1, reserva=0)
        self.llenar(p, 1)
        p.gastar("POST", "/me/playlists")
        p.gastar("PUT", "/playlists/x/tracks")

    def test_la_ventana_libera(self):
        p = _Presupuesto(limite=1, reserva=0, ventana=10)
        with mock.patch("app.clients.spotify.time.time", return_value=1000.0):
            self.llenar(p, 1)
        with mock.patch("app.clients.spotify.time.time", return_value=1011.0):
            self.llenar(p, 1)
            self.assertEqual(p.estado()["usadas"], 1)


class ConCache(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for p in (mock.patch.object(cache, "ARCHIVO", Path(tmp.name) / "c.json"),
                  mock.patch.object(cache, "_memoria", None)):
            p.start()
            self.addCleanup(p.stop)


class TestEstadoCache(ConCache):
    def test_resumen_y_detalle(self):
        cache.guardar("res3:a", 1)
        cache.guardar("res3:b", 1)
        cache.guardar("biblioteca", 1)
        r = cache.estado()
        self.assertEqual(r, {"entradas": 3, "por_tipo": {"res3": 2, "biblioteca": 1}})
        self.assertEqual(len(cache.estado(True)), 3)


if __name__ == "__main__":
    unittest.main()
