"""Calendarios mensuales de lanzamientos: lo que la prensa dice que ha salido.

Tres fuentes que en la práctica sacaron lo que se le escapaba al resto:

- Dod Magazine, "Nuevos discos <año>": una página por año con un encabezado
  por mes (OCTUBRE), un subencabezado por fecha (02/10/2026) y una lista
  "Artista - Título".
- Binaural, "Lanzamientos de discos en <mes> de <año>": un artículo por mes;
  se encuentra por su RSS.
- Bandcamp Daily: "The Best Punk on Bandcamp, <Month> <Year>" y las
  "Essential Releases" semanales (se buscan en el archivo de prensa).

ESTO ES SCRAPING Y SE ROMPERÁ: cualquier rediseño de una de esas webs deja
el parser leyendo cero discos. Por eso vive aparte, cada fuente falla por
separado y un fallo nunca tumba monthly_releases: solo deja un aviso claro
("Dod Magazine: 0 discos leídos, puede que haya cambiado la web"). Los
nombres que salen de aquí NO se creen sin más: se comprueban en Deezer.

Se pueden añadir páginas a mano para un mes en datos/calendarios.json:
{"urls": {"2026-10": ["https://…"]}} (se leen con el parser genérico).
"""
import html as html_mod
import json
import logging
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx

from . import press

log = logging.getLogger("playlist_lab.calendarios")

CONFIG = Path(__file__).resolve().parents[2] / "datos" / "calendarios.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; playlist-lab/0.3; uso personal)",
           "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"}

MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
            "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
MESES_EN = ["january", "february", "march", "april", "may", "june", "july",
            "august", "september", "october", "november", "december"]

_BLOQUES = re.compile(r"<\s*(br|/p|/li|/h[1-6]|/div|li|h[1-6]|p|tr|/tr)\b[^>]*>", re.I)
_ETIQUETAS = re.compile(r"<[^>]+>")
_SCRIPTS = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
_FECHA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
# "Artista - Título", "Artista – Título", "Artista — «Título»", "Artista: Título"
_ITEM = re.compile(r"^\s*[•·\-\*]?\s*(?P<a>[^–—:\n]{1,60}?)\s+[-–—]\s+(?P<t>.{1,120})$")
_ITEM_DOS_PUNTOS = re.compile(r"^\s*(?P<a>[^:\n]{1,60}?):\s+[«“\"](?P<t>[^»”\"]{1,120})[»”\"]")
_BAND = re.compile(r'"band_name"\s*:\s*"(?P<a>[^"]{1,80})"')
_TITULO_JSON = re.compile(r'"(?:album_title|title)"\s*:\s*"(?P<t>[^"]{1,150})"')
# Lo que tiene forma de "Artista - Título" sin ser un disco: el título del
# propio artículo y los titulares de la barra lateral ("[Entrevista] X - …",
# "Grupo - Disco | Crítica").
_NO_ES_ARTISTA = re.compile(r"^\W*\[|^lanzamientos de discos", re.I)
_NO_ES_TITULO = re.compile(r"\|\s*(cr[ií]tica|rese[nñ]a|review|entrevista)\s*$", re.I)
# En Bandcamp, la cuenta que publica puede ser el sello y no el grupo.
_SELLO = re.compile(r"\b(records|recordings)\s*$", re.I)


def html_a_lineas(html: str) -> list[str]:
    """Texto de la página, una línea por bloque (párrafo, elemento de lista…)."""
    texto = _SCRIPTS.sub(" ", html or "")
    texto = _BLOQUES.sub("\n", texto)
    texto = html_mod.unescape(_ETIQUETAS.sub("", texto))
    return [re.sub(r"\s+", " ", l).strip() for l in texto.split("\n") if l.strip()]


def _limpio(s: str) -> str:
    return s.strip().strip("«»“”\"'").strip()


def _item(linea: str) -> tuple[str, str] | None:
    m = _ITEM.match(linea) or _ITEM_DOS_PUNTOS.match(linea)
    if not m:
        return None
    a, t = _limpio(m.group("a")), _limpio(m.group("t"))
    if len(a) < 2 or len(a.split()) > 7 or not t or _FECHA.search(a):
        return None
    if _NO_ES_ARTISTA.search(a) or _NO_ES_TITULO.search(t):
        return None
    return a, t


