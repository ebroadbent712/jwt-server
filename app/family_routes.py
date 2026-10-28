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
label.f{{display:flex;flex-direction:column;gap:6px;font-size:11px;letter-spacing:.2em;text-transform:uppercase}}
label.f input,label.f select{{font:16px Jost,sans-serif;letter-spacing:0;text-transform:none;color:var(--ink);background:#fff;border:0;border-bottom:1px solid var(--ink);border-radius:0;padding:10px 0;width:100%}}
.err{{color:#9b2c2c}}
label.story{{display:flex;gap:14px;align-items:flex-start;border-top:1px solid var(--line);padding:14px 0;cursor:pointer}}
label.story input{{width:20px;height:20px;accent-color:#121212;flex:none;margin-top:4px}}
label.story>span{{display:flex;flex-direction:column;gap:6px}} label.story b{{font-family:"Bodoni Moda",serif;font-size:19px;font-weight:500}}
label.story small{{font-family:Jost,sans-serif;font-size:13px;color:var(--soft)}}
.dots-row{{display:flex;gap:6px}}
.whys{{display:flex;flex-wrap:wrap;gap:8px}} label.why{{cursor:pointer}} label.why input{{position:absolute;opacity:0}}
label.why span{{display:inline-block;border:1px solid var(--line);padding:9px 14px;font-size:15px}}
label.why input:checked+span{{background:var(--ink);color:#fff;border-color:var(--ink)}} label.why input:focus-visible+span{{outline:2px solid var(--ink)}}
.looks{{display:flex;flex-direction:column;gap:8px}} label.look{{display:flex;gap:12px;align-items:center;border:1px solid var(--line);padding:10px;cursor:pointer}}
label.look:has(input:checked){{border-color:var(--ink)}} label.look input{{width:20px;height:20px;accent-color:#121212;flex:none}}
label.look img{{width:52px;height:52px;object-fit:contain}} label.look small{{display:block;color:var(--soft);font-size:13px}} .dots-row i{{width:22px;height:22px;border-radius:50%;border:1px solid var(--line)}}
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


async def api_photo(request: Request):
    """A photo of a piece she already owns, sent from /start/ (already shrunk on her phone). Returns its id."""
    if int(request.headers.get("content-length") or 0) > 12_000_000:
        return JSONResponse({"error": "That photo is too big. Try a smaller one."}, 413)
    data = await request.body()
    if not data or len(data) > 12_000_000:
        return JSONResponse({"error": "That photo didn't come through. Please try again."}, 400)
    try:
        return JSONResponse({"id": family.save_photo(data)})
    except family.BadPhoto as e:
        return JSONResponse({"error": str(e)}, 400)


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


SWAP_WHYS = ["Too frilly", "Too fancy", "Too casual", "Too plain", "Not my style", "I'd rather wear pants", "I'd rather wear a dress"]


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
        whys = [w for w in form.getlist("why") if w in SWAP_WHYS]
        note = (form.get("note") or "").strip()[:500]
        if o["status"] == "building":
            err = "Your last swap is still being made. Give it a minute."
        elif not picked and not note and not whys:
            err = "Pick the piece you'd like swapped, or tell us what you'd like different."
        elif o.get("swaps", 0) >= 25:
            err = "That's a lot of swaps! Reply to your plan email and we'll help by hand."
        else:
            names = {i["id"]: i["name"] for i in family.catalog()["items"]}
            plan = o["plan"]
            who_of = {iid: p["label"] for p in plan["people"] for iid in p["items"]}
            lines = [f"{who_of.get(i, '?')}: swap the {names.get(i, i)} ({i})" for i in picked]
            req = "She asked for a swap. " + (" ".join(lines) + ". " if lines else "") + \
                  (f"What's off for her: {', '.join(w.lower() for w in whys)}. " if whys else "") + (f"Her words: \"{note}\". " if note else "") + \
                  ("Give her something clearly different, not a near twin: a different kind of piece or shape (for example trousers and a sweater "
                   "instead of a dress, or a simple knit instead of a ruffled floral), not the same thing in a slightly different color or print. "
                   "The pieces she swapped away are gone from the list, so don't look for them. " if picked or whys else "") + \
                  "Change only those pieces (and anything that must change so the board still follows the rules). Keep everyone else's outfit, the color story and the copy the same unless the swap needs a small edit."
            o["swapped_out"] = list(dict.fromkeys((o.get("swapped_out") or []) + picked))[-60:]
            o["swaps"] = o.get("swaps", 0) + 1
            o["swap_pending"] = True
            family.log(o, f"swap requested: {lines} {whys} {note}")
            family.save_order(o)
            family.build_async(oid, req)
            return RedirectResponse(f"/o/{oid}", 303)
    names = {i["id"]: i["name"] for i in family.catalog()["items"]}
    names.update({ow["id"]: ow["label"] for ow in o["plan"].get("owned") or [] if isinstance(ow, dict) and ow.get("label")})
    pre = (request.query_params.get("piece") or "").upper()
    people = "".join(
        f"<div class=person><b>{E(p['label'])}</b>" + "".join(
            f"<label class=pc><input type=checkbox name=piece value='{E(i)}'{' checked' if i == pre else ''}><img src='/lib/{E(i)}.jpg' alt='' loading=lazy><span>{E(names.get(i, i))}</span></label>" for i in p["items"]) + "</div>"
        for p in o["plan"]["people"])
    whys = "".join(f"<label class=why><input type=checkbox name=why value='{E(w)}'><span>{E(w)}</span></label>" for w in SWAP_WHYS)
    return _page("Swap a piece", f"""<h1>Swap a piece.</h1>
<p class=soft>Tick anything you'd like changed, or tell us what you're after. Everything else stays the same, and your link doesn't change.</p>
{f'<p class=err>{E(err)}</p>' if err else ''}
<form method=post style="display:flex;flex-direction:column;gap:18px">{people}
<div class=person><b>What's off?</b><span class=soft>Optional. Tick any that fit.</span><div class=whys>{whys}</div></div>
<label style="display:flex;flex-direction:column;gap:6px;font-size:11px;letter-spacing:.2em;text-transform:uppercase">Anything else? (optional)
<textarea name=note placeholder="Dad would rather wear jeans. Something warmer for the baby."></textarea></label>
<button class=btn>Make my swap</button></form>
<p class=soft>Need to change someone's details or style instead? <a href="/o/{E(oid)}/edit" style="color:#121212">Edit a person</a></p>
<p class=soft>Want different colors for everyone? <a href="/o/{E(oid)}/colors" style="color:#121212">Change our colors</a></p>
<p class=soft>Have a piece you already own? <a href="/o/{E(oid)}/own" style="color:#121212">Add something I own</a></p>
<p class=soft><a href="{E(o['url'])}" style="color:#121212">Back to my plan</a></p>""")


PERSON_FIELDS = (("name", "Name"), ("age", "Age"), ("kidAge", "How old"), ("shop", "Shop from"), ("dress", "Dressing up"), ("nope", "Won't wear"))


def _opts(name, choices, cur):
    return f"<select name={name}>" + "".join(f"<option{' selected' if c == cur else ''}>{E(c)}</option>" for c in choices) + "</select>"


async def edit_page(request: Request):
    """Fix a person's details after the plan is made (a wrong age, Women's picked for Dad...). Restyles only what changed."""
    oid = request.path_params["oid"]
    o = family.get_order(oid)
    if not o or not o.get("plan"):
        return _page("Not found", "<h1>We couldn't find that plan.</h1>")
    if not family.can_swap(o):
        return _page("Photo day has passed", f"""<h1>Photo day has passed.</h1>
<p class=soft>Changes are open until your photo date. Your plan is still here:</p><a class=btn href="{E(o['url'])}">Open my plan</a>""")
    a = o["answers"]
    people = [dict(p) for p in a["people"]]
    err = ""
    if request.method == "POST":
        form = await request.form()
        for n, p in enumerate(people):
            for k, _ in PERSON_FIELDS:
                v = form.get(f"{k}{n}")
                if v is not None:
                    p[k] = str(v)
            if form.get(f"styled{n}"):
                p["looks"] = [str(v) for v in form.getlist(f"looks{n}")]
                p["cut"] = str(form.get(f"cut{n}") or "Either")
        if o["status"] == "building":
            err = "Your last change is still being made. Give it a minute."
        elif o.get("swaps", 0) >= 25:
            err = "That's a lot of changes! Reply to your plan email and we'll help by hand."
        else:
            renamed = {old["name"]: new["name"] for old, new in zip(a["people"], people)}
            new_a = dict(a, people=people, photos=[dict(ph, person=renamed.get(ph["person"], ph["person"])) for ph in a.get("photos") or []])
            try:
                new_a = family.clean_answers(new_a)
            except family.BadAnswers as e:
                err = str(e)
            else:
                changes = family.person_changes(a, new_a)
                if not changes:
                    err = "Nothing's changed yet. Edit someone's details, then tap the button."
                else:
                    req = ("She updated her family's details. " + " ".join(changes) + " Restyle only the people whose details changed, "
                           "so every piece fits their new details (a new age or 'shop from' means pieces made for that kind of person; a new style "
                           "means pieces tagged with that style, clearly different from what they had). "
                           "Use each person's current name as their label. Keep everyone else's outfit, her own pieces, the color story "
                           "and the copy the same unless the change needs a small edit.")
                    o["answers"] = new_a
                    o["swaps"] = o.get("swaps", 0) + 1
                    o["swap_pending"] = True
                    family.log(o, f"swap requested: edited people: {' '.join(changes)}")
                    family.save_order(o)
                    family.build_async(oid, req)
                    return RedirectResponse(f"/o/{oid}", 303)
    rows = ""
    for n, p in enumerate(people):
        rows += f"""<div class=person><b>{E(p['name'])}</b>
<label class=f>Name<input name=name{n} value="{E(p['name'])}" maxlength=40 required></label>
<label class=f>Age{_opts(f'age{n}', family.AGES, p['age'])}</label>
<label class=f>How old? (kids only)<input name=kidAge{n} value="{E(p.get('kidAge') or '')}" inputmode=numeric maxlength=2></label>
<label class=f>Shop from{_opts(f'shop{n}', family.SHOPS, p['shop'])}</label>
<label class=f>Dressing up?{_opts(f'dress{n}', ['Happy to', 'Basics only'], p.get('dress') or 'Happy to')}</label>
<label class=f>Anything they won't wear?<input name=nope{n} value="{E(p.get('nope') or '')}" maxlength=160></label>{_style_fields(n, p)}</div>"""
    return _page("Edit a person", f"""<h1>Edit a person.</h1>
<p class=soft>Fix anyone's details or style and we'll restyle just them. Everyone else stays the same, and your link doesn't change.</p>
{f'<p class=err>{E(err)}</p>' if err else ''}
<form method=post style="display:flex;flex-direction:column;gap:18px">{rows}
<button class=btn>Update my plan</button></form>
<p class=soft><a href="{E(o['url'])}" style="color:#121212">Back to my plan</a></p>""")


def _style_fields(n, p):
    """Style picks for Edit a person (women's and girls' shoppers): up to two looks with example pictures, and dresses or pants."""
    looks = family.looks_for(p)
    if not looks:
        return ""
    mine = set(p.get("looks") or [])
    cards = "".join(
        f"<label class=look><input type=checkbox name=looks{n} value='{E(t)}'{' checked' if t in mine else ''}>"
        + "".join(f"<img src='/lib/{E(i)}.jpg' alt='' loading=lazy>" for i in ids)
        + f"<span>{E(label)}<small>{E(words)}</small></span></label>" for t, label, words, ids in looks)
    return (f"<input type=hidden name=styled{n} value=1><div><p class=soft style='font-size:11px;letter-spacing:.2em;text-transform:uppercase'>"
            f"Their style (pick one or two, or none to let us choose)</p><div class=looks>{cards}</div></div>"
            f"<label class=f>Dresses or pants?{_opts(f'cut{n}', family.CUTS, p.get('cut') or 'Either')}</label>")


def _story_choices(cur):
    """The stocked color stories as radio cards: name and swatches (the catalog summaries use styling words moms shouldn't see)."""
    out = ""
    for k, v in family.catalog()["color_stories"].items():
        if not v.get("stocked"):
            continue
        dots = "".join(f"<i style='background:{E(c['hex'])}' title='{E(c['name'])}'></i>" for c in v.get("palette", []))
        now = " <small>(your plan now)</small>" if k == cur else ""
        out += (f"<label class=story><input type=radio name=story value='{E(k)}'{' checked' if k == cur else ''}>"
                f"<span><b>{E(v['name'])}{now}</b><span class=dots-row>{dots}</span></span></label>")
    return out


async def colors_page(request: Request):
    """Change the whole plan's colors without starting over. Counts as a swap; same link."""
    oid = request.path_params["oid"]
    o = family.get_order(oid)
    if not o or not o.get("plan"):
        return _page("Not found", "<h1>We couldn't find that plan.</h1>")
    if not family.can_swap(o):
        return _page("Photo day has passed", f"""<h1>Photo day has passed.</h1>
<p class=soft>Changes are open until your photo date. Your plan is still here:</p><a class=btn href="{E(o['url'])}">Open my plan</a>""")
    a = o["answers"]
    cur = o["plan"].get("color_story")
    stories = family.catalog()["color_stories"]
    err = ""
    if request.method == "POST":
        form = await request.form()
        story = form.get("story") or ""
        love = family._s(form.get("love"), 120)
        never = family._s(form.get("never"), 120)
        if story not in stories or not stories[story].get("stocked"):
            story = ""
        if o["status"] == "building":
            err = "Your last change is still being made. Give it a minute."
        elif o.get("swaps", 0) >= 25:
            err = "That's a lot of changes! Reply to your plan email and we'll help by hand."
        elif (not story or story == cur) and love == a.get("love", "") and never == a.get("never", ""):
            err = "Pick new colors, or tell us the colors you'd love, then tap the button."
        else:
            wish = []
            if story and story != cur:
                wish.append(f"Use the color story {story} ({stories[story]['name']}).")
            if love != a.get("love", ""):
                wish.append(f"Colors she loves now: {love or 'no preference'}.")
            if never != a.get("never", ""):
                wish.append(f"Colors she never wants now: {never or 'none'}.")
            req = ("She wants new colors for her plan. " + " ".join(wish) + " If she didn't name a color story, pick the stocked one "
                   "that best fits her new colors. Restyle the whole family in the new colors: change any piece that doesn't fit them, "
                   "and rewrite the headline and copy to match. Keep everyone's details, her own pieces (build the new colors around "
                   "them) and the setting the same.")
            o["answers"] = dict(a, love=love, never=never)
            o["swaps"] = o.get("swaps", 0) + 1
            o["swap_pending"] = True
            family.log(o, f"swap requested: new colors: {' '.join(wish)}")
            family.save_order(o)
            family.build_async(oid, req)
            return RedirectResponse(f"/o/{oid}", 303)
    owned = " Pieces you photographed stay in, and the new colors are built around them." if a.get("photos") else ""
    return _page("Change our colors", f"""<h1>Change our colors.</h1>
<p class=soft>Pick a new set of colors, or tell us what you'd love, and we'll redo everyone's outfits to match. No starting over, and your link doesn't change.{owned}</p>
{f'<p class=err>{E(err)}</p>' if err else ''}
<form method=post style="display:flex;flex-direction:column;gap:18px">{_story_choices(cur)}
<label class=f>Colors you love (optional)<input name=love value="{E(a.get('love') or '')}" maxlength=120 placeholder="Sage, rust, cream"></label>
<label class=f>Never, please (optional)<input name=never value="{E(a.get('never') or '')}" maxlength=120 placeholder="Orange, bright red"></label>
<button class=btn>Change my colors</button></form>
<p class=soft><a href="{E(o['url'])}" style="color:#121212">Back to my plan</a></p>""")


async def own_page(request: Request):
    """Add a piece she already owns after the plan is made: a photo (uploaded by /api/family/photo) and/or a few words.
    Only that person is restyled around it. Counts as a swap; same link."""
    oid = request.path_params["oid"]
    o = family.get_order(oid)
    if not o or not o.get("plan"):
        return _page("Not found", "<h1>We couldn't find that plan.</h1>")
    if not family.can_swap(o):
        return _page("Photo day has passed", f"""<h1>Photo day has passed.</h1>
<p class=soft>Changes are open until your photo date. Your plan is still here:</p><a class=btn href="{E(o['url'])}">Open my plan</a>""")
    a = o["answers"]
    names = [p["name"] for p in a["people"]]
    photos = a.get("photos") or []
    room = len(photos) < family.MAX_PHOTOS
    err = ""
    if request.method == "POST":
        form = await request.form()
        who = next((n for n in names if n.lower() == family._s(form.get("person"), 40).lower()), "")
        pid = str(form.get("photo") or "")
        what = family._s(form.get("what"), 120)
        if o["status"] == "building":
            err = "Your last change is still being made. Give it a minute."
        elif o.get("swaps", 0) >= 25:
            err = "That's a lot of changes! Reply to your plan email and we'll help by hand."
        elif not who:
            err = "Pick who's wearing it."
        elif pid and not family.photo_ok(pid):
            err = "That photo didn't come through. Please add it again."
        elif pid and not room:
            err = f"Your plan already has {family.MAX_PHOTOS} photos. Tell us about this one in words instead."
        elif not pid and not what:
            err = "Add a photo of your piece, or tell us what it is."
        else:
            new_a = dict(a)
            if pid:
                new_a["photos"] = photos + [{"id": pid, "person": who, "what": what}]
                said = f"{who}'s own {what or 'piece'} (photo id {pid}, the newest photo)"
            else:
                new_a["own"] = family._s(((a.get("own") or "") + f"; {who}: {what}").strip("; "), 500)
                said = f"{who}'s own {what} (no photo, just her words)"
            req = (f"She added a piece she already owns: {said}. Put it in {who}'s outfit"
                   + (" with an owned entry for the photo" if pid else ", using the closest library piece of the same kind and color as its stand-in,")
                   + f" and restyle {who} around it so everything they wear goes with it. If it replaces a piece {who} had, take that piece out. "
                   "Keep everyone else's outfit, her other own pieces, the color story and the copy the same, unless the new piece truly "
                   "needs a small change so the family still looks good together.")
            o["answers"] = new_a
            o["swaps"] = o.get("swaps", 0) + 1
            o["swap_pending"] = True
            family.log(o, f"swap requested: added her own piece: {said}")
            family.save_order(o)
            family.build_async(oid, req)
            return RedirectResponse(f"/o/{oid}", 303)
    who_opts = "".join(f"<option>{E(n)}</option>" for n in names)
    photo_part = f"""<div class=person><b>Your piece</b>
<input type=hidden name=photo id=photo>
<img id=thumb alt="" style="display:none;width:160px;height:160px;object-fit:contain;border:1px solid var(--line)">
<input type=file id=file accept="image/*" style="display:none">
<button type=button class=btn id=pick style="background:#fff;color:var(--ink)">+ Add a photo</button>
<span class=soft id=phmsg>Lay it flat or hang it up, in good light. Shoes count!</span></div>""" if room else         f"<p class=soft>Your plan already has {family.MAX_PHOTOS} photos, so tell us about this piece in words.</p>"
    return _page("Add something I own", f"""<h1>Add something you own.</h1>
<p class=soft>Have a piece you already love? Add it and we'll restyle just that person around it. Everyone else stays the same, and your link doesn't change.</p>
{f'<p class=err>{E(err)}</p>' if err else ''}
<form method=post id=f style="display:flex;flex-direction:column;gap:18px">{photo_part}
<label class=f>Who's wearing it?<select name=person required><option value="">Pick one</option>{who_opts}</select></label>
<label class=f>What is it? <span style="text-transform:none;letter-spacing:0" class=soft>{'Optional with a photo.' if room else ''}</span><input name=what maxlength=120 placeholder="Brown leather boots"></label>
<button class=btn id=go>Add it to my plan</button></form>
<p class=soft><a href="{E(o['url'])}" style="color:#121212">Back to my plan</a></p>
<script>
const file = document.getElementById("file"), pick = document.getElementById("pick"), msg = document.getElementById("phmsg"),
  thumb = document.getElementById("thumb"), photo = document.getElementById("photo"), go = document.getElementById("go");
if (pick) {{
  pick.onclick = () => file.click();
  file.onchange = async () => {{
    const f = file.files[0]; if (!f) return;
    const img = new Image(), url = URL.createObjectURL(f);
    try {{ img.src = url; await img.decode(); }} catch (e) {{ msg.textContent = "That file didn't open as a photo. Try a JPG or PNG."; return; }}
    const k = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight)), c = document.createElement("canvas");
    c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    thumb.src = url; thumb.style.display = "block"; photo.value = ""; go.disabled = true; msg.textContent = "Uploading…";
    try {{
      const blob = await new Promise(res => c.toBlob(res, "image/jpeg", 0.88));
      const r = await fetch("/api/family/photo", {{method: "POST", headers: {{"content-type": "image/jpeg"}}, body: blob}});
      const d = await r.json().catch(() => ({{}}));
      if (!r.ok || !d.id) throw new Error(d.error || "");
      photo.value = d.id; pick.textContent = "Use a different photo"; msg.textContent = "Got it.";
    }} catch (e) {{ thumb.style.display = "none"; msg.textContent = e.message || "That photo didn't upload. Check your connection and try again."; }}
    go.disabled = false;
  }};
}}
</script>""")


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
    Route("/api/family/photo", api_photo, methods=["POST"]),
    Route("/api/stripe/webhook", stripe_webhook, methods=["POST"]),
    Route("/o/{oid}", order_page),
    Route("/o/{oid}/swap", swap_page, methods=["GET", "POST"]),
    Route("/o/{oid}/edit", edit_page, methods=["GET", "POST"]),
    Route("/o/{oid}/colors", colors_page, methods=["GET", "POST"]),
    Route("/o/{oid}/own", own_page, methods=["GET", "POST"]),
]
