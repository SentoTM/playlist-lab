# Playlist Lab 🎧

Centro de consulta y creación de playlists de Spotify **para usar conversando**. La app no recomienda por sí sola: reúne lo que sabe de ti (Spotify, Last.fm y stats.fm), lo expone a una IA por MCP y ejecuta lo que decidáis (buscar, verificar, crear la playlist). La curación la hace Claude o ChatGPT combinando tu perfil con su conocimiento de escenas, discografías y crítica.

¿Por qué así? El endpoint oficial `/recommendations` de Spotify (y related-artists, top-tracks, audio-features…) está cerrado para apps nuevas, y las heurísticas caseras (similares de Last.fm, tops de tus artistas) tienden a devolverte lo que ya conoces. Un buen curador con tus datos delante lo hace mejor.

## Qué hay

- **Servidor MCP** (`mcp_server.py`) — herramientas de consulta y creación (abajo). Stdio para Claude Desktop y `--http` para ChatGPT vía túnel.
- **Web mínima** (`app/main.py` + `static/index.html`, puerto 8888) — login OAuth PKCE de Spotify (una vez; token en `token.json`), estado de las fuentes, vista del perfil que ve la IA y el bloque de configuración del MCP listo para copiar.
- **Clientes** (`app/clients/`) — Spotify (PKCE, degrada ante endpoints cerrados), Last.fm (escuchas y mapa social), stats.fm (API interna, best-effort; validada sep. 2026), MusicBrainz (datos verificables), Wikipedia (contexto) y prensa por RSS.
- `app/taste.py` — perfil de gustos y artistas conocidos. `app/library.py` — búsqueda, resolución de "Artista – Canción/Álbum" y creación. `app/discovery.py` — novedades de tu órbita. `app/explore.py` — los modos de viaje.

### Presupuesto de fuentes

La cuota de Spotify en modo desarrollo se agota con facilidad —se comparte
entre todas tus consultas y tarda más de una hora en reponerse— y es el cuello
de botella de todo. Por eso la regla es: **Spotify solo al final, para
resolver y crear**. Lo de arriba sale de fuentes sin cuota.

| Para saber... | Fuente | Coste |
|---|---|---|
| Qué apoya una radio con criterio | KEXP (`api.kexp.org`) | sin cuota |
| Quién publica a quién (sellos) | MusicBrainz | sin cuota, 1 petición/segundo |
| Novedades del mundo | ListenBrainz | sin cuota |
| Qué escuchas y en qué época | stats.fm (`weeks`/`months`/`lifetime`) — trae escuchas, géneros e ids de Spotify | 1 petición por tanda, sin cuota |
| Qué conoces (filtro) | stats.fm + Last.fm + tu biblioteca cacheada | sin cuota |
| Tu biblioteca guardada | Spotify (nadie más la tiene) | ~18 peticiones, cacheadas **7 días** |
| Si conoces a un artista concreto | Last.fm `artist.getInfo` | sin cuota |
| Qué ha publicado alguien hace poco | MusicBrainz (fecha de primera edición) | sin cuota, 1 petición/segundo |
| Mapa de un género, escena, artistas similares | Last.fm + Wikipedia | sin cuota |
| Qué se está reseñando | RSS de prensa | sin cuota |
| Que un disco existe y crear la playlist | Spotify | unas pocas, solo para los finalistas |

`status` dice en todo momento si Spotify nos tiene frenados y qué hay en
caché. Si te frena, espera: insistir solo alarga el castigo.

### El reparto de papeles

El **criterio** lo pone el modelo: escenas, discografías, crítica, por qué dos grupos se parecen. Eso no se replica con reglas ni con bases de datos, y es lo que hace que las propuestas sean buenas. La **app** aporta lo que el modelo no puede saber: qué escuchas tú (Spotify, stats.fm), si conoces a un artista concreto aunque lo hayas oído cuatro veces (Last.fm), qué ha salido hace poco cerca de tu órbita (`new_releases`), qué se está reseñando ahora (`music_press`, la fecha de corte del modelo deja de importar) y si un año o un sello son ciertos (`verify` contra MusicBrainz, que es justo lo que un modelo inventa con aplomo).

Last.fm queda fuera de `taste_profile` a propósito: scrobleando solo desde Spotify, sus tops duplicaban los de Spotify. Se usa donde es irreemplazable, el playcount de cualquier artista.

## Puesta en marcha

