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


ADMIN_CSS = """
:root{--ink:#111;--soft:#666;--line:#e3e3e3;--ok:#e9f5ec;--warn:#fff4d6;--bad:#fbeaea}
*{box-sizing:border-box}
body{font:15px/1.45 system-ui,-apple-system,sans-serif;color:var(--ink);background:#fff;margin:0;padding:24px max(16px,env(safe-area-inset-left)) 60px}
main{max-width:980px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:13px;letter-spacing:.12em;text-transform:uppercase;margin:34px 0 10px;border-top:2px solid var(--ink);padding-top:12px}
h3{font-size:15px;margin:22px 0 8px}
.sub{color:var(--soft);margin:0 0 6px}
.note{padding:12px 14px;margin:14px 0;border:1px solid var(--line)}
.note.ok{background:var(--ok)}.note.warn{background:var(--warn)}.note.bad{background:var(--bad)}
.bigform{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0}
input{font:inherit;padding:8px 10px;border:1px solid #bbb;border-radius:4px}
button{font:inherit;padding:8px 14px;border:1px solid var(--ink);background:var(--ink);color:#fff;border-radius:4px;cursor:pointer}
button.ghost{background:#fff;color:var(--ink);padding:5px 10px;font-size:13px}
.wrap{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--soft);font-weight:600;padding:6px 8px;border-bottom:1px solid var(--ink)}
td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top}
code{font-size:13px;word-break:break-all}
.muted{color:var(--soft)}
details{margin:10px 0}
summary{cursor:pointer;font-weight:600;padding:6px 0}
.link{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
"""

ADMIN_JS = """<script>
document.addEventListener('click',async e=>{const b=e.target.closest('[data-copy]');if(!b)return;const t=b.getAttribute('data-copy');
try{await navigator.clipboard.writeText(t);b.textContent='Copied';}catch(_){prompt('Copy this link:',t);}setTimeout(()=>b.textContent='Copy link',1500);});
</script>"""


def _code_link(c):
    return f"{config.PUBLIC_BASE}/start/?code={c}"


def _copy_btn(text, label="Copy link"):
    return f"<button type=button class=ghost data-copy='{html.escape(text)}'>{label}</button>"


