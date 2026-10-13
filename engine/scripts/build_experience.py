"""The client's outfit plan as a tap-through page: the board itself up top (tap a person to jump to their pieces),
check-offs that remember themselves on the client's phone, palette, why it works and the week-before list.
Usage: python3 build_experience.py <plan.json> --out <folder>   (writes <slug>-plan.html)
Publish the HTML as an artifact and send the client the link."""
import argparse, base64, contextlib, html, io, json, os, re, sys
from urllib.parse import urlparse
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "library")
sys.path.insert(0, HERE)
import build_board as bb  # noqa: E402

STORES = {"target.com": "Target", "oldnavy.gap.com": "Old Navy", "gap.com": "Gap", "gapfactory.com": "Gap Factory",
          "kohls.com": "Kohl's", "hm.com": "H&M", "walmart.com": "Walmart", "amazon.com": "Amazon", "landsend.com": "Lands' End",
          "abercrombie.com": "Abercrombie", "factory.jcrew.com": "J.Crew Factory", "jcrew.com": "J.Crew", "madewell.com": "Madewell",
          "bananarepublic.gap.com": "Banana Republic", "llbean.com": "L.L.Bean", "boden.com": "Boden", "hopeandhenry.com": "Hope & Henry",
          "hannaandersson.com": "Hanna Andersson", "janieandjack.com": "Janie and Jack", "petalandpup.com": "Petal & Pup",
          "lulus.com": "Lulus", "balticborn.com": "Baltic Born", "quince.com": "Quince", "mango.com": "Mango", "everlane.com": "Everlane",
          "dsw.com": "DSW", "nordstrom.com": "Nordstrom", "anthropologie.com": "Anthropologie", "freepeople.com": "Free People",
          "thereformation.com": "Reformation", "sezane.com": "Sézane", "shopdoen.com": "Dôen", "jacadi.us": "Jacadi",
          "rachelriley.com": "Rachel Riley", "ryleeandcru.com": "Rylee + Cru", "samedelman.com": "Sam Edelman", "clarks.com": "Clarks",
          "vince.com": "Vince", "tnuck.com": "Tuckernuck", "christydawn.com": "Christy Dawn", "fahertybrand.com": "Faherty", "littleenglish.com": "Little English", "shopdressup.com": "DressUp", "hillhousehome.com": "Hill House", "toddsnyder.com": "Todd Snyder"}
TIERS = [("everyday", "Everyday"), ("mid", "Mid"), ("splurge", "Splurge")]


def store_name(url):
    host = urlparse(url).netloc.lower()
    for dom in sorted(STORES, key=len, reverse=True):
        if host == dom or host.endswith("." + dom):
            return STORES[dom]
    return host.replace("www.", "").split(".")[0].title()


def data_uri(im, w=520, q=80):
    im = im.convert("RGB")
    if im.width > w:
        im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def readable_on(hexs):
    h = hexs.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#1d1d1d" if lum > 0.55 else "#ffffff"


def contact_lines(settings, e):
    """Email always if given; the phone only as the photographer wants it used (text or call)."""
    out = []
    email = settings.get("contact_email") or (settings.get("contact") if "@" in str(settings.get("contact", "")) else "")
    if email:
        out.append(f'<span class="contact"><small>Email</small> {e(email)}</span>')
    phone = settings.get("contact_phone")
    if phone:
        how = "Text" if settings.get("texting", True) else "Call"
        out.append(f'<span class="contact"><small>{how}</small> {e(phone)}</span>')
    return "\n    ".join(out)