def parsear_dod(html: str, mes: str) -> list[dict]:
    """Dod Magazine: OCTUBRE → 02/10/2026 → "Artista - Título"."""
    anio, m = int(mes[:4]), int(mes[5:7])
    nombre_mes = MESES_ES[m - 1]
    dentro, fecha, out = False, None, []
    for linea in html_a_lineas(html):
        plano = re.sub(r"\s*(de\s+)?\d{4}$", "", linea.lower().strip(" :#*"))
        if plano in MESES_ES:
            dentro = plano == nombre_mes
            fecha = None
            continue
        f = _FECHA.fullmatch(linea.strip(" *:"))
        if f:
            d, mm, aa = int(f.group(1)), int(f.group(2)), int(f.group(3))
            fecha = f"{aa:04d}-{mm:02d}-{d:02d}" if (aa, mm) == (anio, m) else None
            dentro = dentro or fecha is not None
            continue
        if not (dentro and fecha):
            continue
        par = _item(linea)
        if par:
            out.append({"artista": par[0], "titulo": par[1], "fecha": fecha})
    return out


def parsear_generico(html: str, mes: str) -> list[dict]:
    """Cualquier artículo con líneas "Artista – Título" (Binaural y similares).

    Si la página pone fechas ("2 de octubre", "02/10/2026") se apuntan; si
    no, la fecha la pondrá Deezer al comprobar el disco.
    """
    anio, m = int(mes[:4]), int(mes[5:7])
    fecha, out = None, []
    patron_dia = re.compile(rf"\b(\d{{1,2}}) de {MESES_ES[m - 1]}\b", re.I)
    for linea in html_a_lineas(html):
        f = _FECHA.search(linea)
        d = patron_dia.search(linea)
        if len(linea) < 40 and (f or d):
            if f and (int(f.group(3)), int(f.group(2))) == (anio, m):
                fecha = f"{anio:04d}-{m:02d}-{int(f.group(1)):02d}"
            elif d:
                fecha = f"{anio:04d}-{m:02d}-{int(d.group(1)):02d}"
            continue
        par = _item(linea)
        if par:
            out.append({"artista": par[0], "titulo": par[1], "fecha": fecha})
    return out


def parsear_bandcamp(html: str) -> list[dict]:
    """Bandcamp Daily: los reproductores incrustados llevan band_name y title
    en JSON; si no aparecen, se prueba con líneas "Artista – Título".

    Se descarta lo publicado a nombre de un sello ("Total Punk Records"): ahí
    band_name no es el artista, y buscarlo en Deezer no llevaría al disco.
    """
    texto = html_mod.unescape(html or "")
    out, vistos = [], set()
    for b in _BAND.finditer(texto):
        ventana = texto[max(0, b.start() - 600): b.end() + 600]
        t = _TITULO_JSON.search(ventana)
        if not t:
            continue
        par = (b.group("a").strip(), t.group("t").strip())
        if _SELLO.search(par[0]):
            continue
        if par not in vistos:
            vistos.add(par)
            out.append({"artista": par[0], "titulo": par[1], "fecha": None})
    if out:
        return out
    for linea in html_a_lineas(html):
        par = _item(linea)
        if par and not _SELLO.search(par[0]) and par not in vistos:
            vistos.add(par)
            out.append({"artista": par[0], "titulo": par[1], "fecha": None})
    return out


