"""justwearthis.co: the website, smart shop links, published client pages and the publish connector, in one service."""
import asyncio, contextlib, html, json, os, re

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles

from . import config, family, links, payments, store
from .family_routes import ROUTES as FAMILY_ROUTES
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
    return PlainTextResponse("ok " + os.environ.get("RENDER_GIT_COMMIT", "")[:7])


def _status_cell(o):
    st = o.get("status", "")
    if st in ("paid", "building"):
        return "<b>building…</b>"
    if st == "failed":
        return "<b style='color:#b00'>failed</b> ⚠ " + html.escape((o.get("error") or "")[:80])
    return html.escape(st)


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
        elif form.get("make_codes"):
            made_codes = payments.make_codes(form.get("make_codes") or 1, (form.get("note") or "").strip())
            made = "<p style='background:#eef7ee;padding:12px'>New beta codes (one use each):<br><code>" + "<br>".join(made_codes) + "</code></p>"
        elif form.get("rebuild"):
            o = family.get_order(str(form["rebuild"]))
            if o:
                if o["status"] == "awaiting_payment":
                    o["status"] = "paid"
                family.log(o, "rebuild from admin")
                family.save_order(o)
                family.build_async(o["id"])
                made = f"<p style='background:#eef7ee;padding:12px'>Rebuilding {html.escape(o['email'])}'s plan. This page updates itself until it's done.</p>"
        elif form.get("name"):
            key = store.create_key(form["name"].strip(), form.get("email", "").strip())
            return JSONResponse({"key": key, "connector_url": f"{config.PUBLIC_BASE}/mcp/{key}"})
    ks = store.keys()
    return JSONResponse([{"name": v["name"], "email": v.get("email"), "created": v["created"], "active": v.get("active", True),
                          "connector_url": f"{config.PUBLIC_BASE}/mcp/{k}", "pages": len(store.pages_for(k))} for k, v in ks.items()])


def _open_link(url):
    return f"<a href='{html.escape(url)}' target=_blank>open</a>" if url else ""