def recs_section(settings, plan, e):
    """Optional 'before your session' favorites: the photographer's saved list, adjusted per plan.
    plan["recommendations"] replaces the list for one session; plan["skip_recommendations"] drops names."""
    recs = plan.get("recommendations", settings.get("recommendations") or [])
    skip = {s.lower() for s in plan.get("skip_recommendations", [])}
    recs = [r for r in recs if r.get("name") and r["name"].lower() not in skip]
    if not recs:
        return ""
    studio = settings.get("studio_name") or "your photographer"
    cards = []
    for r in recs:
        bits = [f'<span class="rkind">{e(r.get("kind", ""))}</span>' if r.get("kind") else "",
                f'<span class="rname">{e(r["name"])}</span>',
                f'<p class="rnote">{e(r["note"])}</p>' if r.get("note") else ""]
        reach = []
        for key, lab in (("link", "Web"), ("instagram", "Instagram"), ("phone", "Phone")):
            v = r.get(key)
            if not v:
                continue
            if key == "link" and str(v).startswith("http"):
                shown = re.sub(r"^https?://(www\.)?", "", v).rstrip("/")
                reach.append(f'<a class="rreach" href="{e(v)}" target="_blank" rel="noopener"><small>{lab}</small> {e(shown)}</a>')
            else:
                reach.append(f'<span class="rreach"><small>{lab}</small> {e(v)}</span>')
        bits.append("".join(reach))
        if r.get("perk"):
            bits.append(f'<span class="rperk">{e(r["perk"])}</span>')
        cards.append('<li class="rec">' + "".join(b for b in bits if b) + "</li>")
    return (f'<section class="colors recs"><h2>Before your session</h2>'
            f'<p class="story">A few favorites from {e(studio)}.</p><ul class="reclist">{"".join(cards)}</ul></section>')


