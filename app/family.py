"""The family version: a mom answers questions on justwearthis.co, pays (or uses a beta code), and Claude styles her
family's plan with the same rules, library and page engine the photographer plugin uses."""
import base64, datetime as dt, io
import json, os, re, secrets, threading, time, traceback

import httpx

from . import config, links, render, store

# ---------- orders (one JSON file each on the persistent disk) ----------
ORDER_ID = re.compile(r"^[a-f0-9]{16}$")
_lock = threading.Lock()

AGES = ["Adult", "Teen", "Kid", "Toddler", "Baby"]
SHOPS = ["Women's", "Men's", "Girls'", "Boys'", "Either"]
LEVELS = ["Relaxed", "Dressy casual", "Polished", "Formal", "Not sure, you decide"]
PRINTS = ["Love them", "A little is nice", "Solids please"]
SETTINGS = ["Park or field", "Garden", "Beach or lake", "Downtown or city", "Orchard or farm", "Tree farm",
            "At home", "Studio", "Somewhere else"]
OCCASIONS = ["Fall family photos", "Christmas card photos", "Everyday family photos", "Something else"]
TIMES = ["Golden hour", "Daytime", "Indoors", "Not sure"]

# Style picks ("this or that" on /start/ and Edit a person): tag, what she sees, a few words, three example pieces.
WOMEN_LOOKS = [
    ("romantic", "Soft and romantic", "Florals, ruffles, flowy dresses", ["W-DRS-024", "W-DRS-016", "W-DRS-022"]),
    ("classic", "Classic", "Cable knits, wrap dresses, trousers", ["W-TOP-003", "W-DRS-003", "W-BTM-008"]),
    ("modern", "Clean and simple", "Sleek knits, satin, solid colors", ["W-DRS-019", "W-BTM-009", "W-TOP-011"]),
    ("casual", "Cozy and casual", "Jeans, soft sweaters, corduroy", ["W-BTM-001", "W-TOP-016", "W-BTM-006"]),
]
GIRL_LOOKS = [
    ("romantic", "Sweet and twirly", "Smocking, ruffles, tulle", ["G-DRS-003", "G-DRS-010", "G-BTM-005"]),
    ("classic", "Classic", "Collars, tartan, velvet", ["G-DRS-002", "G-DRS-016", "G-DRS-007"]),
    ("casual", "Cozy and casual", "Sweaters, corduroy, easy pieces", ["G-TOP-004", "G-DRS-004", "G-BTM-002"]),
]
SURPRISE = "surprise"
CUTS = ["Dresses or skirts", "Pants or jeans", "Either"]
STYLE_WORDS = {"romantic": "soft and romantic (florals, ruffles, flowy)", "classic": "classic", "modern": "clean and simple",
               "casual": "cozy and casual"}


def looks_for(p):
    """The style choices this person gets, or [] when we don't ask (babies, toddlers, men's and boys' shoppers)."""
    if p.get("age") in ("Baby", "Toddler") or p.get("shop") not in ("Women's", "Girls'"):
        return []
    return GIRL_LOOKS if p.get("age") == "Kid" else WOMEN_LOOKS


def _path(oid):
    return os.path.join(config.ORDERS, oid + ".json")


def get_order(oid):
    if not ORDER_ID.match(oid or ""):
        return None
    return store._read(_path(oid), None)


