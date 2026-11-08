"""Qué funciona: etiquetas, balance y detalle de pistas, sin red."""
import datetime as dt
import unittest

from app import balance, huella


def fila(**k):
    return {"tipo": "album", "escuchas": 0, "estado": "sin tocar", "prendio": False,
            "dias_con_escuchas": 0, "otras_cosas_del_artista": 0, **k}


class TestEtiquetas(unittest.TestCase):
    def filas(self):
        return [{"input": "album: Fugazi – Repeater | spotify:album:x", "type": "album",
                 "artist": "Fugazi", "album": "Repeater"},
                {"input": "Hoover – Electrolux", "type": "track", "artist": "Hoover",
                 "title": "Electrolux"}]

    def test_casa_por_texto_y_por_nombre(self):
        f = self.filas()
        avisos = balance.aplicar_etiquetas(f, [
            {"pieza": f[0]["input"], "papel": "Ancla", "origen": "criterio"},
            {"pieza": "Hoover - Electrolux", "papel": "puerta oscura", "conocido": True}])
        self.assertEqual(avisos, [])
        self.assertEqual((f[0]["papel"], f[0]["origen"]), ("ancla", "criterio"))
        self.assertEqual(f[1]["papel"], "puerta_oscura")
        self.assertTrue(f[1]["conocido"])

    def test_avisa_sin_romper(self):
        f = self.filas()
        avisos = balance.aplicar_etiquetas(f, [{"pieza": "Nadie – Nada", "papel": "ancla"},
                                               {"pieza": "Hoover – Electrolux", "origen": "tarot"}])
        self.assertEqual(len(avisos), 2)
        self.assertEqual(f[1]["origen"], "tarot")

    def test_elemento_guarda_etiquetas_y_respeta_recorte(self):
        r = {"type": "album", "artist": "A", "album": "B", "n_tracks": 1, "papel": "ancla",
             "_uris": ["u1"], "_pistas": [{"nombre": "Uno", "uri": "u1"}, {"nombre": "Extra", "uri": "u2"}]}
        e = huella._elemento(r)
        self.assertEqual(e["lista_pistas"], ["Uno"])
        self.assertEqual(e["papel"], "ancla")


class TestResumir(unittest.TestCase):
    def test_agrega_y_excluye(self):
        listas = {
            "abierta": {"elementos": [
                fila(escuchas=9, estado="entero", prendio=True, dias_con_escuchas=2,
                     papel="ancla", origen="radar"),
                fila(papel="salida", origen="criterio"),
                fila(escuchas=2, estado="aún es pronto", papel="salida", origen="radar"),
                fila(tipo="cancion", escuchas=1, estado="escuchado", prendio=True,
                     otras_cosas_del_artista=9, papel="puente", origen="criterio"),
                fila(tipo="cancion", escuchas=1, estado="escuchado", prendio=True,
                     papel="temazo", origen="prensa", conocido=True)]},
            "sin abrir": {"elementos": [fila(papel="ancla", origen="radar")]},
            "antigua": {"elementos": [fila(escuchas=5)]},
        }
        r = balance.resumir(listas)
        self.assertEqual(r["listas_analizadas"], 1)
        self.assertEqual(r["listas_sin_abrir"], ["sin abrir"])
        self.assertEqual(r["listas_sin_etiquetas"], 1)
        self.assertEqual(r["piezas_aun_pronto"], 1)
        origen = {f["grupo"]: f for f in r["por_origen"]}
        self.assertEqual(origen["radar"]["piezas"], 1)     # sin la de "aún es pronto"
        self.assertEqual(origen["radar"]["pct_prendieron"], 100)
        self.assertEqual(origen["criterio"]["piezas"], 1)  # el puente no cuenta
        self.assertNotIn("prensa", origen)                 # lo conocido tampoco
        self.assertEqual(origen["radar"]["muestra"], "poca")
        self.assertEqual({f["grupo"]: f["piezas"] for f in r["por_papel"]}["temazo"], 1)

    def test_sin_datos(self):
        self.assertTrue(balance.resumir({"a": {"elementos": [fila()]}})["sin_datos"])


class TestPistas(unittest.TestCase):
    def test_repetidas_y_sin_escuchar(self):
        hoy = dt.date(2026, 11, 9)
        ts = int(dt.datetime(2026, 11, 9, 12).timestamp())
        scrobbles = [{"artist": "A", "album": "D", "track": t, "uts": ts + i}
                     for i, t in enumerate(["Uno", "Uno", "Uno", "Dos"])]
        listas = {"L": {"fecha": "2026-11-08", "elementos": [
            {"tipo": "album", "artista": "A", "album": "D", "pistas": 3, "papel": "ancla",
             "lista_pistas": ["Uno", "Dos", "Tres"]}]}}
        f = huella.calcular(scrobbles, [], listas, hoy)["L"]["elementos"][0]
        self.assertEqual(f["pistas_repetidas"], ["Uno ×3"])
        self.assertEqual(f["pistas_sin_escuchar"], ["Tres"])
        self.assertEqual(f["papel"], "ancla")

    def test_todas_iguales_no_destaca_ninguna(self):
        self.assertEqual(huella._detalle_pistas(
            [{"track": "Uno"}, {"track": "Uno"}, {"track": "Dos"}, {"track": "Dos"}], None), {})

    def test_listas_antiguas_siguen_funcionando(self):
        listas = {"L": {"fecha": "2026-10-01", "elementos": [
            {"tipo": "album", "artista": "A", "album": "D", "pistas": 3}]}}
        f = huella.calcular([], [], listas, dt.date(2026, 11, 9))["L"]["elementos"][0]
        self.assertNotIn("pistas_repetidas", f)
        self.assertEqual(f["estado"], "sin tocar")


if __name__ == "__main__":
    unittest.main()