def build(plan_path, out_dir, pdf=False):
    plan = json.load(open(plan_path))
    catalog = json.load(open(os.path.join(LIB, "catalog.json")))
    settings = json.load(open(os.path.join(ROOT, "settings.json")))
    settings.update(plan.get("settings_override", {}))
    items = {it["id"]: dict(it) for it in catalog["items"]}
    missing = [i for p in plan["people"] for i in p["items"] if i not in items]
    if missing:
        sys.exit(f"Unknown item ids (not in the library): {missing}")
    smart = catalog.get("smart_links", {})
    base = smart.get("base", "https://justwearthis.co/s/") if smart.get("enabled") else None

    owned = {}
    for o in plan.get("owned", []):
        if isinstance(o, dict):
            owned[o["id"]] = o
        else:
            owned[o] = {"id": o}

    pal = plan.get("palette") or bb.board_palette(plan, items, catalog)
    anchor = pal[0]["hex"] if pal else "#2F4A3A"
    first = plan["people"][0]["items"]
    for i in first:
        if items[i]["category"] == "dress" or items[i].get("layout_role") == "hero":
            anchor = items[i].get("hex") or anchor
            break

    os.makedirs(out_dir, exist_ok=True)
    slug = bb.slugify(plan["family_name"])
    # page 1 of the board is the first thing they see; each person's panel is a tap target
    if pdf:  # only when the photographer asks for a printable version
        bb.build(plan_path, out_dir)
    view_dir = os.path.join(out_dir, ".page-view")
    bb.HIDE_LABELS, bb.VIEW_COLS = True, 2
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            bb.build(plan_path, view_dir)  # the board, two people across and without labels, for a phone
    finally:
        bb.HIDE_LABELS, bb.VIEW_COLS = False, None
    for line in buf.getvalue().splitlines():  # pass CHECK lines through; the engine's own PDF is internal, not a deliverable
        if line.startswith("Board PDF:"):
            continue
        print(line.replace("Preview PNG:", "Board preview (look at this):"))
    board_png = os.path.join(view_dir, f"{slug}-board-preview.png")
    panels = json.load(open(os.path.join(view_dir, f"{slug}-panels.json")))
    # keep only the people grid (the page has its own header, palette and story)
    full = Image.open(board_png)
    X0 = min(pn["x"] for pn in panels); X1 = max(pn["x"] + pn["w"] for pn in panels)
    Y0 = min(pn["y"] for pn in panels); Y1 = max(pn["y"] + pn["h"] for pn in panels)
    crop = full.crop((int(X0 * full.width), int(Y0 * full.height), int(X1 * full.width), int(Y1 * full.height)))
    panels = [dict(pn, x=(pn["x"] - X0) / (X1 - X0), y=(pn["y"] - Y0) / (Y1 - Y0), w=pn["w"] / (X1 - X0), h=pn["h"] / (Y1 - Y0)) for pn in panels]
    lineup_uri = data_uri(crop, w=1300, q=86)

    pieces, numbering, uses = [], {}, {}
    for p in plan["people"]:
        for i in p["items"]:
            if i not in numbering:
                numbering[i] = len(numbering) + 1
            uses.setdefault(i, []).append(p["label"])
    img_cache = {}
    for i, n in sorted(numbering.items(), key=lambda kv: kv[1]):
        it = items[i]
        name = owned.get(i, {}).get("label") or it["name"]
        if owned.get(i, {}).get("photo"):
            try:
                im = bb.client_photo(owned[i]["photo"], owned[i].get("crop"), owned[i].get("clean", True))
            except Exception:
                im = Image.open(os.path.join(LIB, "images", it["file"]))
        else:
            im = Image.open(os.path.join(LIB, "images", it["file"]))
        img_cache[i] = data_uri(im)
        links = []
        for key, lab in TIERS:
            raw = (it.get("shop_links") or {}).get(key)
            if raw:
                links.append({"tier": lab, "store": store_name(raw), "url": f"{base}{i}-{key}" if base else raw})
        pieces.append({"id": i, "n": n, "name": name, "for": uses[i], "img": i, "owned": i in owned,
                       "links": links, "cat": it["category"], "note": (plan.get("piece_notes") or {}).get(i, "")})

    people = [{"label": p["label"], "items": p["items"], "note": (p.get("note") or {}).get("text", "").replace("\n", " ")}
              for p in plan["people"]]
    data = {"slug": slug, "pieces": pieces, "people": people, "checklist": plan.get("prep_checklist", [])}

    e = html.escape
    if not (settings.get("studio_name") or "").strip():
        print("CHECK (fix before delivering): no studio name. Ask the photographer for their business details and put them in settings_override.")
    studio = settings.get("studio_name") or "your photographer"
    website = settings.get("website") or ""
    swatches = "".join(f'<li><span class="chip" style="background:{e(sw["hex"])}"></span><span>{e(sw["name"])}</span></li>' for sw in pal)
    headline = "".join(f"<span>{e(h)}</span>" for h in plan.get("headline", [])[:3])
    names = "".join(f'<a class="spot" href="#p-{k}" style="left:{pn["x"] * 100:.2f}%;top:{pn["y"] * 100:.2f}%;width:{pn["w"] * 100:.2f}%;height:{pn["h"] * 100:.2f}%" aria-label="See {e(pn["label"])}\'s outfit"></a>'
                    for k, pn in enumerate(panels))
    tabs = '<button class="tab on" data-f="all" type="button">Everyone</button>' + "".join(
        f'<button class="tab" data-f="{k}" type="button">{e(p["label"])}</button>' for k, p in enumerate(people))
    sub = " · ".join(x for x in [plan.get("subtitle_right", ""), plan.get("dress_level", "")] if x)
    where = " · ".join(x.replace(" | ", " · ") for x in [plan.get("title_right", ""), plan.get("subtitle_right", "")] if x)
    m = re.match(r"^(.*\S)\s+(family)$", plan["family_name"].strip(), re.I)
    family_html = f"{e(m.group(1))} <em>family</em>" if m else e(plan["family_name"])
    photo = ""
    if plan.get("hero_photo"):
        try:
            ph = Image.open(plan["hero_photo"])
            photo = f'<img class="photo" src="{data_uri(ph, w=1400, q=84)}" alt="">'
        except Exception as ex:
            print(f"CHECK (fix before delivering): couldn't use the session photo {plan['hero_photo']} ({ex}); the page goes without it.")
    imgs_js = json.dumps(img_cache)

    page = TEMPLATE
    for k, v in {
        "{{TITLE}}": e(f"{plan['family_name'].replace('The ', '')} Outfit Plan"),
        "{{FAMILY}}": e(plan["family_name"]), "{{FAMILY_HTML}}": family_html, "{{WHERE}}": e(where), "{{PHOTO}}": photo,
        "{{LOCATION}}": e(plan.get("title_right", "")), "{{SUB}}": e(sub),
        "{{STUDIO}}": e(studio), "{{WEBSITE}}": e(website),
        "{{CONTACT}}": contact_lines(settings, e), "{{RECS}}": recs_section(settings, plan, e), "{{ACCENT}}": anchor, "{{ACCENT_INK}}": readable_on(anchor),
        "{{LINEUP}}": lineup_uri, "{{NAMES}}": names, "{{SWATCHES}}": swatches, "{{HEADLINE}}": headline,
        "{{STORY}}": e(plan.get("story", "")), "{{WHY}}": e(plan.get("why_it_works", "")), "{{TABS}}": tabs,
        "{{DATA}}": json.dumps(data), "{{IMGS}}": imgs_js, "{{TOTAL}}": str(len(pieces)),
    }.items():
        page = page.replace(k, v)
    out = os.path.join(out_dir, f"{slug}-plan.html")
    open(out, "w").write(page)
    print(f"Client page: {out} ({os.path.getsize(out) // 1024} KB)")
    return out