class CalendariosClient:
    def __init__(self, http: httpx.Client | None = None):
        self._http = http or httpx.Client(timeout=25, headers=HEADERS,
                                          follow_redirects=True)
        self.peticiones = 0

    def _texto(self, url: str, exigir_en_url: str | None = None) -> str:
        """HTML de la página. Con `exigir_en_url`, falla si ha redirigido a otra:
        una portada también tiene líneas "X - Y", y se leerían como discos."""
        self.peticiones += 1
        resp = self._http.get(url)
        resp.raise_for_status()
        if exigir_en_url and exigir_en_url not in str(resp.url):
            raise RuntimeError(f"{url} redirige a {resp.url}")
        return resp.text

    def _rss(self, url: str) -> list[tuple[str, str]]:
        """(título, enlace) de un feed RSS/Atom."""
        try:
            raiz = ET.fromstring(self._texto(url))
        except (httpx.HTTPError, ET.ParseError, ValueError):
            return []
        out = []
        for it in raiz.iter():
            if it.tag.split("}")[-1] not in ("item", "entry"):
                continue
            titulo = enlace = ""
            for hijo in it:
                tag = hijo.tag.split("}")[-1]
                if tag == "title":
                    titulo = (hijo.text or "").strip()
                elif tag == "link":
                    enlace = (hijo.text or hijo.get("href") or "").strip()
            if titulo and enlace:
                out.append((titulo, enlace))
        return out

    # ---------- cada fuente ----------

    def dod(self, mes: str) -> list[dict]:
        url = f"https://www.dodmagazine.es/nuevos-discos-{mes[:4]}/"
        return parsear_dod(self._texto(url), mes)

    def binaural(self, mes: str) -> list[dict]:
        anio, nombre = mes[:4], MESES_ES[int(mes[5:7]) - 1]
        buscado = re.compile(rf"lanzamientos.*{nombre}.*{anio}", re.I)
        urls = [enlace for titulo, enlace in self._rss("https://www.binaural.es/feed/")
                if buscado.search(titulo)]
        if not urls:
            urls = ["https://www.binaural.es/lanzamientos/"
                    f"lanzamientos-de-discos-en-{nombre}-de-{anio}/"]
        out = []
        for url in urls[:2]:
            html = self._texto(url, exigir_en_url=f"{nombre}-de-{anio}")
            out.extend(parsear_generico(html, mes))
        return out

    def bandcamp(self, mes: str) -> list[dict]:
        anio, m = int(mes[:4]), int(mes[5:7])
        nombre_en = MESES_EN[m - 1]
        urls = [f"https://daily.bandcamp.com/best-punk/"
                f"the-best-punk-on-bandcamp-{nombre_en}-{anio}"]
        # Las "Essential Releases" son semanales: se buscan en el archivo de
        # prensa (el feed de Bandcamp Daily ya se archiva con music_press).
        siguiente = f"{anio + (m == 12):04d}-{(m % 12) + 1:02d}"
        for item in press.cargar_archivo():
            fecha = item.get("date") or ""
            if (item.get("source") == "Bandcamp Daily"
                    and "essential releases" in (item.get("title") or "").lower()
                    and mes <= fecha[:7] <= siguiente and item.get("url")):
                urls.append(item["url"])
        out, errores = [], 0
        for url in dict.fromkeys(urls):
            try:
                out.extend(parsear_bandcamp(self._texto(url)))
            except httpx.HTTPError:
                errores += 1
        if errores == len(urls):
            raise RuntimeError("no se pudo abrir ninguna página")
        return out

    def a_mano(self, mes: str) -> list[dict]:
        try:
            urls = (json.loads(CONFIG.read_text(encoding="utf-8")).get("urls") or {}).get(mes) or []
        except (OSError, json.JSONDecodeError):
            return []
        out = []
        for url in urls:
            out.extend(parsear_generico(self._texto(url), mes))
        return out

    def del_mes(self, mes: str) -> dict:
        """Todos los calendarios. Cada uno falla por separado y deja aviso."""
        fuentes = {"Dod Magazine": self.dod, "Binaural": self.binaural,
                   "Bandcamp Daily": self.bandcamp, "calendarios.json": self.a_mano}
        discos, avisos, leidos = [], [], {}
        for nombre, fn in fuentes.items():
            try:
                filas = fn(mes)
            except Exception as e:  # noqa: BLE001 — scraping: nada puede tumbar la tanda
                log.warning("Calendario %s falló: %s", nombre, e)
                avisos.append(f"{nombre}: no se pudo leer ({type(e).__name__}: {e}); "
                              "faltan sus discos")
                leidos[nombre] = None
                continue
            leidos[nombre] = len(filas)
            if not filas and nombre != "calendarios.json":
                avisos.append(f"{nombre}: 0 discos leídos para {mes}; puede que la "
                              "web haya cambiado o que aún no haya publicado el mes")
            for f in filas:
                f["fuente"] = nombre
            discos.extend(filas)
        return {"discos": discos, "avisos": avisos, "leidos": leidos}