def save_order(o):
    with _lock:
        o["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        store._write(_path(o["id"]), o)
    return o


def all_orders():
    out = []
    for fn in os.listdir(config.ORDERS):
        if fn.endswith(".json"):
            o = store._read(os.path.join(config.ORDERS, fn), None)
            if o:
                out.append(o)
    return sorted(out, key=lambda o: o.get("created", ""), reverse=True)


def log(o, msg):
    o.setdefault("log", []).append(f"{time.strftime('%m-%d %H:%M')} {msg}")


# ---------- photos of pieces she already owns ----------
PHOTO_ID = re.compile(r"^[a-f0-9]{20}$")
MAX_PHOTOS = 4


class BadPhoto(ValueError):
    pass


def save_photo(data):
    """Stores a phone photo of a piece she owns: turned upright, at most 1600px, re-saved as a plain JPEG (which drops
    the location and camera details). Returns its id."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im).convert("RGB")
    except Exception:
        raise BadPhoto("That file didn't open as a photo. Try a JPG or PNG.")
    if min(im.size) < 120:
        raise BadPhoto("That photo is too small to see the piece. Try a bigger one.")
    im.thumbnail((1600, 1600), Image.LANCZOS)
    pid = secrets.token_hex(10)
    im.save(photo_path(pid), "JPEG", quality=88)
    return pid


def photo_path(pid):
    return os.path.join(config.UPLOADS, pid + ".jpg")


def photo_ok(pid):
    return bool(PHOTO_ID.match(pid or "")) and os.path.exists(photo_path(pid))


def _photo_b64(pid, size=1000):
    from PIL import Image
    im = Image.open(photo_path(pid)).convert("RGB")
    im.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


# ---------- answers ----------
class BadAnswers(ValueError):
    pass


def _s(v, n=300):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def clean_answers(a):
    """Checks and trims what the question page sends. Raises BadAnswers with a message she can act on."""
    if not isinstance(a, dict):
        raise BadAnswers("Something went wrong sending your answers. Please try again.")
    out = {"who": _s(a.get("who"), 60), "email": _s(a.get("email"), 120).lower(), "family": _s(a.get("family"), 60)}
    if not out["who"]:
        raise BadAnswers("Add your first name.")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", out["email"]):
        raise BadAnswers("That email doesn't look right. Your plan link goes there.")
    people = []
    for p in (a.get("people") or [])[:8]:
        name = _s(p.get("name"), 40)
        age = p.get("age") if p.get("age") in AGES else ""
        if not name and not age:
            continue
        if not name or not age:
            raise BadAnswers("Every person needs a name and an age.")
        kid = re.sub(r"\D", "", str(p.get("kidAge") or ""))[:2]
        q = {"name": name, "age": age, "kidAge": kid, "shop": p.get("shop") if p.get("shop") in SHOPS else "Either",
             "dress": "Basics only" if p.get("dress") == "Basics only" else "Happy to", "nope": _s(p.get("nope"), 160)}
        offered = [t for t, *_ in looks_for(q)]
        if offered:
            picked = p.get("looks") if isinstance(p.get("looks"), list) else []
            looks = [t for t in offered if t in picked][:2]  # kept in a fixed order, so an edit only counts real changes
            q["looks"] = looks or [SURPRISE]
            q["cut"] = p.get("cut") if p.get("cut") in CUTS and age != "Kid" else "Either"  # no girls' pants in the library yet
        people.append(q)
    if not people:
        raise BadAnswers("Add at least one person.")
    out["people"] = people
    d = _s(a.get("date"), 10)
    try:
        dt.date.fromisoformat(d)
    except ValueError:
        raise BadAnswers("Add your photo date (a guess is fine).")
    out["date"] = d
    out["setting"] = a.get("setting") if a.get("setting") in SETTINGS else "Somewhere else"
    out["setting_note"] = _s(a.get("setting_note"), 120)
    out["occasion"] = a.get("occasion") if a.get("occasion") in OCCASIONS else "Everyday family photos"
    out["time"] = a.get("time") if a.get("time") in TIMES else "Not sure"
    out["level"] = a.get("level") if a.get("level") in LEVELS else "Not sure, you decide"
    out["prints"] = a.get("prints") if a.get("prints") in PRINTS else "A little is nice"
    for k, n in (("love", 120), ("never", 120), ("own", 500), ("extra", 600)):
        out[k] = _s(a.get(k), n)
    names = {p["name"].lower(): p["name"] for p in people}
    photos = []
    for ph in (a.get("photos") or [])[:MAX_PHOTOS]:
        if not isinstance(ph, dict) or not photo_ok(ph.get("id")):
            continue  # an upload that never finished: skip it rather than stop her
        who = names.get(_s(ph.get("person"), 40).lower())
        if not who:
            raise BadAnswers("Pick who's wearing each piece in your photos.")
        photos.append({"id": ph["id"], "person": who, "what": _s(ph.get("what"), 120)})
    out["photos"] = photos
    return out


def person_changes(old, new):
    """Plain sentences for what changed between two sets of answers' people (same people, same order)."""
    out = []
    labels = {"name": "name", "age": "age", "kidAge": "age in years", "shop": "shops from", "dress": "dressing up", "nope": "won't wear",
              "looks": "style", "cut": "dresses or pants"}
    show = lambda v: style_words(v) if isinstance(v, list) else (v or "-")
    blank = {"looks": [SURPRISE], "cut": "Either"}  # older orders have no style picks: same as "you choose"
    val = lambda p, k: p.get(k) or blank.get(k) or ""
    for p, q in zip(old["people"], new["people"]):
        diffs = [f"{label} was \"{show(val(p, k))}\", now \"{show(val(q, k))}\"" for k, label in labels.items() if val(p, k) != val(q, k)]
        if diffs:
            out.append(f"{q['name']}: " + "; ".join(diffs) + ".")
    return out


def style_words(looks):
    looks = [l for l in looks or [] if l != SURPRISE]
    return " + ".join(STYLE_WORDS.get(l, l) for l in looks) if looks else "no style picked (you choose)"


def family_label(a):
    return f"The {a['family']} family" if a.get("family") else f"{a['who']}'s family"


def answers_text(a):
    def person(p):
        age = f"Kid, {p['kidAge']}" if p["age"] == "Kid" and p["kidAge"] else p["age"]
        bits = [age, f"shops {p['shop']}"]
        if p["age"] not in ("Baby", "Toddler"):
            bits.append("basics only, won't dress up" if p["dress"] == "Basics only" else "happy to dress up")
        if p.get("looks"):
            bits.append("style: " + style_words(p["looks"]))
            if p.get("cut") in ("Dresses or skirts", "Pants or jeans"):
                bits.append("wants " + p["cut"].lower())
        return f"- {p['name']}: {', '.join(bits)}" + (f". Won't wear: {p['nope']}" if p["nope"] else "")
    d = dt.date.fromisoformat(a["date"])
    return "\n".join([
        f"Family: {family_label(a)} (answered by {a['who']})",
        f"Photo date: {d.strftime('%B %-d, %Y')}",
        f"Occasion: {a['occasion']}",
        f"Setting: {a['setting']}{(' (' + a['setting_note'] + ')') if a['setting_note'] else ''}; light: {a['time']}",
        "1. Everyone in the photos:", *[person(p) for p in a["people"]],
        f"2. How dressy: {a['level']}",
        f"3. Colors they love: {a['love'] or 'no preference'}. Never: {a['never'] or 'none'}",
        f"4. Prints: {a['prints']}",
        f"5. Already own and want to wear: {a['own'] or ('nothing else' if a.get('photos') else 'nothing')}",
        *[f"   Photo {n} (photo id {ph['id']}): {ph['person']}'s own {ph['what'] or 'piece (see the photo)'}"
          for n, ph in enumerate(a.get("photos") or [], 1)],
        f"6. Anything else: {a['extra'] or 'nothing'}",
    ])


# ---------- library ----------
_cat = None


def catalog():
    global _cat
    if _cat is None:
        _cat = json.load(open(config.CATALOG))
    return _cat


def persons_for(p):
    age, shop = p["age"], p["shop"]
    fem, male = shop in ("Women's", "Girls'"), shop in ("Men's", "Boys'")
    either = not fem and not male
    if age == "Adult":
        return {"women"} if fem else {"men"} if male else {"women", "men"}
    if age == "Teen":
        return {"teen girls"} if fem else {"teen boys"} if male else {"teen girls", "teen boys"}
    if age == "Kid":
        return ({"girls"} if fem else {"boys"} if male else {"girls", "boys"}) | {"kids"}
    if age == "Toddler":
        return {"toddlers", "kids"}
    return {"babies"}


def _fits(item, wanted):
    return item["person"] in wanted or bool(wanted & set(item.get("also_for", [])))


def candidates(a):
    """Library pieces any person in this family could wear, from stocked stories, with at least one shop link."""
    cat = catalog()
    stocked = {k for k, v in cat["color_stories"].items() if v.get("stocked")}
    wanted = set().union(*(persons_for(p) for p in a["people"]))
    h, b = links.health(), links.browser_checks()
    out = []
    for i in cat["items"]:
        if i.get("link_tier") == "0 links" or not (set(i.get("color_stories", [])) & stocked):
            continue
        if not links.has_live_link(i, h, b):  # every shop link known dead: leave it out until it's fixed
            continue
        if _fits(i, wanted):
            out.append(i)
    return out


def _line(i):
    bits = [i["id"], f"{i['person']}{' (also ' + ', '.join(i['also_for']) + ')' if i.get('also_for') else ''}",
            f"{i['category']}/{i['layout_role']}", i["name"], i["hex"],
            ("print: " + (i.get("pattern_family") or "yes") + (f" {i['pattern_scale']}" if i.get("pattern_scale") else "")) if i.get("pattern") else "solid",
            "stories: " + ",".join(i.get("color_stories", []))]
    for k in ("texture", "formality", "style", "baby_for", "toddler_for"):
        if i.get(k):
            bits.append(f"{k}: {i[k] if isinstance(i[k], str) else ','.join(i[k])}")
    if i.get("season"):
        bits.append("season: " + ",".join(i["season"]))
    if i.get("statement"):
        bits.append("statement piece")
    if i.get("never_with"):
        bits.append("never with: " + ",".join(i["never_with"]))
    return " | ".join(bits)


# ---------- the stylist (Claude) ----------
def _read_engine(rel):
    return open(os.path.join(config.ENGINE, rel)).read()


def _skill_sections():
    s = _read_engine("SKILL.md")
    m = re.search(r"## Plan format.*?(?=## Privacy)", s, re.S)
    return m.group(0) if m else ""


def system_prompt():
    stories = {k: {"name": v["name"], "season": v.get("season"), "settings": v.get("settings"), "summary": v.get("summary"),
                   "palette": [p["name"] for p in v.get("palette", [])]}
               for k, v in catalog()["color_stories"].items() if v.get("stocked")}
    q = _read_engine("references/questionnaire.md")
    mapping = re.search(r"## How answers map to the plan.*?(?=## Gift path)", q, re.S)
    return f"""You are the stylist behind Just Wear This. A mom has answered questions about her family's upcoming photos. You decide what everyone wears, using only the library pieces listed in her message, and return one confident plan as JSON. There is no photographer in this flow: you make every call yourself and never ask questions.

Follow every styling rule below. They are the product.

{_read_engine("references/styling-rules.md")}

{mapping.group(0) if mapping else ""}

Stocked color stories (use only these keys for color_story):
{json.dumps(stories, indent=1)}

{_skill_sections()}

Rules for this flow:
- Only use item ids from the list in the message. Each person's pieces must be listed for that kind of person (women, men, girls, boys, teen girls, teen boys, toddlers, babies, kids, or "also" that person).
- Labels: the first names exactly as she gave them (or Mom, Dad). Order: adults first, then kids oldest to youngest.
- If she owns something that matches a library piece closely, use that piece and list it in "owned" with a label naming her real piece; otherwise ignore the owned note.
- Photos of pieces she owns: each photo comes with its photo id and who wears it. Put every photographed piece in that person's outfit and build the rest of the family around it (it usually sets the colors). In that person's items use the closest library piece of the same kind and color as a stand-in, and add an "owned" entry: {{"id": "<that library id>", "label": "<her real piece in a few words, for example Ava's own brown boots>", "photo": "<photo id>", "crop": [left, top, right, bottom]}}. The crop is fractions of the photo (0 to 1), framed tightly on the piece; always leave out faces and people. Use a photo's id only once. If a photo doesn't show a piece of clothing, shoes or an accessory, leave it out.
- dress_level: if she said "Not sure", choose from the setting (usually Dressy casual). If she said Formal, use the dressiest Polished pieces and print Polished.
- title_right: a short line about the setting (for example "A park at golden hour"). subtitle_right: "<Season> | Family photos" or "Holiday | Christmas card photos".
- Leave out palette and settings_override.
- Client-facing copy speaks to her family warmly. Never mention AI, Claude, the library or the catalog.
- Headline: three short lines in plain mom language, specific to this family's colors, setting and pieces. Don't open with "One ___ anchor" and don't use styling jargon like "anchor", "palette" or "tonal".
- Talk about the clothes, never bodies: no "bump", "figure", "flattering", "slimming" or "hides". Say what the piece is ("a roomy wrap dress", "soft and stretchy"), not what it does for a body.
- "Won't wear" is a hard rule. No short sleeves means long sleeves on the piece itself (a cardigan over a short-sleeve dress doesn't count). No heels means flat shoes or boots with a flat or block heel under 1 inch.
- Style picks: some people come with the style they actually wear (soft and romantic, classic, clean and simple, cozy and casual) and sometimes "wants dresses or skirts" or "wants pants or jeans". These outrank the general guidance in the styling rules about what women and girls usually wear ("midi and maxi dresses with movement", "smocked or tiered dresses"). Every dress, top, bottom and layer you give that person must carry one of their picked styles in its "style" tag, and "wants pants or jeans" means pants or jeans with a top, never a dress or skirt. Pick the color story that has pieces in her style. Mom can still be the standout through a rich color or one special piece in her own style; it doesn't have to be a flowing dress.
- When a person has no style picked, lean classic. Keep ruffles, smocking, tiers and prairie-style florals to one person on the board at most, unless she picked soft and romantic.
- Reply with only the plan JSON: start your reply with {{ and end it with }}. No other text, no code fences, no questions."""


def recently_used(limit=40, min_uses=2):
    """Pieces that show up a lot in recent plans, so families don't all get the same favorites."""
    from collections import Counter
    c = Counter()
    for o in all_orders()[:limit]:
        for p in (o.get("plan") or {}).get("people", []):
            c.update(p.get("items", []))
    return [iid for iid, n in c.most_common() if n >= min_uses]


def user_content(a, text):
    """The message as Claude reads it: her photos first (each named by its id), then the words."""
    blocks = []
    for n, ph in enumerate(a.get("photos") or [], 1):
        if photo_ok(ph["id"]):
            blocks += [{"type": "text", "text": f"Photo {n}, photo id {ph['id']}: {ph['person']}'s own {ph['what'] or 'piece'}"},
                       {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": _photo_b64(ph["id"])}}]
    return blocks + [{"type": "text", "text": text}] if blocks else text


def user_prompt(a, items, fix=None, avoid=None):
    import random
    items = list(items)
    random.shuffle(items)  # list order shouldn't decide the plan
    msg = f"Her answers:\n{answers_text(a)}\n\nLibrary pieces you may use ({len(items)}):\n" + "\n".join(_line(i) for i in items)
    if avoid:
        msg += ("\n\nVariety: these pieces were used in several recent family plans. When another piece works just as well "
                "for this family, choose it instead (use one of these only when it is clearly the best fit): " + ", ".join(avoid[:40]))
    if fix:
        msg += "\n\n" + fix
    return msg


class StylistError(Exception):
    pass


_prefill = {"ok": False}  # this model doesn't accept a prefilled reply
_claude_slots = threading.Semaphore(int(os.environ.get("CLAUDE_CONCURRENCY", "2")))  # stay under the API's rate limits


def call_claude(system, messages):
    key = config.ANTHROPIC_API_KEY
    if not key:
        raise StylistError("ANTHROPIC_API_KEY isn't set on the server.")
    last = ""
    budget = 16000
    for attempt in range(6):
        with _claude_slots:
            try:
                r = httpx.post("https://api.anthropic.com/v1/messages", timeout=240, headers={
                    "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": config.ANTHROPIC_MODEL, "max_tokens": budget, "system": system,
                          "messages": messages + ([{"role": "assistant", "content": "{"}] if _prefill["ok"] else [])})
            except httpx.HTTPError as e:
                r, last = None, f"network: {e}"
        if r is not None and r.status_code == 200:
            data = r.json()
            text = ("{" if _prefill["ok"] else "") + "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
            usage = dict(data.get("usage", {}), stop=data.get("stop_reason"))
            if not text.strip():
                # big families can use the whole budget before writing any plan; give it more room and ask again
                last = f"Claude sent back no plan (stop: {data.get('stop_reason')})"
                print(f"[claude empty] stop={data.get('stop_reason')} usage={data.get('usage')}")
                budget = min(32000, budget * 2)
                continue
            return text, usage
        if r is not None:
            last = f"Claude API {r.status_code}: {r.text[:300]}"
            if r.status_code == 400 and "prefill" in r.text.lower():
                _prefill["ok"] = False
                continue
            if r.status_code not in (429, 500, 502, 503, 504, 529):
                break
            wait = float(r.headers.get("retry-after") or 0) or min(60, 5 * 2 ** attempt)
        else:
            wait = min(60, 5 * 2 ** attempt)
        time.sleep(wait)
    raise StylistError(last)


def parse_plan(text):
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    else:
        t = t[t.find("{"): t.rfind("}") + 1]
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise StylistError(f"The plan wasn't valid JSON ({e}); it began: {text.strip()[:120]!r}")


PANTS = re.compile(r"\b(pants|trousers|jeans|leggings|chinos)\b", re.I)


def style_probs(plan, a, items):
    """Pieces that don't match a person's style picks (soft: on the last try the plan is built anyway)."""
    byid = {i["id"]: i for i in items}
    probs = []
    for idx, pp in enumerate(plan.get("people") or []):
        src = a["people"][idx] if idx < len(a["people"]) else None
        if not src:
            continue
        looks = {l for l in src.get("looks") or [] if l != SURPRISE}
        its = [byid[i] for i in pp.get("items") or [] if i in byid]
        if looks:
            for i in its:
                if i["category"] in ("dress", "top", "bottom", "outerwear") and i.get("style") and not looks & set(i["style"]):
                    probs.append(f"{pp.get('label')}'s style is {style_words(list(looks))}, but {i['id']} ({i['name']}) is {', '.join(i['style'])}. "
                                 "Pick a piece tagged with her style.")
        cut = src.get("cut")
        if cut == "Pants or jeans":
            for i in its:
                if i["category"] == "dress" or (i["category"] == "bottom" and not PANTS.search(i["name"])):
                    probs.append(f"{pp.get('label')} wants pants or jeans, but {i['id']} ({i['name']}) isn't. Use pants or jeans with a top.")
        elif cut == "Dresses or skirts":
            for i in its:
                if i["category"] == "bottom" and PANTS.search(i["name"]):
                    probs.append(f"{pp.get('label')} wants a dress or skirt, but {i['id']} ({i['name']}) is pants.")
    return probs


def check_plan(plan, a, items):
    """Problems the stylist must fix before the page is built (the engine adds its own CHECK lines)."""
    byid = {i["id"]: i for i in items}
    probs = []
    stocked = {k for k, v in catalog()["color_stories"].items() if v.get("stocked")}
    if plan.get("color_story") not in stocked:
        probs.append(f"color_story must be one of {sorted(stocked)}.")
    people = plan.get("people") or []
    if len(people) != len(a["people"]):
        probs.append(f"The family has {len(a['people'])} people; the plan has {len(people)}.")
    used = {}
    for idx, pp in enumerate(people):
        its = pp.get("items") or []
        if not 2 <= len(its) <= 5:
            probs.append(f"{pp.get('label')}: 2 to 5 pieces, not {len(its)}.")
        src = a["people"][idx] if idx < len(a["people"]) else None
        for iid in its:
            if iid not in byid:
                probs.append(f"{pp.get('label')}: {iid} isn't in the list of pieces you may use.")
            elif src and not _fits(byid[iid], persons_for(src)):
                probs.append(f"{pp.get('label')}: {iid} ({byid[iid]['name']}) is made for {byid[iid]['person']}, not this person.")
            if iid in used:
                probs.append(f"{iid} is used for both {used[iid]} and {pp.get('label')}; nobody shares a piece.")
            used[iid] = pp.get("label")
        note = pp.get("note") or {}
        if note.get("points_to") and note["points_to"] not in its:
            probs.append(f"{pp.get('label')}: the note points to {note['points_to']}, which they aren't wearing.")
    for idx, pp in enumerate(people):
        src = a["people"][idx] if idx < len(a["people"]) else None
        if src and src.get("nope"):
            for iid in pp.get("items") or []:
                if iid in byid:
                    hit = nope_hit(src["nope"], byid[iid])
                    if hit:
                        probs.append(f"{pp.get('label')} won't wear {hit}, but {iid} ({byid[iid]['name']}) is one. Pick another piece.")
    probs += photo_probs(plan, a)
    probs += style_probs(plan, a, items)
    copy = json.dumps([plan.get(k) for k in ("headline", "story", "why_it_works", "piece_notes")]).lower()
    for w in COPY_BANNED:
        if re.search(rf"\b{w}\b", copy):
            probs.append(f'Client copy uses "{w}". Talk about the clothes in plain words instead.')
    for k in ("family_name", "headline", "story", "why_it_works", "prep_checklist", "piece_notes"):
        if not plan.get(k):
            probs.append(f"{k} is missing.")
    return probs


def photo_probs(plan, a):
    """Her photographed pieces: each on the right person, cropped sensibly, used once."""
    probs = []
    mine = {ph["id"]: ph for ph in a.get("photos") or []}
    worn = {pp.get("label"): set(pp.get("items") or []) for pp in plan.get("people") or []}
    seen = set()
    for o in plan.get("owned") or []:
        if not isinstance(o, dict) or not o.get("photo"):
            continue
        pid = o["photo"]
        if pid not in mine:
            probs.append(f'owned: "{pid}" is not one of her photo ids.')
            continue
        if pid in seen:
            probs.append(f"owned: photo {pid} is used twice.")
        seen.add(pid)
        if o.get("id") not in worn.get(mine[pid]["person"], set()):
            probs.append(f"owned: photo {pid} is {mine[pid]['person']}'s piece, so its stand-in {o.get('id')} must be in {mine[pid]['person']}'s items.")
        c = o.get("crop")
        if c is not None and not (isinstance(c, list) and len(c) == 4 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in c)
                                  and c[0] < c[2] and c[1] < c[3]):
            probs.append(f"owned: the crop for photo {pid} must be [left, top, right, bottom], fractions from 0 to 1.")
    missing = [pid for pid in mine if pid not in seen]
    if missing:
        probs.append("Her photographed pieces must be in the plan (photo ids " + ", ".join(missing) + "): add each one to its person's outfit with an owned entry. "
                     "Only leave a photo out if it doesn't show clothing, shoes or an accessory.")
    return probs


def plan_photos(plan, a):
    """photo id -> file on the disk, for the photos this plan uses."""
    mine = {ph["id"] for ph in a.get("photos") or []}
    return {o["photo"]: photo_path(o["photo"]) for o in plan.get("owned") or []
            if isinstance(o, dict) and o.get("photo") in mine and photo_ok(o["photo"])}


COPY_BANNED = ["anchor", "anchors", "bump", "figure", "flattering", "slimming", "hides", "curves", "tummy"]

# "won't wear" words -> what to look for in a piece's name/tags
NOPE_RULES = [
    (r"short[- ]?sleeve|sleeveless|bare arms", r"short[- ]sleeve|puff[- ]sleeve|flutter|cap[- ]sleeve|sleeveless|tank|\btee\b|t-shirt|polo"),
    (r"short (hem|skirt|dress)|short hems|mini", r"\bmini\b|shorts?\b|skort"),
    (r"heel", r"heel|stiletto|pump\b"),
    (r"dress(es)?\b", r"\bdress\b|jumper dress|romper"),
    (r"skirt", r"skirt"),
    (r"collar", r"collar|button[- ]down|button[- ]up|oxford|(?<!sweat)shirt\b|polo"),
    (r"\bbows?\b", r"\bbows?\b"),
    (r"\bties?\b|neckties?", r"\bties?\b|bow tie"),
    (r"sport ?coats?|blazers?|suit jackets?", r"sport coat|blazer|suit jacket"),
    (r"sequin|sparkle|glitter", r"sequin|sparkle|glitter|metallic"),
    (r"turtleneck", r"turtleneck"),
    (r"jeans|denim", r"jeans|denim|chambray"),
    (r"velvet", r"velvet"),
    (r"tights", r"tights"),
    (r"scratchy|wool|itchy", r"\bwool\b|tweed|mohair|fisherman"),
]


def nope_hit(nope, item):
    n = nope.lower()
    text = " ".join([item.get("name", ""), item.get("category", ""), item.get("cat", ""), " ".join(item.get("tags", []) if isinstance(item.get("tags"), list) else [])]).lower()
    for said, look in NOPE_RULES:
        if re.search(said, n) and re.search(look, text):
            # a dress-style rule shouldn't trip on "dress shoes"/"dress pants"
            if look.startswith(r"\bdress") and re.search(r"dress (shoe|pant|boot|shirt)", text):
                continue
            return re.search(said, n).group(0)
    return None


def fake_plan(a, items):
    """A rough plan with no API call, so the whole flow can be tested before the key is in. Never shown to customers."""
    story = "holiday-plaid" if a["occasion"].startswith("Christmas") else "harvest"
    people = []
    taken = set()
    for p in a["people"]:
        mine = [i for i in items if _fits(i, persons_for(p)) and story in i["color_stories"] and i["id"] not in taken]
        pick = []
        for roles in (("hero",), ("bottom", "layer"), ("shoes",)):
            for i in mine:
                if i["layout_role"] in roles and i not in pick:
                    if roles == ("hero",) or not any(x["category"] == i["category"] for x in pick):
                        pick.append(i)
                        break
        if len(pick) < 2:
            pick = mine[:2]
        taken |= {i["id"] for i in pick}
        people.append({"label": p["name"], "items": [i["id"] for i in pick],
                       "note": {"text": "test\nnote", "points_to": pick[0]["id"]}})
    return {"family_name": family_label(a).replace("'s family", "'s Family").replace(" family", " Family"),
            "title_right": a["setting"], "subtitle_right": "Fall | Family photos", "dress_level": "Dressy casual",
            "color_story": story, "people": people, "owned": [], "headline": ["Test plan.", "Not styled.", "Pipeline only."],
            "story": "A test plan.", "why_it_works": "Test.", "prep_checklist": ["Test."],
            "piece_notes": {iid: "Test note." for pp in people for iid in pp["items"]}}


FAMILY_BUSINESS = {"studio_name": "Just Wear This", "website": "justwearthis.co"}


def stylist(a, fix_note=None, base_plan=None, extra=None, exclude=()):
    """Returns (plan, html, title, notes). Asks Claude, checks the plan, builds the page; one or two rounds of fixes.
    exclude: pieces she already swapped away, so a swap never brings them back."""
    items = [i for i in candidates(a) if i["id"] not in set(exclude)]
    system = system_prompt()
    if config.ANTHROPIC_API_KEY == "fake":
        plan = fake_plan(a, items)
        if base_plan:
            plan["owned"] = base_plan.get("owned") or []
        html, title, checks = render.build_plan_page(dict(plan, **(extra or {})), FAMILY_BUSINESS, plan_photos(plan, a))
        return plan, html, title, checks + ["fake plan (test mode)"]
    first = user_prompt(a, items, fix_note, avoid=None if base_plan else recently_used())
    if base_plan:
        first += "\n\nHer current plan (change only what she asked for, keep everything else the same):\n" + json.dumps(base_plan)
    messages = [{"role": "user", "content": user_content(a, first)}]
    usage = []
    for attempt in range(3):
        text, u = call_claude(system, messages)
        usage.append(u)
        try:
            plan = parse_plan(text)
            probs = check_plan(plan, a, items)
            soft = set(photo_probs(plan, a)) | set(style_probs(plan, a, items))
            if attempt == 2 and probs and all(p in soft for p in probs):
                print(f"[photos/style] building without a clean match: {probs}")
                plan["owned"] = [o for o in plan.get("owned") or [] if not isinstance(o, dict) or not o.get("photo")
                                 or o["photo"] in {ph["id"] for ph in a.get("photos") or []}]
                probs = []
            if not probs:
                plan.pop("settings_override", None)
                html, title, checks = render.build_plan_page(dict(plan, **(extra or {})), FAMILY_BUSINESS, plan_photos(plan, a))
                probs = [c for c in checks if c.startswith("CHECK")]
                if not probs or attempt == 2:
                    return plan, html, title, checks + [f"usage: {usage}"]
        except (StylistError, render.BuildError) as e:
            probs = [str(e)]
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Fix these and send the whole plan JSON again:\n- " + "\n- ".join(probs)}]
    raise StylistError("Couldn't make a clean plan after three tries: " + "; ".join(probs))


# ---------- the build job ----------
def _swap_block(oid):
    """A clear 'swap a piece' section, right after Why it works and before the week-before list."""
    swap = f"{config.PUBLIC_BASE}/o/{oid}/swap"
    return (f'<section class="colors"><h2>Change your mind?</h2>'
            f'<p class="story">Swap any piece, as many times as you like until photo day. Your link stays the same.</p>'
            f'<a class="btn lead" href="{swap}"><span>Swap a piece</span><small>Free until photo day &rarr;</small></a>'
            f'<p class="story">Need to fix someone\'s details, like their age or where they shop? <a href="{config.PUBLIC_BASE}/o/{oid}/edit">Edit a person</a>.</p>'
            f'<p class="story">Want different colors? <a href="{config.PUBLIC_BASE}/o/{oid}/colors">Change our colors</a>, free until photo day.</p></section>\n  ')


def _family_voice(html, oid):
    """The page template speaks as a photographer; the family version speaks as Just Wear This."""
    swap = f"{config.PUBLIC_BASE}/o/{oid}/swap"
    html = html.replace("<span class=\"by\">Just Wear This</span>", "<span class=\"by\">Family outfit plan</span>", 1)
    html = html.replace("<span class=\"sign\">Can't wait to see you!</span>", "<span class=\"sign\">Have fun at your photos!</span>", 1)
    contact = f" or email <a href=\"mailto:{config.SUPPORT_EMAIL}\">{config.SUPPORT_EMAIL}</a>" if config.SUPPORT_EMAIL else ""
    html = html.replace(
        "Questions about a piece, a size that isn't working, or something you'd like to swap? Reach out to Just Wear This anytime. We'll figure it out together before your session.",
        f"Something not working, or a piece sold out? <a href=\"{swap}\">Swap it here</a>{contact}. We'll sort it out before photo day.", 1)
    return html


def _with_bar(html, oid, a):
    html = _family_voice(html, oid)
    m = re.search(r'<section class="colors">\s*<h2>The week before</h2>', html)
    if m:
        return html[:m.start()] + _swap_block(oid) + html[m.start():]
    return html.replace("</body>", _swap_block(oid) + "</body>", 1)


def build(oid, request_note=None):
    o = get_order(oid)
    if not o:
        return
    o["status"] = "building"
    log(o, "building" + (f" (swap: {request_note})" if request_note else ""))
    save_order(o)
    try:
        plan, html, title, notes = stylist(o["answers"], request_note, o.get("plan") if request_note else None,
                                           extra={"swap_url": f"{config.PUBLIC_BASE}/o/{oid}/swap"}, exclude=o.get("swapped_out") or ())
        pid = store.save_page("family", _with_bar(html, oid, o["answers"]), title, "plan", o.get("page_id"))
        o.update(status="ready", page_id=pid, plan=plan, url=f"{config.PUBLIC_BASE}/p/{pid}", swap_pending=False, error="")
        log(o, "ready " + "; ".join(n for n in notes if not n.startswith("usage"))[:300])
        o.setdefault("usage", []).append(next((n for n in notes if n.startswith("usage")), ""))
        first = not o.get("emailed")
        save_order(o)
        from . import mailer
        if first:
            mailer.plan_ready(o)
            o["emailed"] = True
        elif request_note:
            mailer.plan_updated(o)
        save_order(o)
    except Exception as e:
        o = get_order(oid)
        o["status"] = "failed" if not o.get("page_id") else "ready"
        o["error"] = str(e)[:500]
        o["swap_pending"] = False
        log(o, "FAILED " + str(e)[:300])
        traceback.print_exc()
        save_order(o)
        from . import mailer
        mailer.alert_emily(o)


def build_async(oid, request_note=None):
    threading.Thread(target=build, args=(oid, request_note), daemon=True).start()


def new_order(answers, method):
    oid = secrets.token_hex(8)
    o = {"id": oid, "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "answers": answers, "email": answers["email"],
         "status": "awaiting_payment", "payment": {"method": method}, "swaps": 0}
    log(o, f"order started ({method})")
    return save_order(o)


def can_swap(o):
    try:
        return dt.date.today() <= dt.date.fromisoformat(o["answers"]["date"])
    except Exception:
        return True


def resume_unfinished():
    """After a restart (a deploy), finish any plan that was mid-build so no family is left waiting."""
    n = 0
    for o in all_orders()[:300]:
        if o.get("status") in ("paid", "building"):
            note = None
            if o.get("swap_pending") and o.get("plan"):
                last = next((l for l in reversed(o.get("log", [])) if "swap requested" in l), "")
                note = "She asked for a swap: " + last.split("swap requested:", 1)[-1].strip() if last else None
            log(o, "resuming after a restart")
            save_order(o)
            build_async(o["id"], note)
            n += 1
    return n
