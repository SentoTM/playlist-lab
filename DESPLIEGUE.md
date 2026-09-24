# Playlist Lab en internet (Railway) para usarlo desde el móvil

Una sola vez, unos 15 minutos. Después, cada `git push` despliega solo.

## Qué se consigue

- El conector funciona en Claude en todas partes: móvil, web y Claude Desktop.
- Hay una sola memoria: tus notas, tu historial y tu huella viven en el
  servidor.
- Nadie más puede usarlo. Hace falta entrar con GitHub **y** ser uno de los
  usuarios de `GITHUB_USUARIOS_PERMITIDOS`. Tus datos solo se suben o bajan
  con tu `ADMIN_TOKEN`.
- Coste: el plan Hobby de Railway ronda los 5 $/mes con ese consumo incluido.

ChatGPT: hoy los conectores MCP propios solo existen en los planes Business
y Enterprise, y solo en la web. El servidor ya habla el mismo protocolo, así
que valdría el día que lo abran.

## 1. Dos claves aleatorias

En una terminal, dentro del proyecto:

    .venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"

Ejecútalo dos veces. La primera clave es tu `ADMIN_TOKEN` y la segunda tu
`JWT_SIGNING_KEY`. Guárdalas, por ejemplo en tu gestor de contraseñas.

## 2. Railway

1. Entra en https://railway.com con **Login with GitHub**.
2. Crea el proyecto: **New Project → Deploy from GitHub repo →
   playlist-lab**. Si no aparece, dale permiso a Railway sobre ese repo.
3. Genera el dominio: en el servicio, **Settings → Networking → Generate
   Domain**. Apunta la URL, que será algo como
   `https://playlist-lab-production.up.railway.app`.
4. Crea el volumen para tus datos: botón derecho sobre el servicio (o
   **+ New**) → **Volume**. Ruta de montaje: `/app/datos`.

## 3. App de GitHub para el login

En https://github.com/settings/developers → **OAuth Apps → New OAuth App**:

- Application name: `Playlist Lab`
- Homepage URL: tu URL de Railway
- Authorization callback URL: tu URL de Railway + `/auth/callback`

Pulsa **Generate a new client secret** y copia el *Client ID* y el *Client
secret*.

## 4. Variables en Railway

En el servicio, **Variables → Raw Editor**. Pega esto y rellena los valores.
Las de Spotify, Last.fm y stats.fm son las de tu `.env`.

    SPOTIFY_CLIENT_ID=
    LASTFM_API_KEY=
    LASTFM_USERNAME=
    STATSFM_USERNAME=
    GITHUB_CLIENT_ID=
    GITHUB_CLIENT_SECRET=
    GITHUB_USUARIOS_PERMITIDOS=SentoTM
    ADMIN_TOKEN=
    JWT_SIGNING_KEY=
    HOST=0.0.0.0
    SPOTIFY_TOKEN_FILE=/app/datos/token.json
    FASTMCP_HOME=/app/datos/fastmcp

`GITHUB_USUARIOS_PERMITIDOS` es tu usuario de GitHub. Si es otro, cámbialo.

Railway vuelve a desplegar solo. Comprueba que ha ido bien abriendo
`https://TU-URL/salud`: tiene que salir `"ok": true` y
`"datos_persistentes": true`. Si sale `false`, el volumen no está en
`/app/datos`.

## 5. Sube tus datos

En tu `.env` local añade:

    PLAYLIST_LAB_URL=https://TU-URL
    ADMIN_TOKEN=el mismo de Railway

y haz doble clic en `subir_datos.bat`. Sube tus notas, historial, radar,
caché y el token de Spotify, así el servidor no necesita que vuelvas a
iniciar sesión.

Para bajar una copia de seguridad cuando quieras: `subir_datos.bat --bajar`.
Deja `datos_servidor.zip` en la carpeta del proyecto.

## 6. Conéctalo a Claude

En https://claude.ai → **Configuración → Conectores → Añadir conector
personalizado**:

- Nombre: `Playlist Lab`
- URL: `https://TU-URL/mcp`

Pulsa **Conectar**, entra con GitHub y autoriza. Desde ese momento lo tienes
en el móvil, en la web y en Claude Desktop.

**Importante:** quita `playlist-lab` de `claude_desktop_config.json` en
Claude Desktop. Si no, tendrías dos cerebros con datos distintos: el local y
el del servidor. `radar.bat` escribe en los datos locales, así que a partir
de ahora el radar se actualiza desde el chat con `radar_update`.

## Si algo falla

- **No aparecen herramientas o sale "no autorizado":** revisa en Railway
  (**Deployments → View logs**) si pone "Acceso denegado a 'xxx'". Ese
  `xxx` es el usuario que hay que poner en `GITHUB_USUARIOS_PERMITIDOS`.
- **Error de Spotify sin sesión:** vuelve a lanzar `subir_datos.bat`, que
  sube `token.json`.