async def admin_home(request: Request):
    """A plain page for Emily: make a connector link for a buyer, see who has one, open the link report."""
    if not _admin_ok(request):
        return HTMLResponse("""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Admin</title><form style="font:16px system-ui;margin:40px"><p>Admin password</p><input name=token type=password autofocus>
<button>Open</button></form>""", status_code=200 if not request.query_params.get("token") else 403)
    tok = html.escape(request.query_params.get("token", ""))
    made = ""
    if request.method == "POST":
        form = await request.form()
        if form.get("delete_page"):
            pid = str(form["delete_page"])
            meta = store.page_meta(pid) or {}
            if store.delete_page(pid):
                made = f"<p style='background:#fbeaea;padding:12px'>Deleted <b>{html.escape(meta.get('title') or pid)}</b>. That link now shows the not-found page.</p>"
        elif form.get("make_codes"):
            made_codes = payments.make_codes(form.get("make_codes") or 1, (form.get("note") or "").strip())
            made = "<p style='background:#eef7ee;padding:12px'>New beta codes (one use each):<br><code>" + "<br>".join(made_codes) + "</code></p>"
        elif form.get("rebuild"):
            o = family.get_order(str(form["rebuild"]))
            if o:
                if o["status"] == "awaiting_payment":
                    o["status"] = "paid"
                family.log(o, "rebuild from admin")
                family.save_order(o)
                family.build_async(o["id"])
                made = f"<p style='background:#eef7ee;padding:12px'>Rebuilding {html.escape(o['email'])}'s plan. This page updates itself until it's done.</p>"
        elif form.get("name"):
            key = store.create_key(form["name"].strip(), (form.get("email") or "").strip())
            made = f"<p style='background:#eef7ee;padding:12px'>Connector link for <b>{html.escape(form['name'])}</b>:<br><code>{config.PUBLIC_BASE}/mcp/{key}</code></p>"
    rows = "".join(f"<tr><td>{html.escape(v['name'])}</td><td>{html.escape(v.get('email') or '')}</td><td>{v['created']}</td>"
                   f"<td>{len(store.pages_for(k))}</td><td><code>{config.PUBLIC_BASE}/mcp/{k}</code></td></tr>"
                   for k, v in store.keys().items() if v.get("active", True))
    names = {k: v["name"] for k, v in store.keys().items()}
    page_rows = "".join(
        f"<tr><td><a href='/{'p' if m.get('kind') == 'plan' else 'q'}/{m['id']}' target=_blank>{html.escape(m.get('title') or m['id'])}</a></td>"
        f"<td>{html.escape(names.get(m.get('key'), '?'))}</td><td>{html.escape((m.get('updated') or '')[:16].replace('T', ' '))}</td>"
        f"<td><form method=post action='/admin?token={tok}' onsubmit=\"return confirm('Delete this page for good? Anyone with the link will see a not-found page.')\">"
        f"<input type=hidden name=delete_page value='{m['id']}'><button>Delete</button></form></td></tr>"
        for m in store.all_pages()) or "<tr><td colspan=4>No pages yet.</td></tr>"
    order_rows = "".join(
        f"<tr><td>{html.escape(o.get('created','')[:16].replace('T',' '))}</td><td><b>{html.escape(o['answers'].get('family') or o['answers'].get('who',''))}</b><br>{html.escape(o.get('email',''))}</td>"
        f"<td>{len(o['answers']['people'])}</td><td>{html.escape((o.get('payment') or {}).get('code') or (o.get('payment') or {}).get('method',''))}</td>"
        f"<td title='{html.escape(chr(10).join(o.get('log', [])[-6:]))}'>{_status_cell(o)}</td>"
        f"<td>{o.get('swaps',0)}</td><td>{_open_link(o.get('url'))}</td>"
        f"<td><form method=post action='/admin?token={tok}'><input type=hidden name=rebuild value='{o['id']}'><button>Rebuild</button></form></td></tr>"
        for o in family.all_orders()[:200]) or "<tr><td colspan=8>No orders yet.</td></tr>"
    busy = [o for o in family.all_orders()[:200] if o.get("status") in ("paid", "building")] or (made and "Rebuilding" in made)
    busy_note = ("<p style='background:#fff6dd;padding:10px'>Building now. This page refreshes every 15 seconds until every plan is done.</p>"
                 f"<script>setTimeout(function(){{location.href='/admin?token={tok}'}},15000)</script>") if busy else ""
    code_rows = "".join(f"<tr><td><code>{c}</code></td><td>{html.escape(v.get('note') or '')}</td><td>{html.escape(v.get('used_by') or '')}</td></tr>"
                        for c, v in sorted(payments.codes().items(), key=lambda x: x[1].get('made',''), reverse=True)) or "<tr><td colspan=3>None yet.</td></tr>"
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Just Wear This admin</title><style>body{{font:15px system-ui;margin:24px;max-width:1000px}}td{{padding:4px 8px;border-bottom:1px solid #ddd}}input{{font:inherit;padding:6px}}</style>
<h1>Just Wear This admin</h1>{made}
<h2>New connector link</h2><form method=post action="/admin?token={tok}"><input name=name placeholder="Photographer or business name" required size=32>
<input name=email placeholder="Email (optional)" size=28> <button>Make link</button></form>
<h2>Connector links</h2><table><tr><th>Name</th><th>Email</th><th>Made</th><th>Pages</th><th>Link</th></tr>{rows}</table>
<h2>Published pages</h2><table><tr><th>Page</th><th>By</th><th>Updated</th><th></th></tr>{page_rows}</table>
<h2>Family orders</h2>{busy_note}<table><tr><th>When</th><th>Family / email</th><th>People</th><th>Paid by</th><th>Status</th><th>Swaps</th><th>Plan</th><th></th></tr>{order_rows}</table>
<h2>Beta codes</h2><form method=post action="/admin?token={tok}">Make <input name=make_codes type=number value=10 min=1 max=50 style="width:70px"> codes
<input name=note placeholder="Note (e.g. Oct beta moms)" size=28> <button>Make codes</button></form>
<table><tr><th>Code</th><th>Note</th><th>Used by</th></tr>{code_rows}</table>
<p><a href="/admin/links?token={tok}">Shop link health report</a></p>""")


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
            Route("/admin", admin_home, methods=["GET", "POST"]),
            Route("/admin/keys", admin_keys, methods=["GET", "POST"]),
            Route("/admin/links", admin_links, methods=["GET", "POST"]),
            *FAMILY_ROUTES,
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
            try:
                family.resume_unfinished()
            except Exception as e:
                print("resume failed:", e)
            if config.CHECK_ENABLED:
                self._nightly = asyncio.get_running_loop().create_task(links.nightly())
            await send({"type": "lifespan.startup.complete"})
        msg = await receive()
        if msg["type"] == "lifespan.shutdown":
            await self._stack.aclose()
            await send({"type": "lifespan.shutdown.complete"})


app = App()