TEMPLATE = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Bodoni+Moda:ital,opsz,wght@0,6..96,400..600;1,6..96,400..600&family=Jost:wght@300;400;500&display=swap" rel="stylesheet">
<style>
/* Just Wear This brand, client side ("quiet"): white page, black type and thin rules, the clothes bring the color.
   Fonts: Jost (labels in light wide caps, body), Bodoni Moda (family name and soft italic notes), Anton (the small wordmark). */
:root{
  --paper:#ffffff; --ink:#121212; --soft:#6b6b6b; --line:#e2e2e2; --rule:#121212; --wash:#f4f4f4;
  --sans:"Jost",system-ui,-apple-system,"Segoe UI",sans-serif; --serif:"Bodoni Moda",Didot,"Bodoni 72",Georgia,serif; --mark:"Anton",Impact,"Arial Narrow Bold",sans-serif;
}
*{box-sizing:border-box} [hidden]{display:none!important}
body{color-scheme:light;background:var(--paper);color:var(--ink);font:16px/1.55 var(--sans);-webkit-font-smoothing:antialiased;margin:0}
.wrap{max-width:720px;margin:0 auto;padding-inline:22px;padding-block:18px 64px;display:flex;flex-direction:column;gap:40px}
a{color:inherit}
.caps{font-size:11px;font-weight:300;letter-spacing:.24em;text-transform:uppercase}
.top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--rule);padding-bottom:12px}
.mark{font-family:var(--mark);font-size:17px;letter-spacing:.01em;text-transform:uppercase}
.by{font-size:10px;font-weight:300;letter-spacing:.2em;text-transform:uppercase}
.hero{display:flex;flex-direction:column;gap:10px}
.photo{display:block;width:100%;height:auto;max-height:520px;object-fit:cover;margin-bottom:10px}
h1{font-family:var(--serif);font-weight:500;font-size:clamp(40px,11.5vw,60px);line-height:.98;letter-spacing:-.02em;margin:0;text-wrap:balance}
h1 em{font-style:italic;font-weight:400}
.intro{display:flex;flex-direction:column;font-size:15px;line-height:1.5}
.intro span{white-space:nowrap}
.intro .tap{color:var(--soft)}
.stage{display:flex;flex-direction:column;gap:12px}
.lineup{position:relative;background:#fff}
.spot{position:absolute}
.spot:hover,.spot:focus-visible{background:rgba(0,0,0,.04);outline:none}
.lineup img{display:block;width:100%;height:auto}
.hint{font-size:13px;color:var(--soft)}
h2{font-size:11px;font-weight:300;letter-spacing:.24em;text-transform:uppercase;margin:0}
.colors{display:grid;grid-template-columns:minmax(0,1fr);gap:14px}
.swatches{list-style:none;margin:0;padding:0;display:flex;gap:8px}
.swatches li{display:flex;flex-direction:column;gap:6px;font-size:11px;line-height:1.25;flex:1 1 0;min-width:0;max-width:96px}
.chip{display:block;width:100%;height:46px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.08)}
.headline{display:flex;flex-direction:column;font-family:var(--serif);font-size:24px;line-height:1.2}
.headline span:nth-child(2){font-style:italic}
.story{color:var(--soft);max-width:60ch;margin:0}
.progress{display:flex;flex-direction:column;gap:10px;border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);padding:16px 0}
.ptop{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap}
.pnum{font-family:var(--serif);font-size:30px;font-weight:500;font-variant-numeric:lining-nums tabular-nums}
.pnum small{font-family:var(--sans);font-size:12px;font-weight:300;letter-spacing:.2em;text-transform:uppercase;color:var(--soft)}
.bar{display:flex;gap:3px;height:6px}
.bar i{flex:1;background:var(--line)}
.bar i.ordered{background:#9a9a9a} .bar i.have{background:var(--ink)}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:11px;font-weight:300;letter-spacing:.18em;text-transform:uppercase;color:var(--soft)}
.legend span::before{content:"";display:inline-block;width:14px;height:6px;margin-right:7px;vertical-align:2px;background:var(--line)}
.legend .lo::before{background:#9a9a9a} .legend .lh::before{background:var(--ink)}
.tabs{position:sticky;top:env(safe-area-inset-top,0px);z-index:5;display:flex;gap:22px;overflow-x:auto;padding-block:12px;margin-inline:-22px;padding-inline:22px;background:var(--paper);border-bottom:1px solid var(--line);scrollbar-width:none}
.tabs::-webkit-scrollbar{display:none}
.tab{font:300 12px var(--sans);letter-spacing:.2em;text-transform:uppercase;color:var(--soft);background:none;border:0;border-bottom:1px solid transparent;padding:6px 0;white-space:nowrap;cursor:pointer;min-height:36px}
.tab.on{color:var(--ink);border-bottom-color:var(--ink);font-weight:400}
.tab:focus-visible,.piece:focus-visible,.btn:focus-visible,.seg button:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.person{display:flex;flex-direction:column;gap:4px;scroll-margin-top:70px}
.phead{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;border-bottom:1px solid var(--rule);padding-bottom:10px}
.phead h3{font-size:13px;font-weight:400;letter-spacing:.24em;text-transform:uppercase;margin:0}
.note{font-family:var(--serif);font-style:italic;font-size:18px;line-height:1.1;color:var(--soft)}
.grid{display:flex;flex-direction:column}
.piece{all:unset;cursor:pointer;display:flex;gap:16px;align-items:center;padding:14px 0;border-bottom:1px solid var(--line);min-width:0}
.ph{flex:none;width:76px;height:96px;display:grid;place-items:center;background:#fff}
.ph img{max-width:100%;max-height:100%;object-fit:contain}
.pbody{display:flex;flex-direction:column;gap:3px;min-width:0;flex:1}
.pname{font-size:15px;font-weight:500;line-height:1.3}
.pnote{font-size:14px;line-height:1.4;color:var(--soft)}
.prow{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-top:4px}
.go{font-size:11px;font-weight:400;letter-spacing:.22em;text-transform:uppercase;text-decoration:underline;text-underline-offset:4px}
.status{font-size:10px;font-weight:300;letter-spacing:.2em;text-transform:uppercase;color:var(--soft)}
.status.ordered,.status.have{color:var(--ink);font-weight:400}
.why p{margin:0;max-width:62ch}
.list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;border-top:1px solid var(--rule)}
.list label{display:flex;gap:12px;align-items:flex-start;padding:12px 0;border-bottom:1px solid var(--line);cursor:pointer}
.list input{width:20px;height:20px;margin:2px 0 0;accent-color:var(--ink);flex:none}
.list input:checked+span{color:var(--soft);text-decoration:line-through}
.foot{display:flex;flex-direction:column;gap:4px;border-top:1px solid var(--rule);padding-top:22px}
.foot .sign{font-family:var(--serif);font-style:italic;font-size:30px;line-height:1.1;margin-bottom:6px}
.foot small{color:var(--soft)}
.reclist{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:minmax(0,1fr);border-top:1px solid var(--rule)}
@media (min-width:620px){.reclist{grid-template-columns:repeat(2,minmax(0,1fr));column-gap:28px}}
.rec{display:flex;flex-direction:column;gap:6px;padding:16px 0;border-bottom:1px solid var(--line);min-width:0}
.rkind{font-size:10px;font-weight:300;letter-spacing:.22em;text-transform:uppercase;color:var(--soft)}
.rname{font-size:17px;font-weight:500}
.rnote{margin:0;font-family:var(--serif);font-style:italic;font-size:18px;line-height:1.25}
.rreach{display:flex;gap:8px;align-items:baseline;font-size:14px;text-decoration:none;overflow-wrap:anywhere}
.rreach small{font-size:10px;font-weight:300;letter-spacing:.2em;text-transform:uppercase;color:var(--soft);min-width:76px}
a.rreach{text-decoration:underline;text-decoration-color:var(--line);text-underline-offset:3px}
.rperk{align-self:flex-start;margin-top:4px;font-size:11px;letter-spacing:.16em;text-transform:uppercase;border:1px solid var(--ink);padding:4px 10px}
.ask{margin:4px 0 8px;max-width:52ch}
.who{font-weight:500}
.contact{display:flex;gap:8px;align-items:baseline}
.contact small{font-size:10px;font-weight:300;letter-spacing:.2em;text-transform:uppercase;color:var(--soft);min-width:44px}
/* piece sheet */
.scrim{position:fixed;inset:0;background:rgba(18,18,18,.45);z-index:20;display:flex;align-items:flex-end;justify-content:center}
.sheet{background:var(--paper);width:100%;max-width:560px;padding:14px 22px calc(22px + env(safe-area-inset-bottom,0px));max-height:92%;overflow:auto;display:flex;flex-direction:column;gap:16px}
@media (min-width:700px){.scrim{align-items:center}}
.grab{width:42px;height:3px;background:var(--line);align-self:center}
.sheet>*{flex-shrink:0}
.sheet .big{background:#fff;display:grid;place-items:center;height:min(44vh,360px);overflow:hidden}
.sheet .big img{max-height:calc(min(44vh,360px) * .92);max-width:92%;object-fit:contain}
.sheet h4{font-size:20px;font-weight:500;margin:0;line-height:1.25}
.for{font-size:11px;font-weight:300;letter-spacing:.2em;text-transform:uppercase;color:var(--soft)}
.snote{font-family:var(--serif);font-style:italic;font-size:18px;color:var(--soft);margin:2px 0 0}
.shop{display:flex;flex-direction:column;border-top:1px solid var(--rule)}
.btn{display:flex;justify-content:space-between;align-items:center;gap:10px;text-decoration:none;padding:15px 2px;border-bottom:1px solid var(--line);min-height:48px}
.btn span{font-size:12px;font-weight:400;letter-spacing:.22em;text-transform:uppercase}
.btn small{font-size:14px;color:var(--soft)}
.btn.lead{background:var(--ink);color:#fff;padding-inline:14px;border-bottom-color:var(--ink)}
.btn.lead small{color:#d6d6d6}
.nolink{font-size:13px;color:var(--soft)}
.similar{font-weight:300;text-transform:uppercase;letter-spacing:.16em;font-size:11px;color:var(--soft);margin-bottom:-6px}
.seg{display:grid;grid-template-columns:repeat(3,1fr);border:1px solid var(--ink)}
.seg button{font:300 11px var(--sans);letter-spacing:.16em;text-transform:uppercase;border:0;padding:13px 4px;background:transparent;color:var(--ink);cursor:pointer;min-height:44px}
.seg button+button{border-left:1px solid var(--ink)}
.seg button.on{background:var(--ink);color:#fff;font-weight:400}
.close{all:unset;cursor:pointer;align-self:center;font-size:11px;letter-spacing:.22em;text-transform:uppercase;color:var(--soft);padding:8px 14px}
.owned{font-family:var(--serif);font-style:italic;font-size:22px}
@media (prefers-reduced-motion:no-preference){.sheet{animation:up .22s ease-out}@keyframes up{from{transform:translateY(24px);opacity:.6}}}
</style>

<div class="wrap">
  <header class="top"><span class="mark">Just Wear This.</span><span class="by">{{STUDIO}}</span></header>

  <section class="hero">
    {{PHOTO}}
    <span class="caps">{{WHERE}}</span>
    <h1>{{FAMILY_HTML}}</h1>
    <span class="intro"><span>Here's what everyone's wearing.</span><span class="tap">Tap any piece to shop it.</span></span>
  </section>

  <section class="stage" aria-label="The family together">
    <div class="lineup"><img src="{{LINEUP}}" alt="The family outfit board">{{NAMES}}</div>
    <span class="hint">Tap anyone on the board to see their pieces.</span>
  </section>

  <section class="colors">
    <h2>Your colors</h2>
    <ul class="swatches">{{SWATCHES}}</ul>
    <div class="headline">{{HEADLINE}}</div>
    <p class="story">{{STORY}}</p>
  </section>

  <section class="progress" aria-live="polite">
    <div class="ptop"><span class="pnum" id="pnum">0 <small>of {{TOTAL}} pieces ready</small></span><span class="hint" id="pmsg">Mark each piece as you go.</span></div>
    <div class="bar" id="bar"></div>
    <div class="legend"><span class="lh">Have it</span><span class="lo">Ordered</span><span>Still need</span></div>
  </section>

  <section aria-label="Everyone's pieces">
    <div class="tabs" role="tablist">{{TABS}}</div>
    <div id="people" style="display:flex;flex-direction:column;gap:40px;margin-top:22px"></div>
  </section>

  <section class="why colors">
    <h2>Why it works</h2>
    <p>{{WHY}}</p>
  </section>

  <section class="colors">
    <h2>The week before</h2>
    <ul class="list" id="prep"></ul>
  </section>

  {{RECS}}
  <footer class="foot">
    <span class="sign">Can't wait to see you!</span>
    <p class="ask">Questions about a piece, a size that isn't working, or something you'd like to swap? Reach out to {{STUDIO}} anytime. We'll figure it out together before your session.</p>
    <span class="who">{{STUDIO}}</span>
    {{CONTACT}}
    <small>{{WEBSITE}}</small>
    <small>Links show the look, not always the exact piece.</small>
  </footer>
</div>

<div class="scrim" id="scrim" hidden>
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sname" id="sheet"></div>
</div>

<script>
const D = {{DATA}};
const IMG = {{IMGS}};
const KEY = "jwt-" + D.slug;
let S = {};
try { S = JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch (e) { S = {}; }
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) {} };
const byId = Object.fromEntries(D.pieces.map(p => [p.id, p]));
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const stat = id => byId[id].owned ? "have" : (S[id] || "need");
const LABEL = {need: "Still need", ordered: "Ordered", have: "Have it"};

function render() {
  const wrap = document.getElementById("people");
  wrap.innerHTML = D.people.map((p, k) => `
    <div class="person" id="p-${k}" data-k="${k}">
      <div class="phead"><h3>${esc(p.label)}</h3>${p.note ? `<span class="note">${esc(p.note)}</span>` : ""}</div>
      <div class="grid">${p.items.map(id => { const it = byId[id], st = stat(id); return `
        <button class="piece" type="button" data-id="${id}" aria-label="${esc(it.name)}, ${LABEL[st]}">
          <span class="ph"><img src="${IMG[id]}" alt=""></span>
          <span class="pbody">
            <span class="pname">${esc(it.name)}</span>
            ${it.note ? `<span class="pnote">${esc(it.note)}</span>` : ""}
            <span class="prow"><span class="go">${it.owned ? "See it" : "Shop"} &rarr;</span><span class="status ${st}">${it.owned ? "You have this" : LABEL[st]}</span></span>
          </span>
        </button>`; }).join("")}</div>
    </div>`).join("");
  wrap.querySelectorAll(".piece").forEach(b => b.addEventListener("click", () => openSheet(b.dataset.id)));
  progress();
}

function progress() {
  const ids = D.pieces.map(p => p.id);
  const sts = ids.map(stat);
  const ready = sts.filter(s => s !== "need").length;
  document.getElementById("pnum").innerHTML = `${ready} <small>of ${ids.length} pieces ready</small>`;
  document.getElementById("bar").innerHTML = sts.map(s => `<i class="${s === "need" ? "" : s}"></i>`).join("");
  const left = ids.length - ready;
  document.getElementById("pmsg").textContent = left === 0 ? "Everyone's ready. See you soon!" : left <= 3 ? `Almost there: ${left} to go.` : "Mark each piece as you go.";
}

function openSheet(id) {
  const it = byId[id], st = stat(id);
  const lead = it.links.length ? it.links[Math.min(1, it.links.length - 1)].tier : "";
  const shop = it.owned ? `<span class="owned">You already have this one.</span>` :
    (it.links.length ? `<span class="similar">${it.links.length > 1 ? `Similar picks at ${it.links.length} prices` : "A similar pick"}</span><div class="shop">${it.links.map(l => `<a class="btn ${l.tier === lead ? "lead" : ""}" href="${l.url}" target="_blank" rel="noopener">
        <span>${l.tier}</span><small>${esc(l.store)} &rarr;</small></a>`).join("")}</div>
      <span class="nolink">${it.links.length < 3 ? "Close matches look just as good: the colors and the mix matter more than the exact piece. We only list a pick when it's a close match, so some pieces have fewer options." : "Close matches look just as good: the colors and the mix matter more than the exact piece. Splurge on the favorite, save on the rest."}</span>` : "");
  document.getElementById("sheet").innerHTML = `
    <span class="grab"></span>
    <div class="big"><img src="${IMG[id]}" alt="${esc(it.name)}"></div>
    <div><span class="for">For ${esc(it.for.join(", "))}</span><h4 id="sname">${esc(it.name)}</h4>${it.note ? `<p class="snote">${esc(it.note)}</p>` : ""}</div>
    ${shop}
    ${it.owned ? "" : `<div class="seg" role="group" aria-label="Where this piece stands">
      ${["need", "ordered", "have"].map(s => `<button type="button" data-s="${s}" class="${st === s ? "on" : ""}" aria-pressed="${st === s}">${LABEL[s]}</button>`).join("")}</div>`}
    <button class="close" type="button" id="closeBtn">Done</button>`;
  const scrim = document.getElementById("scrim");
  scrim.hidden = false;
  document.querySelectorAll(".seg button").forEach(b => b.addEventListener("click", () => {
    S[id] = b.dataset.s; save();
    document.querySelectorAll(".seg button").forEach(x => { x.classList.toggle("on", x === b); x.setAttribute("aria-pressed", x === b); });
    render(); filter(current);
  }));
  document.getElementById("closeBtn").addEventListener("click", closeSheet);
  document.getElementById("closeBtn").focus();
}
function closeSheet() { document.getElementById("scrim").hidden = true; }
document.getElementById("scrim").addEventListener("click", e => { if (e.target.id === "scrim") closeSheet(); });
document.addEventListener("keydown", e => { if (e.key === "Escape") closeSheet(); });

let current = "all";
function filter(f) {
  current = f;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.dataset.f === f));
  document.querySelectorAll(".person").forEach(p => p.hidden = !(f === "all" || p.dataset.k === f));
}
document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => filter(t.dataset.f)));
document.querySelectorAll(".spot").forEach(a => a.addEventListener("click", () => filter("all")));

document.getElementById("prep").innerHTML = D.checklist.map((c, i) => `<li><label><input type="checkbox" id="prep-${i}" ${S["prep-" + i] ? "checked" : ""}><span>${esc(c)}</span></label></li>`).join("");
document.querySelectorAll("#prep input").forEach(cb => cb.addEventListener("change", () => { S[cb.id] = cb.checked; save(); }));
render();
</script>
"""

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--out", default="output")
    ap.add_argument("--pdf", action="store_true", help="also write a printable board PDF (only on request)")
    a = ap.parse_args()
    build(a.plan, a.out, pdf=a.pdf)
