# Estado del proyecto

Notas para retomar sin releer todo el historial. Actualizar al cerrar cada sesión.

_Última actualización: 21 de septiembre de 2026._

## Dónde estamos

Playlist Lab ya no recomienda por reglas: es la capa de datos y ejecución para
que una IA (Claude Desktop, vía MCP) cure la música. 22 herramientas y 2
prompts. La web solo sirve para el login de Spotify y para ver el perfil.

Probado contra las APIs reales y funcionando: `status`, `taste_profile`,
`my_library`, `my_playlists`, `check_known`, `explore_genre`, `explore_era`,
`find_underrated`, `artist_context`, `verify`, `music_press` (los 8 feeds
responden), `search`, `album_info`.

## Pendiente de comprobar (lo primero mañana)

1. `new_releases` — historial del problema: primero devolvía listas vacías
   (por el `limit` de Spotify, ya arreglado), luego tardaba más de 3 minutos
   (freno de peticiones y menos paralelismo, ya puesto) y por último falló con
   `JSONDecodeError`, porque Last.fm devolvió HTML en vez de JSON y solo
   Wikipedia tenía ese caso previsto. Corregido en los cuatro clientes y
   aislado para que el fallo de un artista no tumbe la tanda. **Falta
   ejecutarlo tras reiniciar Claude Desktop** y mirar `peticiones_a_spotify` y
   `progreso` para saber dónde se va el tiempo.
2. `discover_emerging` — mismo camino, nunca ha llegado a devolver resultados.
3. `explore_scene` — es la única herramienta que no se ha ejecutado nunca.

## Lo siguiente, por orden

1. **Memoria de opiniones.** Es lo que más cambia la experiencia y no existe.
   Hoy la app sabe qué escuchas pero no qué opinas: "esto me encantó", "no me
   propongas más X" se pierde al cerrar la conversación. Hace falta un fichero
   de notas por artista/disco, herramientas para leer y escribir en él, y que
   el prompt de curación lo consulte siempre.
2. **Despliegue.** Hoy es local y depende de tener Claude Desktop abierto.
   Servidor con Tailscale o Cloudflare Access, token fuera del disco local y
   MCP por HTTP con autenticación; eso da móvil y ChatGPT sin túneles. ~1 día.
3. **Chat propio con la API** (opcional, solo si al usarlo se echa de menos
   hablar con la app en vez de con Claude Desktop).

## Cómo se trabaja aquí

- Cambiar código → **cerrar Claude Desktop del todo y abrirlo**: el servidor
  MCP se arranca una vez y no recarga solo. Es el cuello de botella del ciclo
  de prueba, y conviene agrupar varios cambios antes de reiniciar.
- La web (`setup.bat`) solo hace falta para el login; el MCP reutiliza
  `token.json`.
- Si se añaden permisos de Spotify, hay que salir y volver a entrar en la web.
  `status` avisa cuando al token le faltan permisos.
- `diag.bat` prueba endpoint por endpoint y deja `diag_spotify.txt`.
  `scripts/diag_statsfm.py` hace lo propio con stats.fm.
- Commits pequeños, en español, y `git push` a mano (las credenciales de
  GitHub no están disponibles desde la sesión de Cowork).

## Lo que hemos aprendido de las APIs

La tabla completa está en el README. Lo esencial: Spotify ha cerrado casi todo
lo interesante para apps nuevas (recomendaciones, artistas relacionados,
top-tracks, popularidad, novedades destacadas) y ha bajado el `limit` a 10 en
búsqueda y en discografías. La extensión de cuota solo se concede a
organizaciones con 250.000 usuarios mensuales, así que es permanente. De ahí
que el tamaño de un artista se mida con los oyentes de Last.fm y que el mapa
de géneros salga de sus etiquetas.

AOTY y RateYourMusic no tienen API pública y RYM prohíbe el scraping: el canon
lo pone el modelo, la actualidad `music_press` y los datos duros MusicBrainz.

Lección transversal: **ninguna de estas APIs es de fiar**. Devuelven HTML
cuando esperas JSON, cambian límites sin avisar y cierran endpoints. Todo
cliente nuevo debe capturar también `ValueError`, degradar a lista vacía y
dejar un aviso, nunca tumbar la operación entera.