1. Crea una app en https://developer.spotify.com/dashboard (Redirect URI exacta: `http://127.0.0.1:8888/callback`, API: Web API) y copia el **Client ID**.
2. `cp .env.example .env` y rellena `SPOTIFY_CLIENT_ID`, y opcionalmente `LASTFM_API_KEY` + `LASTFM_USERNAME` (https://www.last.fm/api/account/create) y `STATSFM_USERNAME` (perfil público).
3. Windows: doble clic en `setup.bat`. Otros: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt && uvicorn app.main:app --port 8888`.
4. En http://127.0.0.1:8888 pulsa **Iniciar sesión con Spotify**. Ya está: el MCP reutiliza ese token (y lo refresca solo).

Requiere Python 3.11+ y cuenta de Spotify Premium (Development Mode).

## Conectarlo a Claude Desktop

Ajustes → Desarrollador → Editar configuración, y pega el bloque que muestra la web (rutas ya rellenas). En general:

```json
{
  "mcpServers": {
    "playlist-lab": {
      "command": "D:\\ruta\\playlist_lab\\.venv\\Scripts\\python.exe",
      "args": ["D:\\ruta\\playlist_lab\\mcp_server.py"]
    }
  }
}
```

Reinicia Claude Desktop. Con el MCP registrado, las sesiones de Cowork vinculadas a tu ordenador también pueden usarlo.

## Conectarlo a ChatGPT (opcional, túnel)

ChatGPT solo acepta conectores MCP remotos. `mcp_http.bat` (o `python mcp_server.py --http`) sirve el MCP en `http://127.0.0.1:8877/mcp`; expónlo con `cloudflared tunnel --url http://127.0.0.1:8877` o `ngrok http 8877` y añade la URL pública + `/mcp` en Settings → Connectors → Developer mode. El túnel expone el servidor mientras esté abierto (quien tenga la URL podría crear playlists en tu cuenta): úsalo puntualmente.

## Herramientas MCP

| Consulta | |
|---|---|
| `status` | fuentes configuradas, sesión, avisos |
| `my_library` | canciones y álbumes guardados: guardar es decidir, repetir no |
| `my_playlists` / `playlist_contents` | cómo organiza él la música, y qué hay dentro de cada lista |
| `now_playing` | qué suena ahora mismo |
| `taste_profile` | tops por periodo con géneros, Last.fm reciente, histórico stats.fm, `fase_actual`, `generos_principales` |
| `listening_history` | tops en bruto por fuente/rango, paginable |
| `check_known` | si ya conoces a unos artistas y con qué evidencia (tops, biblioteca, seguidos, Last.fm, stats.fm) |
| `similar_artists` | similares según Last.fm, filtrando conocidos |
| `search` | búsqueda en Spotify (álbum/canción/artista, con filtros `year:`, `genre:`) |
| `album_info` | año, duración y pistas de un álbum |
| `new_releases` | discos recientes de tu órbita, separando "de los tuyos" y "alrededor" |
| `music_press` | reseñas y noticias recientes (Pitchfork, Quietus, Bandcamp Daily, Mondo Sonoro, Jenesaispop, Stereogum, BrooklynVegan) |
| `verify` | año real, sello, actividad y discografía según MusicBrainz |

| Radar | |
|---|---|
| `radar` | la lista viva de emergentes que no conoces, validada por varias fuentes; **la fuente de novedades** |
| `radar_update` | pasa el radar (1-2 min, en segundo plano) |
| `follow` / `unfollow` | vigilar sellos y artistas: el radar avisa de lo que saquen |

| Conocer y evaluar | |
|---|---|
| `vet_candidates` | valida una lista entera de candidatos de una vez: nivel de conocimiento, opinión, audiencia, KEXP y prensa |
| `dossier_artist` | todas las señales de un artista en una llamada: audiencia, ficha, sellos, KEXP, prensa y tu opinión |
| `radio_tastemaker` | qué pincha KEXP esta semana: curación humana, la mejor señal para emergentes |
| `played_on_radio` | si KEXP ha emitido a alguien, como aval de un desconocido |
| `labels_of` / `label_catalog` | con qué sello publica una banda y quiénes son sus compañeros de catálogo |
| `fresh_releases` | novedades del mundo según ListenBrainz, sin pasar por Spotify |
| `press_about` | qué se ha dicho de un artista en la prensa archivada |

| Exploración | |
|---|---|
| `explore_genre` | qué es un género, de dónde viene y quién lo puebla (incluye subgéneros finos) |
| `explore_era` | los clásicos de un género en una franja de años, por fecha de primera edición |
| `discover_emerging` | bandas recién publicadas y aún pequeñas (filtros `tag:new` / `tag:hipster` de Spotify) |
| `find_underrated` | separa lo de culto (público pequeño y devoto) de lo simplemente poco escuchado |
| `explore_scene` | qué se escucha en un país y qué grupos salieron de allí |
| `artist_context` | bio, ficha, formación, historia y discografía real de un artista |
| `artist_releases` | discografía en Spotify, de lo más nuevo a lo más viejo |

| Tu criterio | |
|---|---|
| `curation_guide` | cómo escuchas y cómo quieres que se te proponga música (`datos/perfil.md`) |
| `remember` | guarda lo que opinas de un artista, un disco o en general |
| `my_notes` | todo lo juzgado hasta ahora, agrupado por veredicto |
| `forget_note` | borra una nota cuando cambias de opinión |
| `rate` | guarda de una vez lo que opinas de varios discos |

| Creación | |
|---|---|
| `resolve` | verifica una propuesta ("Artista – Canción" / "Artista – Álbum") sin crear nada |
| `create_playlist` | crea la playlist con canciones y/o álbumes completos; informa de lo no encontrado |

Dos prompts guían el uso: `curar_playlist` (leer el perfil → proponer como un crítico, no como un algoritmo → filtrar conocidos → verificar → presentar y confirmar → crear) y `explorar` (situar el terreno → engancharlo con lo que ya escuchas → contar por qué importa → proponer un recorrido corto).

### Tu criterio y tus opiniones

Dos ficheros en `datos/` (fuera de git, porque son tuyos) sostienen la parte
que ninguna API puede dar.

**`perfil.md`** es la guía de curación: cómo escuchas, no qué escuchas.
Personalidad por encima de ejecución, qué entiendes por "garra", la regla de
que lo experimental entra si conserva un punto de anclaje, el formato de menú
de cinco, las cuatro dimensiones (afinidad, historia, frontera,
descubrimiento) y cómo mides el éxito. Lo edita uno a mano y `curation_guide`
lo sirve tal cual.

**`notas.json`** guarda tus juicios. Los datos de escucha dicen qué has
puesto, no qué te pareció: un disco que odiaste tras una escucha y otro que no
repites porque te lo sabes de memoria se ven idénticos desde fuera.
`remember` registra el veredicto con tus palabras y el motivo. La escala es la
tuya, y esto importa: *sin pena ni gloria* y *no es para mí pero lo entiendo*
**no descartan nada**, porque para ti una recomendación no fracasa por no
gustarte. Solo *nunca más* y *no es lo mío* sacan al artista del
descubrimiento. `check_known` devuelve tu opinión junto a la evidencia de
escucha, así que al proponer se ve de un vistazo qué pasó con eso.

`scripts/sembrar_notas.py` hace la carga inicial a partir de lo ya escuchado.

### El radar

La IA solo buscaba novedades si se le ocurría en mitad de una conversación, y
entonces tiraba de su memoria, que tiene fecha de corte. El radar invierte el
flujo: se pasa solo (`radar.bat`, o `radar_update` desde el chat), recoge
candidatos de fuentes independientes —qué apuesta KEXP y quién tiene sesión en
directo, qué publican los sellos que sigues (`datos/seguimiento.json`), qué
sale en ListenBrainz con algo de público, el fondo de las etiquetas de tu
gusto—, quita lo que ya conoces y los puntúa.

Dos ideas lo sostienen. **Triangulación**: un grupo en dos o más orígenes
independientes (la rotación y la sesión de KEXP cuentan como uno) es mucho
mejor apuesta que cualquier cosa de una sola fuente, así que suma fuerte, y
una fuente débil suelta no basta para entrar. **Recurrencia**: el radar se
acumula en `datos/radar.json` y quien sigue apareciendo pasada tras pasada
suma más. Al pedir un menú, la novedad sale de aquí, ya validada.

Para que se pase solo cada semana, programa `radar.bat` en el Programador de
tareas de Windows (por ejemplo, domingos por la noche).

### Feedback en treinta segundos

Si opinar cuesta, no se opina, y sin opiniones la herramienta no aprende.
Dos caminos: en el chat, decir de una vez qué te pareció la semana (la IA lo
guarda todo con `rate` en una llamada), o abrir http://127.0.0.1:8888/semana
y dar un clic por disco. Los discos aparecen agrupados por la lista en la que
entraron, porque `create_playlist` los apunta como pendientes al crearla.

### Las tres señales que no da ningún algoritmo

La popularidad agregada (oyentes, listas por etiqueta) dice lo que ya es
grande. Para lo que todavía no lo es, sirven otras tres, y las tres son
gratuitas:

**Una radio con criterio.** KEXP decide cada semana a quién apoyar, y lo hace
antes de que existan cifras. Un grupo con tres mil oyentes que suena tres
veces en una semana no es casualidad: alguien lo ha elegido. `radio_tastemaker`
da ese ranking; `played_on_radio` comprueba un nombre concreto.

**El sello.** En el indie británico las escenas se organizan por sello, no por
género: Speedy Wunderground, Nice Swan, Partisan. Un sello es un filtro de
gusto humano, así que si te gustan tres de sus discos el cuarto tiene
papeletas. El flujo es `labels_of` sobre una banda que te guste y después
`label_catalog` para ver a sus compañeros de catálogo.

**Las escuchas por oyente.** Mucha escucha repartida entre poca gente es un
público devoto, que es distinto de ser desconocido. Lo calcula
`find_underrated` y aparece en el dosier.

`dossier_artist` junta todo eso en una sola llamada, con tu opinión lo
primero si ya habías dicho algo.

### Por qué estas fuentes y no AOTY o RateYourMusic

Ninguna de las dos tiene API pública; lo que circula son *scrapers* no oficiales, y en el caso de RYM sus términos lo prohíben expresamente. Además, lo que las hace atractivas ya está cubierto: el **canon** de un género lo tiene el modelo de serie, la **actualidad y la crítica** vienen de `music_press` (las mismas fuentes que esos sitios agregan, de primera mano) y el **mapa del género** lo dan las etiquetas de Last.fm con API legítima. Si algún día hicieran falta subgéneros aún más finos, la vía limpia sería la API oficial de Discogs y sus *styles*.

Ejemplos de encargos: *«5 discos de post-punk actual que no conozca, máximo 70 min cada uno»*, *«una playlist de rock español de los 90 que me falte, vista mi fase Vetusta/Sidonie»*, *«algo lejano a lo mío pero que un fan de IDLES pueda disfrutar»*, *«qué ha salido este mes que me pegue y qué dice la prensa»*.

## Notas

- `token.json` y `.env` contienen credenciales: están en `.gitignore`.
- Los clientes externos degradan con gracia (listas vacías + aviso) en vez de tumbar la app. Spotify devuelve 403 en `/artists/{id}/top-tracks` a las apps nuevas; el cliente lo aproxima con búsqueda.
- `scripts/diag_statsfm.py` diagnostica la API de stats.fm si deja de funcionar.
- Spotify ha ido cerrando endpoints a las apps nuevas. Comprobado contra la API real en sep. 2026 con `scripts/diag_spotify.py` (o `diag.bat`):

| Endpoint | Estado |
|---|---|
| `/recommendations`, `related-artists`, `audio-features` | cerrados desde nov. 2024 |
| `/artists/{id}/top-tracks` | 403 — se aproxima con `search(artist:"…")` |
| `/artists?ids=` | 403 — **no hay forma de leer `popularity` ni `followers`**; el tamaño de un artista se mide con los oyentes de Last.fm |
| `/browse/new-releases` | 403 |
| `/artists/{id}/albums` | funciona, pero `limit` ahora es **0-10** (antes 50): pasarse da 400 "Invalid limit"; se completa con búsqueda por nombre |
| `/search` | `limit` también **0-10**, con `offset` hasta 1000 → se pagina. `popularity` y `genres` están deprecados y vienen vacíos; `genre:` solo filtra artistas y canciones, no álbumes |
| `/me/*` (tops, biblioteca, playlists, seguidos, reproduciendo) | funcionan con sus permisos |

Por eso el descubrimiento por género se apoya en las etiquetas de Last.fm y no en los filtros de Spotify.
- Los permisos incluyen `user-follow-read` y `user-read-currently-playing`; si tu `token.json` es anterior, `status` te avisa: entra en la web, pulsa "salir" y vuelve a iniciar sesión.
- La extensión de cuota de Spotify ya solo se concede a organizaciones con más de 250.000 usuarios mensuales, así que estos recortes son permanentes para una herramienta personal: la app está construida asumiéndolos.
- Los feeds de prensa se definen en `app/clients/press.py` (`FEEDS`): añadir o quitar uno es una línea. Si alguno deja de responder, `music_press` lo avisa y sigue con el resto.
- MusicBrainz no pide clave, pero limita a 1 petición por segundo: el cliente lo respeta, así que `verify`, `explore_era` y `artist_context` tardan unos segundos.
- Spotify en modo desarrollo tiene **cuota compartida por desarrollador** y responde 429 cuando se va en tromba. El cliente lleva un freno común a 8 peticiones por segundo; si un 429 pide esperar más de 10 s, se aborta con un aviso claro en vez de quedarse colgado. Las respuestas de las consultas pesadas incluyen `peticiones_a_spotify` para ver lo que cuesta cada una.
- Las consultas pesadas se cachean 30 minutos en memoria del servidor MCP. `taste_profile`, `new_releases` y `discover_emerging` además se calculan en segundo plano (`app/jobs.py`): hacen cientos de peticiones y no caben en el minuto que aguanta el cliente MCP, así que la primera llamada responde "en curso" y la siguiente, con los mismos parámetros, recoge el resultado.
