# Playlist Lab 🎧

Herramienta local para generar playlists de Spotify combinando varios sistemas de recomendación propios: tu perfil de Spotify, similares de Last.fm y tu historial completo de stats.fm.

Tres formas de usarla:

1. **Web app** local (interfaz en el navegador)
2. **CLI** — `python -m app.weekly week` genera las playlists de álbumes de la semana
3. **Servidor MCP** — para usarla conversacionalmente desde Claude o (vía túnel) desde ChatGPT

Corre en tu máquina, solo para ti (Development Mode de Spotify: requiere cuenta Premium y admite hasta 5 usuarios autorizados).

## 1. Crear la app en Spotify (una vez)

1. Entra en https://developer.spotify.com/dashboard con tu cuenta (Premium).
2. **Create app** → dale un nombre (p. ej. "Playlist Lab").
3. En **Redirect URIs** añade exactamente: `http://127.0.0.1:8888/callback`
4. En APIs marca **Web API**. Guarda.
5. Copia el **Client ID** de la app (no necesitas el Client Secret: usamos PKCE).

## 2. Configurar

```bash
cd playlist-lab
python3 -m venv .venv && source .venv/bin/activate   # en Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edita `.env`:

- `SPOTIFY_CLIENT_ID` — obligatorio (paso 1).
- `LASTFM_API_KEY` + `LASTFM_USERNAME` — opcional; API key gratuita en https://www.last.fm/api/account/create (basta rellenar nombre y descripción; la key sale al instante).
- `STATSFM_USERNAME` — opcional; tu usuario de stats.fm **con perfil público**. Ojo: stats.fm no tiene API oficial, así que este motor es "best effort" y puede dejar de funcionar si cambian su API interna.

## 3. Ejecutar

```bash
uvicorn app.main:app --port 8888
```

Abre http://127.0.0.1:8888, pulsa **Iniciar sesión con Spotify** (solo la primera vez; el token se guarda en `token.json`) y genera.

## Los motores

- **Perfil Spotify** — parte de tus canciones y artistas top (corto/medio/largo plazo) y expande por los top tracks y álbumes de tus artistas. El deslizador *Descubrimiento* controla el equilibrio: 0% ≈ tus clásicos, 100% ≈ temas que no conoces de artistas que sí conoces.
- **Last.fm similares** — toma como semillas tu top reciente de Spotify **y** tu top de Last.fm (que incluye lo que scrobbleas fuera de Spotify), pide `track.getSimilar` y agrega las puntuaciones de similitud. Los resultados se resuelven a Spotify por búsqueda.
- **stats.fm historial** — usa tu top *lifetime*: propone redescubrimientos (favoritos históricos que ya no escuchas) y temas aún no escuchados de tus artistas con más streams.

La mezcla normaliza las puntuaciones de cada motor, las pondera con los pesos que elijas, suma cuando varios motores coinciden en la misma canción, y hace un muestreo ponderado con tope de canciones por artista — cada "Regenerar" da una variación distinta.

## Playlists diarias de álbumes (lunes a viernes)

Cada día laborable, una playlist con **5 álbumes** (máx. ~70 min cada uno):

| Categoría | Qué es |
|---|---|
| 🆕 Moderno similar | Últimos 5 años, artista similar a tus gustos que **no** conoces |
| 🕰 Clásico similar | Lo mismo pero anterior a 2000 |
| ↔️ Género adyacente | Cualquier época, género vecino al tuyo (rock/punk → metal, blues…) |
| 🎲 Sorpresa lejana | Género alejado de tu perfil: jazz, electrónica, pop… |
| ⭐ Imprescindible | Un clásico unánime de cualquier género (lista editable en `app/albums/essentials.py`) |

El filtro de "no conocido" usa tus artistas de Spotify + Last.fm + stats.fm. La selección es determinista por fecha (misma fecha → mismos álbumes) y el parámetro `--variant` da otra tirada. Dentro de una semana no se repiten álbumes ni, dentro de un día, artistas.

```bash
python -m app.weekly preview                # los 5 álbumes de hoy, sin crear nada
python -m app.weekly today                  # crea la playlist de hoy
python -m app.weekly week                   # crea las 5 playlists de la próxima semana
python -m app.weekly week --start 2026-09-14 --dry-run
```

Requiere Last.fm configurado (las categorías por similitud y género salen de ahí) y haber hecho login una vez en la web app.

## Servidor MCP (usarla hablando con Claude o ChatGPT)

El servidor expone estas herramientas: `status`, `preview_day_albums`, `create_day_playlist`, `generate_week` y `custom_playlist` (la mezcla de motores de la web, por conversación).

### Claude Desktop

Añade a tu `claude_desktop_config.json` (Ajustes → Desarrollador → Editar configuración):

```json
{
  "mcpServers": {
    "playlist-lab": {
      "command": "/RUTA/A/playlist-lab/.venv/bin/python",
      "args": ["/RUTA/A/playlist-lab/mcp_server.py"]
    }
  }
}
```

Reinicia Claude Desktop y pídele por ejemplo: *"enséñame los álbumes de hoy"* o *"genera las playlists de la semana que viene"*. Además, con el MCP registrado en Claude Desktop, las sesiones de Cowork vinculadas a tu ordenador también pueden usar estas herramientas.

### ChatGPT (opcional, requiere túnel)

ChatGPT solo acepta conectores MCP **remotos** (una URL pública). Para probarlo:

```bash
python mcp_server.py --http        # sirve MCP en http://127.0.0.1:8877/mcp
cloudflared tunnel --url http://127.0.0.1:8877   # o ngrok http 8877
```

En ChatGPT: Settings → Connectors → Advanced → Developer mode → añade la URL pública del túnel + `/mcp`. Ten en cuenta que un túnel expone el servidor a internet mientras esté abierto: úsalo puntualmente y ciérralo después, porque quien tenga la URL podría crear playlists en tu cuenta.

## Notas

- El endpoint oficial `/recommendations` de Spotify (y audio-features, related-artists…) está deprecado para apps nuevas desde nov. 2024; por eso los motores son propios.
- `token.json` contiene tu token de acceso: no lo compartas ni lo subas a git (ya está en `.gitignore`).
- Para añadir un motor nuevo: crea un módulo en `app/engines/` que devuelva `list[Candidate]` y engánchalo en `app/main.py` (`/api/preview`) y en la UI.
