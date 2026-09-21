# Playlist Lab 🎧

Centro de consulta y creación de playlists de Spotify **para usar conversando**. La app no recomienda por sí sola: reúne lo que sabe de ti (Spotify, Last.fm y stats.fm), lo expone a una IA por MCP y ejecuta lo que decidáis (buscar, verificar, crear la playlist). La curación la hace Claude o ChatGPT combinando tu perfil con su conocimiento de escenas, discografías y crítica.

¿Por qué así? El endpoint oficial `/recommendations` de Spotify (y related-artists, top-tracks, audio-features…) está cerrado para apps nuevas, y las heurísticas caseras (similares de Last.fm, tops de tus artistas) tienden a devolverte lo que ya conoces. Un buen curador con tus datos delante lo hace mejor.

## Qué hay

- **Servidor MCP** (`mcp_server.py`) — herramientas de consulta y creación (abajo). Stdio para Claude Desktop y `--http` para ChatGPT vía túnel.
- **Web mínima** (`app/main.py` + `static/index.html`, puerto 8888) — login OAuth PKCE de Spotify (una vez; token en `token.json`), estado de las fuentes, vista del perfil que ve la IA y el bloque de configuración del MCP listo para copiar.
- **Clientes** (`app/clients/`) — Spotify (PKCE, degrada ante endpoints cerrados), Last.fm, stats.fm (API interna, best-effort; validada sep. 2026), MusicBrainz (verificación de datos) y prensa por RSS.
- `app/taste.py` — perfil de gustos y artistas conocidos. `app/library.py` — búsqueda, resolución de "Artista – Canción/Álbum" y creación. `app/discovery.py` — novedades de tu órbita.

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
| `taste_profile` | tops por periodo con géneros, Last.fm reciente, histórico stats.fm, `fase_actual`, `generos_principales` |
| `listening_history` | tops en bruto por fuente/rango, paginable |
| `check_known` | si ya conoces a unos artistas y con qué evidencia (Spotify/Last.fm/stats.fm) |
| `similar_artists` | similares según Last.fm, filtrando conocidos |
| `search` | búsqueda en Spotify (álbum/canción/artista, con filtros `year:`, `genre:`) |
| `album_info` | año, duración y pistas de un álbum |
| `new_releases` | discos recientes de tu órbita, separando "de los tuyos" y "alrededor" |
| `music_press` | reseñas y noticias recientes (Pitchfork, Quietus, Bandcamp Daily, Mondo Sonoro, Jenesaispop, Stereogum, BrooklynVegan) |
| `verify` | año real, sello, actividad y discografía según MusicBrainz |

| Creación | |
|---|---|
| `resolve` | verifica una propuesta ("Artista – Canción" / "Artista – Álbum") sin crear nada |
| `create_playlist` | crea la playlist con canciones y/o álbumes completos; informa de lo no encontrado |

Y el prompt `curar_playlist`, con el método: leer el perfil → proponer como un crítico (no como un algoritmo) → filtrar conocidos → verificar en Spotify → presentar y confirmar → crear.

Ejemplos de encargos: *«5 discos de post-punk actual que no conozca, máximo 70 min cada uno»*, *«una playlist de rock español de los 90 que me falte, vista mi fase Vetusta/Sidonie»*, *«algo lejano a lo mío pero que un fan de IDLES pueda disfrutar»*, *«qué ha salido este mes que me pegue y qué dice la prensa»*.

## Notas

- `token.json` y `.env` contienen credenciales: están en `.gitignore`.
- Los clientes externos degradan con gracia (listas vacías + aviso) en vez de tumbar la app. Spotify devuelve 403 en `/artists/{id}/top-tracks` a las apps nuevas; el cliente lo aproxima con búsqueda.
- `scripts/diag_statsfm.py` diagnostica la API de stats.fm si deja de funcionar.
- Los feeds de prensa se definen en `app/clients/press.py` (`FEEDS`): añadir o quitar uno es una línea. Si alguno deja de responder, `music_press` lo avisa y sigue con el resto.
- MusicBrainz no pide clave, pero limita a 1 petición por segundo: el cliente lo respeta, así que `verify` con discografía tarda un par de segundos.
