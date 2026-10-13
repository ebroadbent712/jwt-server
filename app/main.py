"""justwearthis.co: the website, smart shop links, published client pages and the publish connector, in one service."""
import asyncio, contextlib, html, json, os, re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from . import config, links, store
from .connector import mcp

mcp_app = mcp.streamable_http_app()


# ---------- pages ----------
def _page(kind):
    async def handler(request: Request):
        pid = request.path_params["pid"].lower()
        meta = store.page_meta(pid)
        path = store.page_html_path(pid)
        if not meta or not path or (meta.get("kind") == "plan") != (kind == "plan"):
            return FileResponse(os.path.join(config.SITE, "404.html"), status_code=404)
        return FileResponse(path, media_type="text/html", headers={
            "X-Robots-Tag": "noindex, nofollow", "Cache-Control": "no-cache", "Referrer-Policy": "no-referrer"})
    return handler


async def smart_link(request: Request):
    url, how = links.resolve(request.path_params["code"])
    return RedirectResponse(url, status_code=302, headers={"X-JWT-Link": how, "Cache-Control": "no-store"})


async def healthz(request):
    return PlainTextResponse("ok")


# ---------- admin (Emily only; token lives in the Render dashboard) ----------
def _admin_ok(request):
    tok = request.headers.get("x-admin-token") or request.query_params.get("token", "")
    return bool(config.ADMIN_TOKEN) and tok == config.ADMIN_TOKEN


async def admin_keys(request: Request):
    if not _admin_ok(request):
        return PlainTextResponse("Not allowed", status_code=403)
    if request.method == "POST":
        form = dict(request.query_params)
        if request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            form.update(await request.form())
        if form.get("disable"):
            store.set_key_active(form["disable"], False)
        elif form.get("name"):
            key = store.create_key(form["name"].strip(), form.get("email", "").strip())
            return JSONResponse({"key": key, "connector_url": f"{config.PUBLIC_BASE}/mcp/{key}"})
    ks = store.keys()
    return JSONResponse([{"name": v["name"], "email": v.get("email"), "created": v["created"], "active": v.get("active", True),
                          "connector_url": f"{config.PUBLIC_BASE}/mcp/{k}", "pages": len(store.pages_for(k))} for k, v in ks.items()])


async def admin_links(request: Request):
    if not _admin_ok(request):
        return PlainTextResponse("Not allowed", status_code=403)
    if request.method == "POST":
        asyncio.get_running_loop().create_task(links.check_all(request.query_params.get("host")))
        return JSONResponse({"started": True, "note": "Takes 20 to 40 minutes. Reload this page later."})
    h = links.health()
    s = links.summary()
    rows = sorted(((u, r) for u, r in h.items() if r.get("dead") or r.get("status") != "ok"),
                  key=lambda x: (not x[1].get("dead"), x[0]))
    e = html.escape
    body = "".join(f"<tr><td>{'DEAD' if r.get('dead') else e(r.get('status',''))}</td><td>{e(', '.join(r.get('pieces', [])))}</td>"
                   f"<td><a href='{e(u)}'>{e(u[:70])}</a></td><td>{e(r.get('note',''))}</td><td>{e(r.get('checked',''))}</td></tr>"
                   for u, r in rows)
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Link health</title><style>body{{font:14px system-ui;margin:20px}}td{{padding:4px 8px;border-bottom:1px solid #ddd;vertical-align:top}}</style>
<h1>Shop link health</h1><p>{s['links']} links: {s['ok']} live, {s['dead']} dead, {s['unchecked']} not checkable by the server.</p>
<p><b>Pieces with no live link ({len(s['pieces_with_no_live_link'])}):</b> {e(', '.join(s['pieces_with_no_live_link'])) or 'none'}</p>
<table><tr><th>Status</th><th>Pieces</th><th>Link</th><th>Why</th><th>Checked</th></tr>{body}</table>""")


# ---------- old addresses from the Netlify _redirects file (everything except /s/, which is live now) ----------
def _legacy_redirects():
    out = []
    p = os.path.join(config.SITE, "_redirects")
    if os.path.exists(p):
        for line in open(p):
            parts = line.split()
            if len(parts) >= 2 and parts[0].startswith("/") and not parts[0].lower().startswith("/s/"):
                out.append((parts[0], parts[1], int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 301))
    return out


LEGACY = _legacy_redirects()


class App:
    """Front door: www -> apex, /mcp/<key> -> connector, legacy redirects, then the routes and the static site."""

    def __init__(self):
        self.routes = Starlette(routes=[
            Route("/healthz", healthz),
            Route("/s/{code:path}", smart_link),
            Route("/p/{pid}", _page("plan")),
            Route("/q/{pid}", _page("questionnaire")),
            Route("/admin/keys", admin_keys, methods=["GET", "POST"]),
            Route("/admin/links", admin_links, methods=["GET", "POST"]),
        ])
        self.routes.mount("/", StaticFiles(directory=config.SITE, html=True))

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            return await self.lifespan(scope, receive, send)
        if scope["type"] != "http":
            return await self.routes(scope, receive, send)
        host = dict(scope.get("headers", [])).get(b"host", b"").decode()
        path = scope["path"]
        if host.startswith("www."):
            qs = scope.get("query_string", b"").decode()
            return await RedirectResponse(f"https://{host[4:]}{path}{'?' + qs if qs else ''}", 301)(scope, receive, send)
        m = re.match(r"^/mcp/([A-Za-z0-9_-]{8,64})(/.*)?$", path)
        if m:
            if not store.key_info(m.group(1)):
                return await JSONResponse({"error": "This connector link isn't active."}, 404)(scope, receive, send)
            scope = dict(scope, path=m.group(2) or "/", raw_path=(m.group(2) or "/").encode(),
                         state=dict(scope.get("state") or {}, jwt_key=m.group(1)))
            return await mcp_app(scope, receive, send)
        for src, dst, code in LEGACY:
            if path == src or (src.endswith("/*") and path.startswith(src[:-1])):
                return await RedirectResponse(dst, code)(scope, receive, send)
        return await self.routes(scope, receive, send)

    async def lifespan(self, scope, receive, send):
        msg = await receive()
        if msg["type"] == "lifespan.startup":
            self._stack = contextlib.AsyncExitStack()
            await self._stack.enter_async_context(mcp.session_manager.run())
            if config.CHECK_ENABLED:
                self._nightly = asyncio.get_running_loop().create_task(links.nightly())
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await self._stack.aclose()
            await send({"type": "lifespan.shutdown.complete"})


app = App()