async def admin_home(request: Request):
    """A plain page for Emily: mom beta codes and family orders first, photographer connector tools below."""
    if not _admin_ok(request):
        return HTMLResponse("""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Admin</title><form style="font:16px system-ui;margin:40px"><p>Admin password</p><input name=token type=password autofocus>
<button>Open</button></form>""", status_code=200 if not request.query_params.get("token") else 403)
    tok = html.escape(request.query_params.get("token", ""))
    e = html.escape
    made = ""
    if request.method == "POST":
        form = await request.form()
        if form.get("delete_page"):
            pid = str(form["delete_page"])
            meta = store.page_meta(pid) or {}
            if store.delete_page(pid):
                made = f"<div class='note bad'>Deleted <b>{e(meta.get('title') or pid)}</b>. That link now shows the not-found page.</div>"
        elif form.get("code_for"):
            name = str(form["code_for"]).strip()[:60]
            c = payments.make_code_for(name)
            link = _code_link(c)
            made = (f"<div class='note ok'><b>{e(name)}'s link is ready.</b> Paste it into her \"When she says yes\" text."
                    f"<div class=link style='margin-top:8px'><code>{e(link)}</code>{_copy_btn(link)}</div></div>")
        elif form.get("make_codes"):
            made_codes = payments.make_codes(form.get("make_codes") or 1, (form.get("note") or "").strip())
            made = "<div class='note ok'>New spare codes (one use each):<br><code>" + "<br>".join(made_codes) + "</code></div>"
        elif form.get("rebuild"):
            o = family.get_order(str(form["rebuild"]))
            if o:
                if o["status"] == "awaiting_payment":
                    o["status"] = "paid"
                family.log(o, "rebuild from admin")
                family.save_order(o)
                family.build_async(o["id"])
                made = f"<div class='note ok'>Rebuilding {e(o['email'])}'s plan. This page updates itself until it's done.</div>"
        elif form.get("name"):
            key = store.create_key(form["name"].strip(), (form.get("email") or "").strip())
            made = (f"<div class='note ok'>Connector link for <b>{e(form['name'])}</b>:"
                    f"<div class=link style='margin-top:8px'><code>{config.PUBLIC_BASE}/mcp/{key}</code>{_copy_btn(f'{config.PUBLIC_BASE}/mcp/{key}')}</div></div>")

    orders = family.all_orders()[:200]
    by_id = {o["id"]: o for o in orders}

    # ----- beta codes, split into what Emily actually needs to see -----
    cs = sorted(payments.codes().items(), key=lambda x: (x[1].get("made", ""), x[0]), reverse=True)
    waiting = [(c, v) for c, v in cs if v.get("for") and not v.get("used_by")]
    used = [(c, v) for c, v in cs if v.get("used_by")]
    spare = [(c, v) for c, v in cs if not v.get("for") and not v.get("used_by")]

    def who_used(v):
        o = by_id.get(v.get("used_by")) or family.get_order(v.get("used_by") or "") or {}
        fam = (o.get("answers") or {}).get("family") or (o.get("answers") or {}).get("who") or ""
        return " · ".join(x for x in (fam, o.get("email", "")) if x) or e(v.get("used_by") or "")

    waiting_rows = "".join(
        f"<tr><td><b>{e(v['for'])}</b></td><td class=muted>{e(v.get('made',''))}</td><td><code>{c}</code></td><td>{_copy_btn(_code_link(c))}</td></tr>"
        for c, v in waiting) or "<tr><td colspan=4 class=muted>Nobody yet. Make a link above when a mom says yes.</td></tr>"
    used_rows = "".join(
        f"<tr><td><b>{e(v.get('for') or v.get('note') or '')}</b></td><td>{e(who_used(v))}</td><td class=muted>{e((v.get('used') or '')[:10])}</td>"
        f"<td>{_open_link((by_id.get(v.get('used_by')) or {}).get('url'))}</td></tr>"
        for c, v in used) or "<tr><td colspan=4 class=muted>No codes used yet.</td></tr>"
    spare_rows = "".join(
        f"<tr><td><code>{c}</code></td><td class=muted>{e(v.get('note') or '')}</td><td class=muted>{e(v.get('made',''))}</td><td>{_copy_btn(_code_link(c))}</td></tr>"
        for c, v in spare)

    # ----- family orders -----
    order_rows = "".join(
        f"<tr><td class=muted>{e(o.get('created','')[:16].replace('T',' '))}</td><td><b>{e(o['answers'].get('family') or o['answers'].get('who',''))}</b><br><span class=muted>{e(o.get('email',''))}</span></td>"
        f"<td>{len(o['answers']['people'])}</td><td>{e((o.get('payment') or {}).get('code') or (o.get('payment') or {}).get('method',''))}</td>"
        f"<td title='{e(chr(10).join(o.get('log', [])[-6:]))}'>{_status_cell(o)}</td>"
        f"<td>{o.get('swaps',0)}</td><td>{_open_link(o.get('url'))}</td>"
        f"<td><form method=post action='/admin?token={tok}'><input type=hidden name=rebuild value='{o['id']}'><button class=ghost>Rebuild</button></form></td></tr>"
        for o in orders) or "<tr><td colspan=8 class=muted>No orders yet.</td></tr>"
    busy = [o for o in orders if o.get("status") in ("paid", "building")] or (made and "Rebuilding" in made)
    busy_note = ("<div class='note warn'>Building now. This page refreshes every 15 seconds until every plan is done.</div>"
                 f"<script>setTimeout(function(){{location.href='/admin?token={tok}'}},15000)</script>") if busy else ""

    # ----- photographer tools -----
    rows = "".join(f"<tr><td>{e(v['name'])}</td><td>{e(v.get('email') or '')}</td><td class=muted>{v['created']}</td>"
                   f"<td>{len(store.pages_for(k))}</td><td><code>{config.PUBLIC_BASE}/mcp/{k}</code></td></tr>"
                   for k, v in store.keys().items() if v.get("active", True)) or "<tr><td colspan=5 class=muted>None yet.</td></tr>"
    names = {k: v["name"] for k, v in store.keys().items()}
    pages = store.all_pages()
    page_rows = "".join(
        f"<tr><td><a href='/{'p' if m.get('kind') == 'plan' else 'q'}/{m['id']}' target=_blank>{e(m.get('title') or m['id'])}</a></td>"
        f"<td>{e(names.get(m.get('key'), '?'))}</td><td class=muted>{e((m.get('updated') or '')[:16].replace('T', ' '))}</td>"
        f"<td><form method=post action='/admin?token={tok}' onsubmit=\"return confirm('Delete this page for good? Anyone with the link will see a not-found page.')\">"
        f"<input type=hidden name=delete_page value='{m['id']}'><button class=ghost>Delete</button></form></td></tr>"
        for m in pages) or "<tr><td colspan=4 class=muted>No pages yet.</td></tr>"

    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Just Wear This admin</title><style>{ADMIN_CSS}</style>
<main>
<h1>Just Wear This admin</h1>
<p class=sub>{len(waiting)} waiting on a plan · {len(used)} used {'code' if len(used)==1 else 'codes'} · {len(orders)} family {'order' if len(orders)==1 else 'orders'}</p>
{made}

