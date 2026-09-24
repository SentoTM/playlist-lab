"""El servidor MCP publicado en internet: login, copias de datos y salud.

Por qué existe: para usar la herramienta desde el chat del móvil, el
servidor tiene que estar en internet (Railway). Y en internet cualquiera
podría encontrar la URL, así que:

- El acceso MCP pide login con GitHub (OAuth, lo que entienden los
  conectores de Claude) y además SOLO deja pasar a los usuarios de GitHub
  listados en GITHUB_USUARIOS_PERMITIDOS. Tener cuenta de GitHub no basta.
- Las rutas para subir y bajar tus datos piden un token propio
  (ADMIN_TOKEN) que solo tienes tú.

En local (stdio, Claude Desktop) nada de esto se activa: sin
GITHUB_CLIENT_ID no hay login.
"""
import hmac
import io
import logging
import os
import zipfile
from pathlib import Path

log = logging.getLogger("playlist_lab.remoto")
DATOS = Path(__file__).resolve().parents[1] / "datos"

# Lo único que se puede subir o bajar: nada de rutas arbitrarias.
FICHEROS = {"notas.json", "perfil.md", "cache.json", "prensa.json", "radar.json",
            "seguimiento.json", "propuestos.json", "listas.json", "scrobbles.json"}


def _url_publica() -> str | None:
    if os.getenv("PUBLIC_URL"):
        return os.getenv("PUBLIC_URL").rstrip("/")
    if os.getenv("RAILWAY_PUBLIC_DOMAIN"):   # Railway la rellena solo
        return "https://" + os.getenv("RAILWAY_PUBLIC_DOMAIN")
    return None


def _permitidos() -> set[str]:
    return {u.strip().lower() for u in os.getenv("GITHUB_USUARIOS_PERMITIDOS", "").split(",")
            if u.strip()}


def opciones_de_seguridad() -> dict:
    """auth + middleware para FastMCP, o {} si no estamos en el servidor."""
    cid, secreto = os.getenv("GITHUB_CLIENT_ID"), os.getenv("GITHUB_CLIENT_SECRET")
    if not (cid and secreto):
        return {}
    base = _url_publica()
    permitidos = _permitidos()
    if not base or not permitidos:
        # Mejor no arrancar que arrancar abierto a cualquiera con GitHub.
        raise RuntimeError("Con GitHub configurado hacen falta PUBLIC_URL (o el dominio "
                           "de Railway) y GITHUB_USUARIOS_PERMITIDOS.")
    from fastmcp.server.auth.providers.github import GitHubProvider
    from fastmcp.server.middleware import AuthMiddleware

    def solo_los_mios(ctx) -> bool:
        claims = (ctx.token.claims if ctx.token else None) or {}
        login = (claims.get("login") or "").lower()
        if login not in permitidos:
            log.warning("Acceso denegado a '%s' (claims: %s)", login or "?", sorted(claims))
            return False
        return True

    auth = GitHubProvider(client_id=cid, client_secret=secreto, base_url=base,
                          jwt_signing_key=os.getenv("JWT_SIGNING_KEY") or None)
    log.info("Servidor protegido con GitHub para: %s", ", ".join(sorted(permitidos)))
    return {"auth": auth, "middleware": [AuthMiddleware(auth=solo_los_mios)]}


def _autorizado(request) -> bool:
    esperado = os.getenv("ADMIN_TOKEN", "")
    dado = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return len(esperado) >= 20 and hmac.compare_digest(dado, esperado)


def rutas_de_servicio(mcp) -> None:
    from starlette.responses import JSONResponse, Response

    @mcp.custom_route("/salud", methods=["GET"])
    async def salud(request):
        # 'datos_persistentes' debe salir true en Railway: si sale false, el
        # volumen no está montado en esta carpeta y tus notas se perderían
        # en cada despliegue.
        return JSONResponse({"ok": True, "datos": str(DATOS),
                             "datos_persistentes": os.path.ismount(DATOS)})

    @mcp.custom_route("/admin/datos/{nombre}", methods=["PUT"])
    async def subir(request):
        if not _autorizado(request):
            return JSONResponse({"error": "no autorizado"}, status_code=401)
        nombre = request.path_params["nombre"]
        if nombre == "token.json":
            destino = Path(os.getenv("SPOTIFY_TOKEN_FILE") or DATOS / "token.json")
        elif nombre in FICHEROS:
            destino = DATOS / nombre
        else:
            return JSONResponse({"error": f"fichero no permitido: {nombre}"}, status_code=400)
        cuerpo = await request.body()
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_suffix(destino.suffix + ".tmp")
        temporal.write_bytes(cuerpo)
        os.replace(temporal, destino)
        if nombre == "cache.json":
            from . import cache
            cache._memoria = None   # que relea lo subido
        return JSONResponse({"ok": True, "fichero": nombre, "bytes": len(cuerpo)})

    @mcp.custom_route("/admin/copia", methods=["GET"])
    async def copia(request):
        """Zip con todos tus datos: copia de seguridad o para trabajar en local."""
        if not _autorizado(request):
            return JSONResponse({"error": "no autorizado"}, status_code=401)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n in sorted(FICHEROS):
                if (DATOS / n).exists():
                    z.write(DATOS / n, n)
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": "attachment; filename=datos.zip"})
