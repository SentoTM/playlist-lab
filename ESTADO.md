# Estado del proyecto

Notas para retomar sin releer todo el historial. Actualizar al cerrar cada sesión.

_Última actualización: 22 de septiembre de 2026._

## Dónde estamos

Playlist Lab ya no recomienda por reglas: es la capa de datos y ejecución para
que una IA (Claude Desktop, vía MCP) cure la música. 22 herramientas y 2
prompts. La web solo sirve para el login de Spotify y para ver el perfil.

Probado contra las APIs reales y funcionando: `status`, `taste_profile`,
`my_library`, `my_playlists`, `check_known`, `explore_genre`, `explore_era`,
`find_underrated`, `artist_context`, `verify`, `music_press` (los 8 feeds
responden), `search`, `album_info`.

## La trampa que nos costó dos días

`new_releases` devolvía listas vacías y fuimos encontrando cuatro causas
reales encadenadas (límite de `limit`, orden no garantizado, respuestas que no
eran JSON, lentitud). La quinta y definitiva: **habíamos agotado la cuota de
Spotify del modo desarrollo** a fuerza de probar, y la API respondía 429
pidiendo esperar 77 minutos.

Lo grave no fue el 429, sino que no se veía: el `except Exception` que se
puso para que el fallo de un artista no tumbara la tanda convertía "Spotify me
está frenando" en "este artista no tiene novedades", y el resultado era una
lista vacía con aspecto de respuesta legítima. **Un error tragado en silencio
es peor que un error ruidoso**: nos hizo perseguir cuatro bugs que sí existían
pero que no eran el problema del momento.

Correcciones: los fallos se cuentan por motivo y salen en `warnings` diciendo
que la lista está incompleta; mientras dura un 429 largo no se lanza ni una
petición más (insistir solo alarga el castigo); y `known_artists`, que cuesta
unas 30 peticiones, se cachea en disco 12 h para que reiniciar el servidor no
vuelva a pagarlas.

## Pendiente de comprobar (tras el próximo reinicio)

1. `new_releases` — cuarta causa del mismo síntoma. Ya no falla y tarda 13 s,
   pero seguía devolviendo listas vacías con 51 peticiones hechas: el endpoint
   de discografía devuelve 10 por página y **no garantiza orden por fecha**,
   así que una sola página traía discos antiguos y parecía que nadie había
   publicado nada. Ahora se pagina y se ordena en local. Falta confirmarlo.
2. `discover_emerging` — nunca ha llegado a devolver resultados; comparte la
   misma corrección.
3. `explore_scene` — es la única herramienta que no se ha ejecutado nunca.
4. La memoria de opiniones (`remember` / `my_notes` / `forget_note`) está
   probada en local pero no a través del MCP.

## Lo siguiente, por orden

1. **Despliegue.** Hoy es local y depende de tener Claude Desktop abierto.
   Servidor con Tailscale o Cloudflare Access, token fuera del disco local y
   MCP por HTTP con autenticación; eso da móvil y ChatGPT sin túneles. ~1 día.
2. **Chat propio con la API** (opcional, solo si al usarlo se echa de menos
   hablar con la app en vez de con Claude Desktop).
3. Con la memoria de opiniones ya en marcha, revisar al cabo de unas semanas
   si hace falta más estructura (por ejemplo, notas por género o por
   contexto de escucha) o si con artista/álbum/general basta.

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
cliente nuevo debe capturar también `ValueError` y degradar en vez de tumbar
la operación entera — pero **degradar dejando rastro**: contar el fallo y
decirlo en la respuesta. Una lista vacía sin explicación es una mentira.

Y la cuota importa: cada tanda de pruebas gasta de un saldo compartido que
tarda más de una hora en reponerse. Antes de lanzar una consulta grande,
mirar `status`, que ahora dice si Spotify nos tiene frenados y qué hay en
caché.
