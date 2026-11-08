"""Conexiones entre artistas, sin red."""
import unittest

import httpx

from app import conexiones
from app.clients import musicbrainz as mb_mod

FUGAZI, EMBRACE, GUY, IAN, RITES, EMBRACE_UK = "f" * 8, "e" * 8, "g" * 8, "i" * 8, "r" * 8, "u" * 8


def rel(tipo, otro, nombre, direccion="forward", **extra):
    return {"type": tipo, "direction": direccion, "target-type": "artist",
            "artist": {"id": otro, "name": nombre}, **extra}


GRAFO = {
    IAN: {"id": IAN, "name": "Ian MacKaye", "relations": [
        rel("member of band", FUGAZI, "Fugazi", begin="1987", end="2003"),
        rel("member of band", EMBRACE, "Embrace", begin="1985", end="1986"),
        rel("producer", RITES, "Ignorado")]},
    GUY: {"id": GUY, "name": "Guy Picciotto", "relations": [
        rel("member of band", FUGAZI, "Fugazi"), rel("member of band", RITES, "Rites of Spring")]},
    FUGAZI: {"id": FUGAZI, "name": "Fugazi", "relations": [
        rel("member of band", IAN, "Ian MacKaye", "backward", begin="1987", end="2003"),
        rel("member of band", GUY, "Guy Picciotto", "backward"),
        {"type": "wikidata", "target-type": "url",
         "url": {"resource": "https://www.wikidata.org/wiki/Q1"}},
        {"type": "free streaming", "target-type": "url",
         "url": {"resource": "https://open.spotify.com/artist/abc"}}]},
    EMBRACE: {"id": EMBRACE, "name": "Embrace", "relations": [
        rel("member of band", IAN, "Ian MacKaye", "backward", begin="1985", end="1986"),
        {"type": "wikidata", "target-type": "url",
         "url": {"resource": "https://www.wikidata.org/wiki/Q2"}}]},
}
CANDIDATOS = {
    "Fugazi": [{"artist": "Fugazi", "mbid": FUGAZI, "score": 100, "desambiguacion": "",
                "zona": "Washington, D.C.", "tags": []}],
    "Embrace": [{"artist": "Embrace", "mbid": EMBRACE_UK, "score": 100,
                 "desambiguacion": "UK rock band", "zona": "Huddersfield", "tags": []},
                {"artist": "Embrace", "mbid": EMBRACE, "score": 100,
                 "desambiguacion": "US hardcore band", "zona": "Washington, D.C.", "tags": []}],
}


class FakeMB:
    def __init__(self, fallan=()):
        self.fallan, self.llamadas = set(fallan), []

    def buscar_artistas(self, nombre):
        return CANDIDATOS.get(nombre, [])

    def relaciones(self, mbid):
        self.llamadas.append(mbid)
        return None if mbid in self.fallan else GRAFO.get(mbid, {"id": mbid, "name": mbid})

    def sellos_por_id(self, mbid):
        return ["Dischord Records", "[no label]"]


class FakeWD:
    def influido_por(self, qid):
        return [{"qid": "Q9", "nombre": "Minor Threat"}] + (
            [{"qid": "Q1", "nombre": "Fugazi"}] if qid == "Q2" else [])

    def productores(self, qid):
        return [{"qid": "Q7", "nombre": "Don Zientara", "obra": f"Disco de {qid}"}]


class TestAristas(unittest.TestCase):
    def test_sentido_y_periodo(self):
        hechos = [a["hecho"] for a in conexiones.aristas(GRAFO[FUGAZI])]
        self.assertIn("Ian MacKaye fue miembro de Fugazi (1987–2003)", hechos)
        self.assertEqual(len(hechos), 2)   # los enlaces url no conectan

    def test_ignora_tipos_no_listados(self):
        self.assertNotIn(RITES, [a["id"] for a in conexiones.aristas(GRAFO[IAN])])


class TestCaminos(unittest.TestCase):
    def vecinos(self, n):
        return conexiones.aristas(GRAFO.get(n, {"id": n, "name": n}))

    def test_miembro_compartido(self):
        r = conexiones.buscar_caminos(EMBRACE, FUGAZI, self.vecinos)
        self.assertEqual([[a["nombre"] for a in c] for c in r["caminos"]],
                         [["Ian MacKaye", "Fugazi"]])
        self.assertTrue(r["completa"])

    def test_camino_ordenado_de_a_hacia_b(self):
        c = conexiones.buscar_caminos(EMBRACE, RITES, self.vecinos)["caminos"][0]
        self.assertEqual([a["nombre"] for a in c][0], "Ian MacKaye")
        self.assertIn("Rites of Spring", c[-1]["hecho"])

    def test_sin_presupuesto_no_es_busqueda_completa(self):
        r = conexiones.buscar_caminos(EMBRACE, RITES, self.vecinos, max_consultas=1)
        self.assertEqual(r["caminos"], [])
        self.assertFalse(r["completa"])

    def test_un_fallo_no_es_busqueda_completa(self):
        r = conexiones.buscar_caminos("x", "y", lambda n: None)
        self.assertFalse(r["completa"])
        self.assertTrue(r["fallos"])


class TestConectar(unittest.TestCase):
    def test_homonimo_avisa_sin_pista(self):
        r = conexiones.identificar("Embrace", FakeMB())
        self.assertEqual(r["ficha"]["mbid"], EMBRACE_UK)
        self.assertEqual(len(r["homonimos"]), 1)
        self.assertTrue(r["avisos"])

    def test_pista_elige_homonimo(self):
        r = conexiones.identificar("Embrace (Washington hardcore)", FakeMB())
        self.assertEqual(r["ficha"]["mbid"], EMBRACE)
        self.assertFalse(r["avisos"])

    def test_extremo_a_extremo(self):
        r = conexiones.conectar("Embrace (Washington)", "Fugazi", FakeMB(), FakeWD())
        self.assertTrue(r["conectados"])
        self.assertEqual(r["caminos"][0]["via"], ["Ian MacKaye"])
        self.assertEqual(r["b"]["spotify"], "https://open.spotify.com/artist/abc")
        self.assertIn("Fugazi figura como influencia de Embrace",
                      [x["hecho"] for x in r["influencias"]])
        self.assertIn("Minor Threat", r["influencias"][1]["hecho"])
        self.assertIn("Don Zientara", r["productores"][0]["hecho"])
        self.assertEqual(len(r["mismo_sello"]), 1)     # "[no label]" no cuenta
        self.assertTrue(all("url" in h for h in r["caminos"][0]["hechos"]))

    def test_mismo_artista(self):
        self.assertIn("error", conexiones.conectar("Fugazi", "Fugazi", FakeMB(), FakeWD()))

    def test_desconocido(self):
        self.assertIn("error", conexiones.conectar("Nadie", "Fugazi", FakeMB(), FakeWD()))

    def test_peticion_real_a_musicbrainz(self):
        vistas = []

        def handler(req):
            vistas.append(req.url.params["inc"])
            return httpx.Response(200, json={"id": "x", "name": "n", "relations": []})

        c = mb_mod.MusicbrainzClient()
        c._http = httpx.Client(transport=httpx.MockTransport(handler))
        c._last = 0
        self.assertEqual(c.relaciones("x")["id"], "x")
        self.assertEqual(vistas, ["artist-rels url-rels"])


if __name__ == "__main__":
    unittest.main()