<h2>Mom beta testers</h2>
<h3>A mom said yes? Make her link.</h3>
<form method=post action="/admin?token={tok}" class=bigform><input name=code_for placeholder="Her name" required maxlength=60 size=24 aria-label="Mom's name"><button>Make her link</button></form>
<p class="sub">One code per mom. Her link fills in the code, so she never has to type it.</p>

<h3>Sent, not used yet ({len(waiting)})</h3>
<div class=wrap><table><tr><th>Mom</th><th>Made</th><th>Code</th><th></th></tr>{waiting_rows}</table></div>

<h3>Used ({len(used)})</h3>
<div class=wrap><table><tr><th>Mom</th><th>Order</th><th>Used</th><th>Plan</th></tr>{used_rows}</table></div>

<details><summary>Spare codes ({len(spare)} unused, from earlier batches)</summary>
<p class=sub>Older codes made in bulk. They still work. You don't need these anymore, but they're here if you want one.</p>
<div class=wrap><table><tr><th>Code</th><th>Note</th><th>Made</th><th></th></tr>{spare_rows or "<tr><td colspan=4 class=muted>None.</td></tr>"}</table></div>
<form method=post action="/admin?token={tok}" class=bigform>Make <input name=make_codes type=number value=5 min=1 max=50 style="width:70px" aria-label="How many"> spare codes
<input name=note placeholder="Note" size=20 aria-label="Note"> <button class=ghost>Make codes</button></form>
</details>

<h2>Family orders</h2>{busy_note}
<div class=wrap><table><tr><th>When</th><th>Family / email</th><th>People</th><th>Paid by</th><th>Status</th><th>Swaps</th><th>Plan</th><th></th></tr>{order_rows}</table></div>

<h2>Photographers</h2>
<details><summary>New connector link</summary>
<form method=post action="/admin?token={tok}" class=bigform><input name=name placeholder="Photographer or business name" required size=30 aria-label="Business name">
<input name=email placeholder="Email (optional)" size=24 aria-label="Email"> <button>Make link</button></form></details>
<details><summary>Connector links ({sum(1 for v in store.keys().values() if v.get("active", True))})</summary>
<div class=wrap><table><tr><th>Name</th><th>Email</th><th>Made</th><th>Pages</th><th>Link</th></tr>{rows}</table></div></details>
<details><summary>Published pages ({len(pages)})</summary>
<div class=wrap><table><tr><th>Page</th><th>By</th><th>Updated</th><th></th></tr>{page_rows}</table></div></details>

<h2>Shop links</h2>
<p><a href="/admin/links?token={tok}">Shop link health report</a></p>
</main>{ADMIN_JS}""")


async def admin_links(request: Request):
    if not _admin_ok(request):
        return PlainTextResponse("Not allowed", status_code=403)
    if request.method == "POST":
        asyncio.get_running_loop().create_task(links.check_all(request.query_params.get("host")))
        return JSONResponse({"started": True, "note": "Takes 20 to 40 minutes. Reload this page later."})
    h, bc = links.health(), links.browser_checks()
    s = links.summary()
    run = links.last_run()
    urls = links.all_links()
    rows = []
    for u, ps in urls.items():
        ef = links.effective(u, h, bc)
        if ef["status"] != "ok":
            rows.append((u, ps, ef))
    rows.sort(key=lambda x: (x[2]["status"] != "dead", x[0]))
    e = html.escape
    body = "".join(f"<tr><td>{'DEAD' if ef['status'] == 'dead' else 'not checked'}</td><td>{e(', '.join(ps))}</td>"
                   f"<td><a href='{e(u)}'>{e(u[:70])}</a></td><td>{e(ef['note'])}</td><td>{e(ef['source'])}</td>"
                   f"<td>{e(ef['checked'])}</td></tr>" for u, ps, ef in rows)
    ran = (f"Last server check: {e(run.get('finished', ''))} ({run.get('checked', 0)} links)." if run
           else "Last server check: none recorded yet.")
    return HTMLResponse(f"""<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Link health</title><style>body{{font:14px system-ui;margin:20px}}td{{padding:4px 8px;border-bottom:1px solid #ddd;vertical-align:top}}</style>
<h1>Shop link health</h1><p>{s['links']} links: {s['ok']} live, {s['dead']} dead, {s['unchecked']} not checked.
Checked by the server: {s['checked_by']['server']}. Checked in the browser: {s['checked_by']['browser']}.</p><p>{ran}</p>
<p><b>Pieces with no live link ({len(s['pieces_with_no_live_link'])}):</b> {e(', '.join(s['pieces_with_no_live_link'])) or 'none'}</p>
<table><tr><th>Status</th><th>Pieces</th><th>Link</th><th>Why</th><th>Checked by</th><th>When</th></tr>{body}</table>""")


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
