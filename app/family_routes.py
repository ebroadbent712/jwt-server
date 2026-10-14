"""Web routes for the family version: order, pay, status, swaps."""
import html, json

import io, os

import httpx
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from . import config, family, payments

E = html.escape


def _page(title, body, refresh_js=""):
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>{E(title)} · Just Wear This</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Anton&family=Bodoni+Moda:ital,opsz,wght@0,6..96,500;1,6..96,400&family=Jost:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{{--ink:#121212;--soft:#6b6b6b;--line:#e2e2e2}}*{{box-sizing:border-box}}
body{{margin:0;background:#fff;color:var(--ink);font:16px/1.55 Jost,system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
main{{max-width:560px;margin:0 auto;padding:18px 22px 60px;display:flex;flex-direction:column;gap:22px}}
.mark{{font-family:Anton,Impact,sans-serif;font-size:17px;text-transform:uppercase;border-bottom:1px solid var(--ink);padding-bottom:12px}}
h1{{font-family:"Bodoni Moda",Georgia,serif;font-size:clamp(30px,8vw,42px);line-height:1.08;font-weight:500;margin:0}}
p{{margin:0}} .soft{{color:var(--soft)}}
.btn{{display:block;text-align:center;text-decoration:none;font:400 12px Jost,sans-serif;letter-spacing:.24em;text-transform:uppercase;
padding:17px;border:1px solid var(--ink);background:var(--ink);color:#fff;cursor:pointer;width:100%}}
.dots::after{{content:"";animation:d 1.5s steps(4) infinite}}@keyframes d{{0%{{content:""}}25%{{content:"."}}50%{{content:".."}}75%{{content:"..."}}}}
.person{{border-top:1px solid var(--ink);padding:14px 0;display:flex;flex-direction:column;gap:8px}}
.person b{{font-family:"Bodoni Moda",serif;font-size:21px;font-weight:500}}
label.pc{{display:flex;gap:14px;align-items:center;font-size:15px;cursor:pointer;padding:4px 0}}
label.pc input{{width:20px;height:20px;accent-color:#121212;flex:none}}
label.pc img{{width:72px;height:72px;object-fit:contain;flex:none;border:1px solid var(--line)}}
label.pc:has(input:checked) img{{border-color:var(--ink)}}
textarea{{font:16px Jost,sans-serif;width:100%;min-height:110px;border:1px solid var(--ink);padding:12px 14px;border-radius:0}}
.err{{color:#9b2c2c}}
</style></head><body><main><div class="mark">Just Wear This.</div>{body}</main>{refresh_js}</body></html>""")


def _poll_js(oid):
    return f"""<script>
(async function poll(){{
  try {{ const r = await fetch('/api/family/status/{oid}', {{cache:'no-store'}}); const s = await r.json();
    if (s.status === 'ready' && s.url && !s.swapping) {{ location.href = s.url; return; }}
    if (s.status === 'failed') {{ location.reload(); return; }}
  }} catch (e) {{}}
  setTimeout(poll, 4000);
}})();
</script>"""


def _maybe_confirm_paid(o):
    """Back from Stripe before the webhook landed: ask Stripe directly."""
    sid = (o.get("payment") or {}).get("session")
    if o["status"] != "awaiting_payment" or not sid or not config.STRIPE_SECRET_KEY:
        return o
    try:
        r = httpx.get(f"https://api.stripe.com/v1/checkout/sessions/{sid}", auth=(config.STRIPE_SECRET_KEY, ""), timeout=15)
        if r.status_code == 200 and r.json().get("payment_status") == "paid":
            return _mark_paid(o["id"], "checked on return")
    except httpx.HTTPError:
        pass
    return o


def _mark_paid(oid, how):
    o = family.get_order(oid)
    if o and o["status"] == "awaiting_payment":
        o["status"] = "paid"
        family.log(o, f"paid ({how})")
        family.save_order(o)
        family.build_async(oid)
    return family.get_order(oid)


# ---------- API ----------
async def api_order(request: Request):
    if not config.ANTHROPIC_API_KEY:
        return JSONResponse({"error": "We're not quite open yet. Check back soon!"}, 503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Something went wrong sending your answers. Please try again."}, 400)
    try:
        a = family.clean_answers(body.get("answers"))
    except family.BadAnswers as e:
        return JSONResponse({"error": str(e)}, 400)
    code = (body.get("code") or "").strip()
    if code:
        if not payments.code_ok(code):
            return JSONResponse({"error": "That code doesn't work (or it's already been used). Check it, or leave it blank to pay."}, 400)
        o = family.new_order(a, "code")
        if not payments.use_code(code, o["id"]):
            return JSONResponse({"error": "That code was just used. Leave it blank to pay."}, 400)
        o["payment"]["code"] = payments.norm(code)
        family.save_order(o)
        _mark_paid(o["id"], "beta code " + payments.norm(code))
        return JSONResponse({"next": f"/o/{o['id']}"})
    o = family.new_order(a, "stripe")
    try:
        url, sid = payments.checkout_url(o)
    except payments.PaymentError as e:
        family.log(o, f"checkout failed: {e}")
        family.save_order(o)
        return JSONResponse({"error": "Checkout isn't available right now. Please try again in a few minutes."}, 503)
    o["payment"]["session"] = sid
    family.save_order(o)
    return JSONResponse({"next": url})


async def api_status(request: Request):
    o = family.get_order(request.path_params["oid"])
    if not o:
        return JSONResponse({"status": "missing"}, 404)
    return JSONResponse({"status": o["status"], "url": o.get("url") if o["status"] == "ready" else None,
                         "swapping": bool(o.get("swap_pending")),
                         "problem": (o.get("error") or "")[:300] if o["status"] == "failed" else "",
                         "last": ((o.get("log") or [""])[-1])[:400]})


async def stripe_webhook(request: Request):
    payload = await request.body()
    try:
        ev = payments.verify_webhook(payload, request.headers.get("stripe-signature", ""))
    except payments.PaymentError as e:
        return JSONResponse({"error": str(e)}, 400)
    if ev.get("type") in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
        s = ev["data"]["object"]
        oid = s.get("client_reference_id") or (s.get("metadata") or {}).get("order")
        if oid and s.get("payment_status") == "paid":
            _mark_paid(oid, "stripe webhook")
    return JSONResponse({"ok": True})


# ---------- pages ----------
async def order_page(request: Request):
    oid = request.path_params["oid"]
    o = family.get_order(oid)
    if not o:
        return _page("Not found", "<h1>We couldn't find that plan.</h1><p class=soft>Check the link in your email.</p>")
    o = _maybe_confirm_paid(o)
    who = E(o["answers"]["who"])
    st = o["status"]
    if st == "ready" and not o.get("swap_pending"):
        return RedirectResponse(o["url"], 302)
    if st == "awaiting_payment":
        return _page("Almost there", f"""<h1>Almost there, {who}.</h1>
<p class=soft>We're waiting on your payment to finish. This page will move on by itself.</p>""", _poll_js(oid))
    if st == "failed":
        return _page("Hang tight", f"""<h1>Hang tight, {who}.</h1>
<p>Your plan needs a little extra care, so a real person is finishing it. It'll be in your inbox at {E(o['email'])} soon, usually within a few hours.</p>""")
    return _page("Styling your family", f"""<h1>Styling your family<span class=dots></span></h1>
<p>We're picking every outfit, {who}. It takes about a minute. Stay here and your plan will open, or close this page: the link is on its way to {E(o['email'])}.</p>""", _poll_js(oid))


async def swap_page(request: Request):
    oid = request.path_params["oid"]
    o = family.get_order(oid)
    if not o or not o.get("plan"):
        return _page("Not found", "<h1>We couldn't find that plan.</h1>")
    if not family.can_swap(o):
        return _page("Photo day has passed", f"""<h1>Photo day has passed.</h1>
<p class=soft>Swaps are open until your photo date. Your plan is still here:</p><a class=btn href="{E(o['url'])}">Open my plan</a>""")
    err = ""
    if request.method == "POST":
        form = await request.form()
        picked = form.getlist("piece")
        note = (form.get("note") or "").strip()[:500]
        if o["status"] == "building":
            err = "Your last swap is still being made. Give it a minute."
        elif not picked and not note:
            err = "Pick the piece you'd like swapped, or tell us what you'd like different."
        elif o.get("swaps", 0) >= 25:
            err = "That's a lot of swaps! Reply to your plan email and we'll help by hand."
        else:
            names = {i["id"]: i["name"] for i in family.catalog()["items"]}
            plan = o["plan"]
            who_of = {iid: p["label"] for p in plan["people"] for iid in p["items"]}
            lines = [f"{who_of.get(i, '?')}: swap the {names.get(i, i)} ({i})" for i in picked]
            req = "She asked for a swap. " + (" ".join(lines) + ". " if lines else "") + (f"Her words: \"{note}\". " if note else "") + \
                  "Change only those pieces (and anything that must change so the board still follows the rules). Keep everyone else's outfit, the color story and the copy the same unless the swap needs a small edit."
            o["swaps"] = o.get("swaps", 0) + 1
            o["swap_pending"] = True
            family.log(o, f"swap requested: {lines} {note}")
            family.save_order(o)
            family.build_async(oid, req)
            return RedirectResponse(f"/o/{oid}", 303)
    names = {i["id"]: i["name"] for i in family.catalog()["items"]}
    pre = (request.query_params.get("piece") or "").upper()
    people = "".join(
        f"<div class=person><b>{E(p['label'])}</b>" + "".join(
            f"<label class=pc><input type=checkbox name=piece value='{E(i)}'{' checked' if i == pre else ''}><img src='/lib/{E(i)}.jpg' alt='' loading=lazy><span>{E(names.get(i, i))}</span></label>" for i in p["items"]) + "</div>"
        for p in o["plan"]["people"])
    return _page("Swap a piece", f"""<h1>Swap a piece.</h1>
<p class=soft>Tick anything you'd like changed, or tell us what you're after. Everything else stays the same, and your link doesn't change.</p>
{f'<p class=err>{E(err)}</p>' if err else ''}
<form method=post style="display:flex;flex-direction:column;gap:18px">{people}
<label style="display:flex;flex-direction:column;gap:6px;font-size:11px;letter-spacing:.2em;text-transform:uppercase">Anything else? (optional)
<textarea name=note placeholder="Dad would rather wear jeans. Something warmer for the baby."></textarea></label>
<button class=btn>Make my swap</button></form>
<p class=soft><a href="{E(o['url'])}" style="color:#121212">Back to my plan</a></p>""")


async def piece_thumb(request: Request):
    """Small square picture of a library piece (for the swap page), made once and kept on the disk."""
    iid = request.path_params["iid"].upper()
    item = next((i for i in family.catalog()["items"] if i["id"] == iid), None)
    if not item:
        return Response(status_code=404)
    out = os.path.join(config.THUMBS, iid + ".jpg")
    if not os.path.exists(out):
        from PIL import Image
        src = os.path.join(config.ENGINE, "library", "images", item["file"])
        if not os.path.exists(src):
            return Response(status_code=404)
        im = Image.open(src).convert("RGB")
        im.thumbnail((240, 240))
        bg = Image.new("RGB", (240, 240), "white")
        bg.paste(im, ((240 - im.width) // 2, (240 - im.height) // 2))
        bg.save(out, "JPEG", quality=85)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


ROUTES = [
    Route("/lib/{iid}.jpg", piece_thumb),
    Route("/api/family/order", api_order, methods=["POST"]),
    Route("/api/family/status/{oid}", api_status),
    Route("/api/stripe/webhook", stripe_webhook, methods=["POST"]),
    Route("/o/{oid}", order_page),
    Route("/o/{oid}/swap", swap_page, methods=["GET", "POST"]),
]
