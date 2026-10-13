"""The family version: a mom answers questions on justwearthis.co, pays (or uses a beta code), and Claude styles her
family's plan with the same rules, library and page engine the photographer plugin uses."""
import datetime as dt
import json, os, re, secrets, threading, time, traceback

import httpx

from . import config, render, store

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
        people.append({"name": name, "age": age, "kidAge": kid, "shop": p.get("shop") if p.get("shop") in SHOPS else "Either",
                       "dress": "Basics only" if p.get("dress") == "Basics only" else "Happy to", "nope": _s(p.get("nope"), 160)})
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
    return out


def family_label(a):
    return f"The {a['family']} family" if a.get("family") else f"{a['who']}'s family"


def answers_text(a):
    def person(p):
        age = f"Kid, {p['kidAge']}" if p["age"] == "Kid" and p["kidAge"] else p["age"]
        bits = [age, f"shops {p['shop']}"]
        if p["age"] not in ("Baby", "Toddler"):
            bits.append("basics only, won't dress up" if p["dress"] == "Basics only" else "happy to dress up")
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
        f"5. Already own and want to wear: {a['own'] or 'nothing'}",
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
    out = []
    for i in cat["items"]:
        if i.get("link_tier") == "0 links" or not (set(i.get("color_stories", [])) & stocked):
            continue
        if _fits(i, wanted):
            out.append(i)
    return out


def _line(i):
    bits = [i["id"], f"{i['person']}{' (also ' + ', '.join(i['also_for']) + ')' if i.get('also_for') else ''}",
            f"{i['category']}/{i['layout_role']}", i["name"], i["hex"],
            ("print: " + (i.get("pattern_family") or "yes") + (f" {i['pattern_scale']}" if i.get("pattern_scale") else "")) if i.get("pattern") else "solid",
            "stories: " + ",".join(i.get("color_stories", []))]
    for k in ("texture", "formality", "baby_for", "toddler_for"):
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
- dress_level: if she said "Not sure", choose from the setting (usually Dressy casual). If she said Formal, use the dressiest Polished pieces and print Polished.
- title_right: a short line about the setting (for example "A park at golden hour"). subtitle_right: "<Season> | Family photos" or "Holiday | Christmas card photos".
- Leave out palette and settings_override.
- Client-facing copy speaks to her family warmly. Never mention AI, Claude, the library or the catalog.
- Reply with only the plan JSON, no other text."""


def user_prompt(a, items, fix=None):
    msg = f"Her answers:\n{answers_text(a)}\n\nLibrary pieces you may use ({len(items)}):\n" + "\n".join(_line(i) for i in items)
    if fix:
        msg += "\n\n" + fix
    return msg


class StylistError(Exception):
    pass


def call_claude(system, messages):
    key = config.ANTHROPIC_API_KEY
    if not key:
        raise StylistError("ANTHROPIC_API_KEY isn't set on the server.")
    r = httpx.post("https://api.anthropic.com/v1/messages", timeout=240, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": config.ANTHROPIC_MODEL, "max_tokens": 6000, "system": system, "messages": messages})
    if r.status_code != 200:
        raise StylistError(f"Claude API {r.status_code}: {r.text[:300]}")
    data = r.json()
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"), data.get("usage", {})


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
        raise StylistError(f"The plan wasn't valid JSON ({e}).")


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
    for k in ("family_name", "headline", "story", "why_it_works", "prep_checklist", "piece_notes"):
        if not plan.get(k):
            probs.append(f"{k} is missing.")
    return probs


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


def stylist(a, fix_note=None, base_plan=None):
    """Returns (plan, html, title, notes). Asks Claude, checks the plan, builds the page; one or two rounds of fixes."""
    items = candidates(a)
    system = system_prompt()
    if config.ANTHROPIC_API_KEY == "fake":
        plan = fake_plan(a, items)
        html, title, checks = render.build_plan_page(plan, FAMILY_BUSINESS)
        return plan, html, title, checks + ["fake plan (test mode)"]
    first = user_prompt(a, items, fix_note)
    if base_plan:
        first += "\n\nHer current plan (change only what she asked for, keep everything else the same):\n" + json.dumps(base_plan)
    messages = [{"role": "user", "content": first}]
    usage = []
    for attempt in range(3):
        text, u = call_claude(system, messages)
        usage.append(u)
        try:
            plan = parse_plan(text)
            probs = check_plan(plan, a, items)
            if not probs:
                plan.pop("settings_override", None)
                html, title, checks = render.build_plan_page(plan, FAMILY_BUSINESS)
                probs = [c for c in checks if c.startswith("CHECK")]
                if not probs or attempt == 2:
                    return plan, html, title, checks + [f"usage: {usage}"]
        except (StylistError, render.BuildError) as e:
            probs = [str(e)]
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": "Fix these and send the whole plan JSON again:\n- " + "\n- ".join(probs)}]
    raise StylistError("Couldn't make a clean plan after three tries: " + "; ".join(probs))


# ---------- the build job ----------
def _swap_bar(oid, a):
    """A small bar on her page: swap a piece (until photo day) and a way to reach us."""
    return (f"<div style=\"font:14px Jost,system-ui,sans-serif;text-align:center;padding:14px 16px;border-top:1px solid #e2e2e2;"
            f"margin-top:24px\">Want to change something? <a href=\"{config.PUBLIC_BASE}/o/{oid}/swap\" "
            f"style=\"color:#121212\">Swap a piece</a>, as many times as you like until photo day.</div>")


def _with_bar(html, oid, a):
    bar = _swap_bar(oid, a)
    return html.replace("</body>", bar + "</body>", 1) if "</body>" in html else html + bar


def build(oid, request_note=None):
    o = get_order(oid)
    if not o:
        return
    o["status"] = "building"
    log(o, "building" + (f" (swap: {request_note})" if request_note else ""))
    save_order(o)
    try:
        plan, html, title, notes = stylist(o["answers"], request_note, o.get("plan") if request_note else None)
        pid = store.save_page("family", _with_bar(html, oid, o["answers"]), title, "plan", o.get("page_id"))
        o.update(status="ready", page_id=pid, plan=plan, url=f"{config.PUBLIC_BASE}/p/{pid}", swap_pending=False)
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
