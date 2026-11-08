"""Tests de monthly_releases sin red: Deezer y MusicBrainz con respuestas grabadas.

Las fixtures (tests/fixtures/*.json) siguen el formato exacto de las APIs
públicas de Deezer y MusicBrainz. Para regrabarlas con datos reales:
`python scripts/grabar_fixtures.py` (ese sí sale a internet).

    python -m unittest discover -s tests
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from app import cache, novedades_mes as nm
from app.clients import musicbrainz as mb_mod
from app.clients.calendarios import (CalendariosClient, parsear_bandcamp, parsear_dod,
                                     parsear_generico)
from app.clients.deezer import DeezerClient, DeezerError, _Almacen, _Ritmo
from app.text import clave, titulo_base

FIX = Path(__file__).parent / "fixtures"
DEEZER = json.loads((FIX / "deezer.json").read_text(encoding="utf-8"))
MB = json.loads((FIX / "musicbrainz.json").read_text(encoding="utf-8"))
SIN_DATOS = {"error": {"type": "DataException", "message": "no data", "code": 800}}
# La búsqueda real de Deezer no distingue puntos ni tildes ("Basht" encuentra
# a "Basht."): las fixtures de búsqueda se sirven por clave normalizada.
BUSQUEDAS = {clave(k.split("?q=", 1)[1]): v for k, v in DEEZER.items() if "?q=" in k}


def transporte_deezer(cuota_primero: set | None = None, contador: list | None = None):
    """Sirve las fixtures; con `cuota_primero` la primera petición a esas rutas
    devuelve el error de cuota de Deezer (un 200 con error code 4)."""
    cuota_primero = set(cuota_primero or ())

    def handler(req: httpx.Request) -> httpx.Response:
        if contador is not None:
            contador.append(req.url.path)
        q = req.url.params.get("q")
        k = f"{req.url.path}?q={q}" if q is not None else req.url.path
        if k in cuota_primero:
            cuota_primero.discard(k)
            return httpx.Response(200, json={"error": {
                "type": "Exception", "message": "Quota limit exceeded", "code": 4}})
        if q is not None:
            return httpx.Response(200, json=BUSQUEDAS.get(clave(q), {"data": [], "total": 0}))
        return httpx.Response(200, json=DEEZER.get(k, SIN_DATOS))
    return httpx.MockTransport(handler)


def deezer(**kw) -> DeezerClient:
    return DeezerClient(http=httpx.Client(transport=transporte_deezer(**kw)),
                        almacen=_Almacen(None), ritmo=_Ritmo(1000, 0.01),
                        dormir=lambda _s: None)


def musicbrainz() -> mb_mod.MusicbrainzClient:
    def handler(req: httpx.Request) -> httpx.Response:
        consulta = req.url.params.get("query", "")
        for artista, datos in MB.items():
            if f'artist:"{artista}"' in consulta:
                return httpx.Response(200, json=datos)
        return httpx.Response(200, json={"release-groups": [], "count": 0})
    cli = mb_mod.MusicbrainzClient()
    cli._http = httpx.Client(transport=httpx.MockTransport(handler))
    return cli


class FakeStatsfm:
    def __init__(self, vida, meses):
        self.vida, self.meses = vida, meses

    def top_artists_todos(self, range_="lifetime", min_streams=10, **_):
        filas = self.vida if range_ == "lifetime" else self.meses
        return [{"name": n, "streams": s, "genres": g} for n, s, g in filas
                if s >= min_streams]


class FakeLastfm:
    peticiones = 0
    username = "prueba"

    def __init__(self, tops=(), similares=None):
        self.tops, self.similares = list(tops), similares or {}

    def user_top_artists(self, period="overall", limit=30):
        return [{"name": n, "playcount": p} for n, p in self.tops]

    def similar_artists(self, artist, limit=15):
        return self.similares.get(artist, [])


class FakeKexp:
    def __init__(self, emisiones=None):
        self.emisiones = emisiones or {}

    def emisiones_de(self, artista, desde_dias=365):
        return self.emisiones.get(artista, [])


class FakeCalendarios:
    peticiones = 0

    def __init__(self, discos):
        self.discos = discos

    def del_mes(self, mes):
        return {"discos": [d for d in self.discos if d["mes"] == mes],
                "avisos": ["Binaural: 0 discos leídos para " + mes], "leidos": {}}


INDIE = ["spanish indie", "indie rock"]
PUNK = ["post-punk", "irish post-punk"]
VIDA = [
    ("Arde Bogotá", 420, INDIE), ("LA MILAGROSA", 35, INDIE), ("Basht", 60, PUNK),
    ("Lori Meyers", 900, INDIE), ("Fontaines D.C.", 1500, PUNK), ("La 126", 25, INDIE),
    ("Viva Belgrado", 80, ["spanish post-hardcore", "screamo"]), ("Niños", 40, INDIE),
    ("Wet Leg", 300, PUNK), ("Squid", 200, PUNK), ("IDLES", 700, PUNK),
    ("Carolina Durante", 500, INDIE), ("Gilla Band", 150, PUNK), ("Gurriers", 90, PUNK),
    ("Kasabian", 40, ["britpop", "rock"]), ("Bloc Party", 300, ["indie rock", "post-punk revival"]),
    ("Protomartyr", 30, PUNK), ("Amyl and The Sniffers", 250, ["punk", "pub rock"]),
    ("Viagra Boys", 400, PUNK), ("Biznaga", 120, ["spanish punk"]),
    ("Grupo Olvidado", 4, INDIE),
]
MESES = [("Arde Bogotá", 120, INDIE), ("Fontaines D.C.", 300, PUNK), ("Gilla Band", 60, PUNK),
         ("Lori Meyers", 20, INDIE), ("Biznaga", 30, ["spanish punk"])]
SIMILARES = {"Gilla Band": [{"name": "Adult DVD", "match": 0.71}, {"name": "Lejano", "match": 0.1}],
             "Biznaga": [{"name": "Aiko el grupo", "match": 0.64}]}
CALENDARIO = [
    {"mes": "2026-10", "artista": "Dummy", "titulo": "do you love the color of the sky?",
     "fecha": "2026-10-16", "fuente": "Dod Magazine"},
    {"mes": "2026-10", "artista": "Pardoner", "titulo": "Target Practice",
     "fecha": None, "fuente": "Bandcamp Daily"},
    {"mes": "2026-10", "artista": "Lori Meyers", "titulo": "DISONANCIA",
     "fecha": "2026-10-15", "fuente": "Dod Magazine"},
]
VET = {"Dummy": ["shoegaze", "noise pop", "indie rock"],
       "Pardoner": ["punk", "indie rock", "noise rock"]}


def vet_falso(nombres):
    return {"candidatos": [{"artist": n, "nivel": "nuevo", "etiquetas": VET.get(n, ["jazz"]),
                            "oyentes": 20000, "senales": []} for n in nombres]}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        parches = [
            mock.patch.object(cache, "ARCHIVO", Path(self.tmp.name) / "cache.json"),
            mock.patch.object(cache, "_memoria", None),
            mock.patch.object(nm.radar_mod, "cargar",
                              lambda: {"candidatos": [], "de_los_que_sigues": []}),
            mock.patch.object(nm.press, "PressClient"),
            mock.patch.object(nm.press, "cargar_archivo", lambda: [
                {"source": "Mondo Sonoro", "date": "2026-10-20",
                 "title": "Niños – Bravos: crítica", "summary": "El disco de Niños, Bravos…"}]),
            mock.patch.object(mb_mod.time, "sleep", lambda _s: None),
        ]
        for p in parches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def calcular(self, mes):
        return nm.calcular(mes, FakeStatsfm(VIDA, MESES), FakeLastfm(similares=SIMILARES),
                           deezer(), musicbrainz(), FakeKexp(), FakeCalendarios(CALENDARIO),
                           None, {}, vet_falso)


class TestTexto(unittest.TestCase):
    def test_clave_casa_variantes(self):
        self.assertEqual(clave("Basht."), clave("Basht"))
        self.assertEqual(clave("MAQUINA."), clave("Máquina"))
        self.assertEqual(clave("Fontaines D.C."), clave("Fontaines DC"))
        self.assertEqual(clave("The Murder Capital"), clave("Murder Capital"))
        self.assertEqual(clave("Simon & Garfunkel"), clave("Simon and Garfunkel"))
        self.assertNotEqual(clave("Niños"), clave("Niños Mutantes"))

    def test_titulo_base_quita_ediciones(self):
        self.assertEqual(titulo_base("moisturizer (deluxe)"), titulo_base("moisturizer"))
        self.assertEqual(titulo_base("viagr aboys (Japanese Deluxe Edition)"),
                         titulo_base("viagr aboys"))
        self.assertEqual(titulo_base("Disco - 20th Anniversary Edition"), "disco")


class TestFiltros(unittest.TestCase):
    def test_por_titulo(self):
        casos = {
            "Truth or Consequence (Live from El Coyote)": "directo",
            "Crispy Skin (Remixes)": "remezclas",
            "Grace (Remix)": "remezclas",
            "moisturizer (deluxe)": "edición deluxe o especial",
            "viagr aboys (Japanese Deluxe Edition)": "edición deluxe o especial",
            "Loveless (Remastered)": "reedición o remasterización",
            "OK Computer (10th Anniversary)": "aniversario",
            "Dune (Original Motion Picture Soundtrack)": "banda sonora",
            "BBC Sessions": "sesiones",
            "Grandes éxitos": "recopilatorio",
            "Live at the Roundhouse": "directo",
            "En directo desde Madrid": "directo",
        }
        for titulo, motivo in casos.items():
            with self.subTest(titulo=titulo):
                self.assertEqual(nm.motivo_por_titulo(titulo), motivo)

    def test_no_se_pasa_de_frenada(self):
        for titulo in ("Live Through This", "Dopamine Chamber", "NECESITO ESTÍMULOS",
                       "Manufacturas del Club de la Gente Sola (MCGS)",
                       "Mientras el Guadalquivir fluye y fluye y fluye",
                       "do you love the color of the sky?", "Señales Brutales"):
            with self.subTest(titulo=titulo):
                self.assertIsNone(nm.motivo_por_titulo(titulo))

    def test_tipos_y_reediciones(self):
        anteriores = [{"title": "moisturizer", "release_date": "2025-07-11", "record_type": "album"}]
        self.assertEqual(nm.filtro_previo({"title": "x", "record_type": "single"}, []), "single")
        self.assertEqual(nm.filtro_previo({"title": "x", "record_type": "compile"}, []),
                         "recopilatorio")
        self.assertIn("reedición", nm.filtro_previo(
            {"title": "Moisturizer", "record_type": "album"}, anteriores))
        self.assertIsNone(nm.filtro_previo({"title": "Bravos", "record_type": "album"}, anteriores))
        self.assertEqual(nm.filtro_ficha({"record_type": "ep", "nb_tracks": 3}), "EP de 3 canciones")
        self.assertIsNone(nm.filtro_ficha({"record_type": "ep", "nb_tracks": 4}))
        self.assertEqual(nm.filtro_ficha({"title": "Pugnello", "record_type": "album",
                                          "nb_tracks": 14},
                                         [{"title": "Pugnello", "nb_tracks": 10}]),
                         "edición ampliada de un disco anterior")


class TestDeezer(unittest.TestCase):
    def test_exige_que_el_nombre_case(self):
        self.assertIsNone(deezer().artista("Las Petunias"))

    def test_casa_aunque_cambie_la_puntuacion(self):
        a = deezer().artista("Basht")
        self.assertEqual(a["name"], "Basht.")

    def test_homonimos_se_guardan(self):
        a = deezer().artista("Niños")
        self.assertEqual(a["nb_fan"], 90000)          # el de más fans…
        self.assertIn("llamados", a["aviso"])
        self.assertEqual([o["id"] for o in a["otros"]], [18])  # …y el otro, por si acaso

    def test_reintenta_si_deezer_pide_calma(self):
        dz = deezer(cuota_primero={"/search/artist?q=Gurriers"})
        self.assertEqual(dz.artista("Gurriers")["id"], 32)
        self.assertEqual(dz.esperas_por_cuota, 1)

    def test_cache_no_repite_peticiones(self):
        dz = deezer()
        dz.albumes(dz.artista("Gurriers")["id"])
        antes = dz.peticiones
        dz.albumes(dz.artista("Gurriers")["id"])
        self.assertEqual(dz.peticiones, antes)

    def test_sin_respuesta_avisa_en_vez_de_callar(self):
        def roto(_req):
            raise httpx.ConnectError("sin red")
        dz = DeezerClient(http=httpx.Client(transport=httpx.MockTransport(roto)),
                          almacen=_Almacen(None), ritmo=_Ritmo(1000, 0.01),
                          dormir=lambda _s: None)
        with self.assertRaises(DeezerError):
            dz.artista("Gurriers")
        self.assertTrue(dz.fallos)

    def test_ritmo_no_pasa_de_n_por_ventana(self):
        r = _Ritmo(maximo=3, ventana=0.3)
        import time
        t0 = time.monotonic()
        for _ in range(4):
            r.esperar()
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)


class TestMusicbrainz(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(mb_mod.time, "sleep", lambda _s: None)
        p.start()
        self.addCleanup(p.stop)

    def test_solo_el_mismo_artista_y_con_subtipos(self):
        filas = musicbrainz().lanzamientos_entre("Biznaga", "2026-10-01", "2026-10-31")
        self.assertEqual([f["album"] for f in filas], ["Una ciudad feliz", "En directo en el Price"])
        self.assertEqual(filas[1]["subtipos"], ["Live"])


class TestCalendarios(unittest.TestCase):
    def test_dod(self):
        html = """<h3>SEPTIEMBRE</h3><p><strong>25/09/2026</strong></p>
        <ul><li>Gilla Band - Pugnello</li></ul>
        <h3>OCTUBRE</h3><p><strong>02/10/2026</strong></p>
        <ul><li>Arde Bogotá - Manufacturas del Club de la Gente Sola (MCGS)</li>
        <li>Wishy - Nature&#8217;s Pill</li></ul>
        <p><strong>16/10/2026</strong></p><ul><li>Dummy - do you love the color of the sky?</li></ul>
        <h3>NOVIEMBRE</h3><p><strong>06/11/2026</strong></p><ul><li>Otro - Disco</li></ul>"""
        filas = parsear_dod(html, "2026-10")
        self.assertEqual([(f["artista"], f["fecha"]) for f in filas],
                         [("Arde Bogotá", "2026-10-02"), ("Wishy", "2026-10-02"),
                          ("Dummy", "2026-10-16")])
        self.assertEqual(filas[1]["titulo"], "Nature’s Pill")

    def test_bandcamp_reproductores(self):
        html = ('<bcaudioplayer data-player-infos="[{&quot;band_name&quot;:&quot;Pardoner'
                '&quot;,&quot;title&quot;:&quot;Target Practice&quot;}]"></bcaudioplayer>')
        self.assertEqual(parsear_bandcamp(html)[0]["artista"], "Pardoner")

    def test_generico_con_fechas(self):
        html = "<p>23 de octubre</p><p>La 126 – NADA PUEDE HACERNOS MAL</p>"
        f = parsear_generico(html, "2026-10")[0]
        self.assertEqual((f["artista"], f["fecha"]), ("La 126", "2026-10-23"))

    def test_generico_ignora_lo_que_no_son_discos(self):
        html = ("<h1>Lanzamientos de discos en... octubre de 2026 - Binaural</h1>"
                "<p>16 de octubre</p><p>Fontaines D.C. - Dopamine Chamber</p>"
                "<p>´[Entrevista] Queens Of The Stone Age - En 2024 no teníamos ni idea</p>"
                "<p>Fontaines DC - Dopamine Chamber | Crítica</p>")
        self.assertEqual([(f["artista"], f["titulo"]) for f in parsear_generico(html, "2026-10")],
                         [("Fontaines D.C.", "Dopamine Chamber")])

    def test_bandcamp_descarta_sellos(self):
        html = ('<bcaudioplayer data-player-infos="[{&quot;band_name&quot;:&quot;Total Punk '
                'Records&quot;,&quot;title&quot;:&quot;Real Simple&quot;}]"></bcaudioplayer>'
                '<bcaudioplayer data-player-infos="[{&quot;band_name&quot;:&quot;Water Damage'
                '&quot;,&quot;title&quot;:&quot;Repair&quot;}]"></bcaudioplayer>')
        self.assertEqual([f["artista"] for f in parsear_bandcamp(html)], ["Water Damage"])

    def _binaural(self, responder):
        http = httpx.Client(transport=httpx.MockTransport(responder), follow_redirects=True)
        return CalendariosClient(http=http).binaural("2026-10")

    def test_binaural_va_al_articulo_del_mes(self):
        vistas = []

        def responder(req):
            vistas.append(req.url.path)
            if req.url.path == "/feed/":
                return httpx.Response(200, text="<rss><channel></channel></rss>")
            return httpx.Response(200, text="<p>2 de octubre</p><p>Blossoms - Songs</p>")

        filas = self._binaural(responder)
        self.assertEqual(vistas[-1], "/lanzamientos/lanzamientos-de-discos-en-octubre-de-2026/")
        self.assertEqual(filas[0]["artista"], "Blossoms")

    def test_binaural_no_lee_la_portada_si_redirige(self):
        def responder(req):
            if req.url.path == "/feed/":
                return httpx.Response(200, text="<rss><channel></channel></rss>")
            if req.url.path == "/":
                return httpx.Response(200, text="<p>Un titular - cualquiera</p>")
            return httpx.Response(301, headers={"Location": "https://www.binaural.es/"})

        with self.assertRaisesRegex(RuntimeError, "redirige"):
            self._binaural(responder)


class TestPuntuacion(unittest.TestCase):
    def disco(self, **kw):
        d = {"relacion": "de_los_tuyos", "tipo": "album", "afinidad": 0.5,
             "escuchas_artista": {"total": 100, "ultimos_6_meses": 0, "lastfm": 0},
             "fuentes_externas": [], "dudoso": False, "vecino_de": []}
        d.update(kw)
        return d

    def test_lo_reciente_pesa_mas(self):
        reciente = self.disco(escuchas_artista={"total": 100, "ultimos_6_meses": 60, "lastfm": 0})
        antiguo = self.disco(escuchas_artista={"total": 160, "ultimos_6_meses": 0, "lastfm": 0})
        self.assertGreater(nm.puntuar(reciente), nm.puntuar(antiguo))

    def test_album_mas_que_ep_y_avales_suman(self):
        self.assertGreater(nm.puntuar(self.disco()), nm.puntuar(self.disco(tipo="ep")))
        self.assertGreater(nm.puntuar(self.disco(fuentes_externas=["KEXP", "Dod Magazine"])),
                           nm.puntuar(self.disco(fuentes_externas=["KEXP"])) + 2.5)

    def test_dudoso_resta(self):
        self.assertLess(nm.puntuar(self.disco(dudoso=True)), nm.puntuar(self.disco()))

    def test_afinidad(self):
        mios = {"post-punk": 1.0, "spanish indie": 0.8}
        self.assertEqual(nm.afinidad(["post-punk"], mios)[0], 1.0)
        self.assertEqual(nm.afinidad(["irish post-punk"], mios)[0], 0.5)
        self.assertEqual(nm.afinidad(["reggaeton"], mios)[0], 0)


class TestAceptacion(Base):
    def titulos(self, res):
        return {(d["artista"], d["titulo"]) for d in res["discos"]}

    def test_octubre(self):
        res = self.calcular("2026-10")
        t = self.titulos(res)
        for esperado in [
                ("Arde Bogotá", "Manufacturas del Club de la Gente Sola (MCGS)"),
                ("LA MILAGROSA", "NECESITO ESTÍMULOS"), ("Basht", "Poor Advice"),
                ("Lori Meyers", "DISONANCIA"), ("Fontaines D.C.", "Dopamine Chamber"),
                ("La 126", "NADA PUEDE HACERNOS MAL"),
                ("Viva Belgrado", "Mientras el Guadalquivir fluye y fluye y fluye"),
                ("Niños", "Bravos"), ("Dummy", "do you love the color of the sky?"),
                ("Pardoner", "Target Practice"), ("Biznaga", "Una ciudad feliz")]:
            with self.subTest(disco=esperado):
                self.assertIn(esperado, t)
        for fuera in [("Wet Leg", "moisturizer (deluxe)"), ("Squid", "Crispy Skin (Remixes)"),
                      ("IDLES", "Grace (Remix)"), ("Niños", "Canciones para bailar"),
                      ("Carolina Durante", "Tres canciones"), ("Biznaga", "En directo en el Price")]:
            with self.subTest(fuera=fuera):
                self.assertNotIn(fuera, t)
        motivos = {(d["artista"], d["titulo"]): d["motivo"] for d in res["descartados"]}
        self.assertEqual(motivos[("Wet Leg", "moisturizer (deluxe)")], "edición deluxe o especial")
        self.assertEqual(motivos[("Squid", "Crispy Skin (Remixes)")], "remezclas")
        self.assertTrue(motivos[("Niños", "Canciones para bailar")].startswith("homónimo"))
        self.assertEqual(motivos[("Carolina Durante", "Tres canciones")], "EP de 3 canciones")
        self.assertEqual(res["estadisticas"]["peticiones_a_spotify"], 0)

    def test_octubre_relaciones_y_porque(self):
        res = self.calcular("2026-10")
        por = {d["artista"]: d for d in res["discos"]}
        self.assertEqual(por["Dummy"]["relacion"], "internacional")
        self.assertIn("Dod Magazine", por["Dummy"]["fuentes"])
        self.assertEqual(por["Lori Meyers"]["relacion"], "de_los_tuyos")
        self.assertIn("Dod Magazine", por["Lori Meyers"]["fuentes"])
        self.assertIn("Mondo Sonoro", por["Niños"]["fuentes"])
        self.assertFalse(por["Niños"]["dudoso"])
        self.assertTrue(por["Arde Bogotá"]["porque"].startswith("Lo has escuchado 420 veces"))
        self.assertEqual(por["Biznaga"]["ids"]["deezer"], None)
        self.assertTrue(por["Biznaga"]["ids"]["musicbrainz"])
        # Ordenado por afinidad: Arde Bogotá (escuchado ahora) va por delante de La 126
        orden = [d["artista"] for d in res["discos"]]
        self.assertLess(orden.index("Arde Bogotá"), orden.index("La 126"))

    def test_septiembre(self):
        res = self.calcular("2026-09")
        t = self.titulos(res)
        for esperado in [("Gilla Band", "Pugnello"), ("Gurriers", "Nobody's Coming To Save You"),
                         ("Adult DVD", "Adult DVD"), ("Aiko el grupo", "Señales Brutales"),
                         ("Kasabian", "Act 3"), ("Bloc Party", "Anatomy of a Brief Romance"),
                         ("Protomartyr", "Hotel Usona")]:
            with self.subTest(disco=esperado):
                self.assertIn(esperado, t)
        self.assertNotIn(("Amyl and The Sniffers", "Truth or Consequence (Live from El Coyote)"), t)
        self.assertNotIn(("Viagra Boys", "viagr aboys (Japanese Deluxe Edition)"), t)
        por = {d["artista"]: d for d in res["discos"]}
        self.assertEqual(por["Adult DVD"]["relacion"], "órbita")
        self.assertIn("Gilla Band", por["Adult DVD"]["porque"])
        # nada de octubre en la lista de septiembre
        self.assertTrue(all(d["fecha"].startswith("2026-09") for d in res["discos"]))

    def test_vetados_no_salen(self):
        res = nm.calcular("2026-10", FakeStatsfm(VIDA, MESES), FakeLastfm(), deezer(), None,
                          FakeKexp(), FakeCalendarios([]), None,
                          {"wet leg": "nunca más", "lori meyers": "no es lo mío"}, vet_falso)
        self.assertNotIn("Lori Meyers", {d["artista"] for d in res["discos"]})

    def test_lo_poco_escuchado_no_se_rastrea(self):
        res = self.calcular("2026-10")
        self.assertEqual(res["estadisticas"]["de_los_tuyos"], len(VIDA) - 1)


REAL = FIX / "deezer_real.json"


@unittest.skipUnless(REAL.exists(), "sin tests/fixtures/deezer_real.json: "
                                    "grábalo con scripts/grabar_fixtures.py")
class TestAceptacionReal(unittest.TestCase):
    """La prueba de aceptación contra respuestas REALES de Deezer, sin red."""

    def setUp(self):
        reales = json.loads(REAL.read_text(encoding="utf-8"))
        busquedas = {clave(k.split("?q=", 1)[1]): v for k, v in reales.items() if "?q=" in k}

        def handler(req):
            q = req.url.params.get("q")
            if q is not None:
                return httpx.Response(200, json=busquedas.get(clave(q), {"data": []}))
            return httpx.Response(200, json=reales.get(req.url.path, SIN_DATOS))
        self.dz = DeezerClient(http=httpx.Client(transport=httpx.MockTransport(handler)),
                               almacen=_Almacen(None), ritmo=_Ritmo(1000, 0.01),
                               dormir=lambda _s: None)

    def entran(self, artista, mes, generos=INDIE):
        inicio, fin = nm.rango_mes(mes)
        r = nm.rastrear_artista(self.dz, artista, inicio, fin, 0, generos)
        return {titulo_base(d["titulo"]) for d in r.get("entran", [])}

    def test_salen(self):
        for artista, titulo, mes in [
                ("Arde Bogotá", "Manufacturas del Club de la Gente Sola", "2026-10"),
                ("LA MILAGROSA", "NECESITO ESTÍMULOS", "2026-10"), ("Basht.", "Poor Advice", "2026-10"),
                ("Lori Meyers", "DISONANCIA", "2026-10"), ("Fontaines D.C.", "Dopamine Chamber", "2026-10"),
                ("La 126", "NADA PUEDE HACERNOS MAL", "2026-10"),
                ("Viva Belgrado", "Mientras el Guadalquivir fluye y fluye y fluye", "2026-10"),
                ("Niños", "Bravos", "2026-10"),
                ("Gilla Band", "Pugnello", "2026-09"),
                ("Gurriers", "Nobody's Coming To Save You", "2026-09"),
                ("Adult DVD", "Adult DVD", "2026-09"), ("Aiko el grupo", "Señales Brutales", "2026-09")]:
            with self.subTest(disco=(artista, titulo)):
                self.assertIn(titulo_base(titulo), self.entran(artista, mes))

    def test_no_salen(self):
        for artista, titulo, mes in [
                ("Amyl and The Sniffers", "Truth or Consequence (Live from El Coyote)", "2026-09"),
                ("Wet Leg", "moisturizer (deluxe)", "2026-09"), ("Wet Leg", "moisturizer (deluxe)", "2026-10"),
                ("Viagra Boys", "viagr aboys (Japanese Deluxe Edition)", "2026-09"),
                ("Viagra Boys", "viagr aboys (Japanese Deluxe Edition)", "2026-10")]:
            with self.subTest(disco=(artista, titulo, mes)):
                inicio, fin = nm.rango_mes(mes)
                r = nm.rastrear_artista(self.dz, artista, inicio, fin, 0, PUNK)
                self.assertNotIn(titulo, {d["titulo"] for d in r.get("entran", [])})
        for artista in ("Squid", "IDLES"):
            for mes in ("2026-09", "2026-10"):
                inicio, fin = nm.rango_mes(mes)
                r = nm.rastrear_artista(self.dz, artista, inicio, fin, 0, PUNK)
                self.assertFalse([d for d in r.get("entran", []) if "remix" in d["titulo"].lower()])


class TestDiscosCortos(unittest.TestCase):
    def test_album_de_dos_canciones_es_un_single(self):
        self.assertEqual(nm.filtro_ficha({"record_type": "album", "nb_tracks": 2, "duration": 240}),
                         "disco de solo 2 canciones")

    def test_pocas_pistas_largas_si_es_disco(self):
        self.assertIsNone(nm.filtro_ficha({"record_type": "album", "nb_tracks": 3, "duration": 2400}))


if __name__ == "__main__":
    unittest.main()
