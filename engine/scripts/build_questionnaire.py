"""Build the studio's client questionnaire page: one phone-friendly page the photographer sends to every client.
The client taps through six questions, then sends her answers to the studio by text or email (or copies them).
The answers arrive as plain text the photographer pastes into Claude.

Usage: python3 build_questionnaire.py --out <folder> [--override settings_override.json]
The override file holds the same keys as settings.json (studio_name, contact_email, contact_phone, texting...)."""
import argparse, html, json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))


def build(settings, out_dir):
    studio = (settings.get("studio_name") or "").strip()
    if not studio:
        raise SystemExit("studio_name is missing: ask the photographer for their business details first.")
    email = (settings.get("contact_email") or "").strip()
    phone = (settings.get("contact_phone") or "").strip()
    texting = bool(settings.get("texting", True))
    first = studio.split()[0] if studio else "me"
    cfg = {
        "studio": studio,
        "email": email,
        "sms": re.sub(r"[^\d+]", "", phone) if (phone and texting) else "",
        "phone": phone,
        "send": settings.get("send_page", "https://justwearthis.co/send/"),
    }
    e = html.escape
    page = TEMPLATE
    for k, v in {
        "{{TITLE}}": e(f"Outfit Questions · {studio}"),
        "{{STUDIO}}": e(studio),
        "{{CFG}}": json.dumps(cfg).replace("</", "<\\/"),
    }.items():
        page = page.replace(k, v)
    os.makedirs(out_dir, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", studio.lower()).strip("-")
    out = os.path.join(out_dir, f"{slug}-questionnaire.html")
    open(out, "w").write(page)
    print(f"Questionnaire page: {out} ({os.path.getsize(out) // 1024} KB)")
    if not email and not cfg["sms"]:
        print("CHECK: no email and no texting number, so clients can only copy their answers. Ask for one.")
    return out


TEMPLATE = r"""<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=Bodoni+Moda:ital,opsz,wght@0,6..96,500;1,6..96,400&family=Jost:wght@300;400;500&display=swap" rel="stylesheet">
<style>
/* Brand D, quiet (client-facing): white page, black for words only, Bodoni Moda headings, Jost labels and body.
   One question per screen, phone first. Matches the client outfit page. */
:root{
  --paper:#ffffff; --ink:#121212; --soft:#6b6b6b; --line:#e2e2e2;
  --sans:"Jost",system-ui,-apple-system,"Segoe UI",sans-serif; --serif:"Bodoni Moda",Didot,Georgia,serif; --mark:"Anton",Impact,sans-serif;
}
*{box-sizing:border-box} [hidden]{display:none!important}
html,body{margin:0}
body{color-scheme:light;background:var(--paper);color:var(--ink);font:16px/1.55 var(--sans);-webkit-font-smoothing:antialiased}
.wrap{max-width:560px;margin:0 auto;padding:18px 22px 120px;min-height:100vh;display:flex;flex-direction:column;gap:28px}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
.mark{font-family:var(--mark);font-size:17px;text-transform:uppercase;letter-spacing:.01em}
.by{font-size:10px;letter-spacing:.2em;text-transform:uppercase;font-weight:300}
.bar{height:2px;background:var(--line);overflow:hidden;margin-top:-14px}
.bar i{display:block;height:100%;width:0;background:var(--ink);transition:width .3s ease}
.step{display:flex;flex-direction:column;gap:18px;animation:in .25s ease}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){.step{animation:none}.bar i{transition:none}}
.eyebrow{font-size:11px;letter-spacing:.24em;text-transform:uppercase;font-weight:300}
h1{font-family:var(--serif);font-size:clamp(36px,10vw,50px);line-height:1;font-weight:500;letter-spacing:-.02em;margin:0;text-wrap:balance}
h2{font-family:var(--serif);font-size:clamp(27px,7vw,34px);line-height:1.1;font-weight:500;letter-spacing:-.015em;margin:0;text-wrap:balance}
.hand{font-family:var(--serif);font-style:italic;font-size:21px;line-height:1.3;margin:0}
.sub{color:var(--soft);margin:0}
label.f{display:flex;flex-direction:column;gap:6px;font-size:11px;letter-spacing:.2em;text-transform:uppercase}
label.f small{letter-spacing:0;text-transform:none;font-size:13px;color:var(--soft)}
input[type=text],input[type=number],textarea{font:16px var(--sans);letter-spacing:0;text-transform:none;color:var(--ink);background:var(--paper);border:0;border-bottom:1px solid var(--ink);border-radius:0;padding:10px 0;width:100%}
textarea{min-height:110px;resize:vertical;border:1px solid var(--ink);padding:12px 14px}
input:focus,textarea:focus{outline:none;border-color:var(--ink);box-shadow:0 1px 0 var(--ink)}
textarea:focus{box-shadow:inset 0 0 0 1px var(--ink)}
.q{font-size:11px;letter-spacing:.2em;text-transform:uppercase;margin:0 0 10px}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{font:400 15px var(--sans);color:var(--ink);background:var(--paper);border:1px solid var(--line);border-radius:0;padding:10px 16px;cursor:pointer;min-height:44px}
.chip:hover{border-color:var(--ink)}
.chip[aria-pressed=true]{background:var(--ink);color:var(--paper);border-color:var(--ink)}
.chip:focus-visible,.btn:focus-visible,.link:focus-visible{outline:2px solid var(--ink);outline-offset:2px}
.chips.big{flex-direction:column}
.chips.big .chip{text-align:left;padding:14px 16px;font-weight:500}
.chip span{display:block;font-weight:400;font-size:13px;color:var(--soft)}
.chip[aria-pressed=true] span{color:#cfcfcf}
.person{border-top:1px solid var(--ink);padding:16px 0 4px;display:flex;flex-direction:column;gap:18px}
.phead{display:flex;justify-content:space-between;align-items:baseline}
.phead b{font-family:var(--serif);font-size:22px;font-weight:500}
.link{all:unset;cursor:pointer;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--soft);padding:6px 2px;text-decoration:underline;text-underline-offset:4px}
.add{all:unset;cursor:pointer;text-align:center;border:1px dashed var(--ink);padding:16px;font-size:11px;letter-spacing:.24em;text-transform:uppercase}
.add:focus-visible{outline:2px solid var(--ink)}
.nav{position:fixed;left:0;right:0;bottom:0;background:linear-gradient(transparent,var(--paper) 30%);padding:28px 22px 18px}
.nav div{max-width:516px;margin:0 auto;display:flex;gap:10px}
.btn{font:400 12px var(--sans);letter-spacing:.24em;text-transform:uppercase;border-radius:0;padding:17px 18px;border:1px solid var(--ink);background:var(--ink);color:var(--paper);cursor:pointer;flex:1;text-align:center;text-decoration:none;display:block}
.btn.ghost{background:var(--paper);color:var(--ink);flex:0 0 auto}
.err{color:#9b2c2c;font-size:14px;margin:0}
.sum{border-top:1px solid var(--ink);padding:16px 0;display:flex;flex-direction:column;gap:12px;font-size:15px}
.sum div b{display:block;font-size:11px;letter-spacing:.2em;text-transform:uppercase;font-weight:400}
.send{display:flex;flex-direction:column;gap:10px}
.tip{border-left:2px solid var(--ink);padding:4px 0 4px 14px;font-size:15px;margin:0}
.raw{width:100%;min-height:200px;font:14px/1.5 ui-monospace,Menlo,monospace}
.done{font-family:var(--serif);font-size:clamp(34px,9vw,44px);line-height:1.05;margin:0}
.done em{font-weight:400}
</style>

<div class="wrap">
  <div class="top"><span class="mark">Just Wear This.</span><span class="by">{{STUDIO}}</span></div>
  <div class="bar" aria-hidden="true"><i id="bar"></i></div>
  <main id="main" aria-live="polite"></main>
</div>
<div class="nav" id="nav"><div>
  <button class="btn ghost" id="back" type="button">Back</button>
  <button class="btn" id="next" type="button">Next</button>
</div></div>

<script>
const CFG = {{CFG}};
const KEY = "jwt-questionnaire-" + CFG.studio;
const AGES = ["Adult", "Teen", "Kid", "Toddler", "Baby"];
const SHOP = ["Women's", "Men's", "Girls'", "Boys'", "Either"];
const DRESS = [["Relaxed", "Comfy and casual"], ["Dressy casual", "Nice, not fussy"], ["Polished", "Our Sunday best"], ["Formal", "Suits and gowns energy"], ["Not sure, you decide", "Trust the stylist"]];
const PRINTS = [["Love them", "Bring on the florals and plaids"], ["A little is nice", "One or two people in a print"], ["Solids please", "We'll use texture instead"]];

const ROOM_YES = "Yes, I'll send a photo of the room";
const blank = () => ({name: "", age: "", kidAge: "", shop: "", dress: "", nope: ""});
let A = {who: "", family: "", people: [blank()], level: "", love: "", never: "", prints: "", own: "", room: "", extra: ""};
try { const s = JSON.parse(localStorage.getItem(KEY) || "null"); if (s && s.people) A = s; } catch (e) {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(A)); } catch (e) {} };

const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const chips = (key, opts, val, idx) => `<div class="chips" role="group">${opts.map(o =>
  `<button type="button" class="chip" data-k="${key}" ${idx != null ? `data-i="${idx}"` : ""} data-v="${esc(o)}" aria-pressed="${val === o}">${esc(o)}</button>`).join("")}</div>`;
const bigChips = (key, opts, val) => `<div class="chips big" role="group">${opts.map(([o, d]) =>
  `<button type="button" class="chip" data-k="${key}" data-v="${esc(o)}" aria-pressed="${val === o}">${esc(o)}<span>${esc(d)}</span></button>`).join("")}</div>`;

const STEPS = [
  {id: "hello", render: () => `
    <div class="step">
      <span class="eyebrow">Outfit questions</span>
      <h1>Let's take outfits off your to-do list.</h1>
      <p class="hand">Six quick questions, about three minutes.</p>
      <p class="sub">Then I'll send you a personal outfit page for your family: tap any piece to shop it at a few price points, and check things off as they arrive.</p>
      <label class="f">Your first name<input type="text" data-f="who" value="${esc(A.who)}" autocomplete="given-name"></label>
      <label class="f">Family last name <small>So ${esc(CFG.studio)} knows whose answers these are</small><input type="text" data-f="family" value="${esc(A.family)}" autocomplete="family-name"></label>
    </div>`, ok: () => A.who.trim() ? "" : "Add your first name so we know who's answering."},

  {id: "people", render: () => `
    <div class="step">
      <span class="eyebrow">1 of 6</span>
      <h2>Who's in the photos?</h2>
      <p class="sub">First names are perfect (or Mom, Dad, Grandma).</p>
      ${A.people.map((p, i) => `
        <div class="person">
          <div class="phead"><b>${p.name ? esc(p.name) : "Person " + (i + 1)}</b>${A.people.length > 1 ? `<button type="button" class="link" data-rm="${i}">Remove</button>` : ""}</div>
          <label class="f">Name<input type="text" data-p="name" data-i="${i}" value="${esc(p.name)}"></label>
          <div><p class="q">Age</p>${chips("age", AGES, p.age, i)}
            ${p.age === "Kid" ? `<label class="f" style="margin-top:10px">How old?<input type="number" inputmode="numeric" min="2" max="17" data-p="kidAge" data-i="${i}" value="${esc(p.kidAge)}"></label>` : ""}</div>
          <div><p class="q">Shop from</p>${chips("shop", SHOP, p.shop, i)}</div>
          ${["Baby", "Toddler"].includes(p.age) ? "" : `<div><p class="q">Dressing up?</p>${chips("dress", ["Happy to", "Basics only"], p.dress, i)}</div>`}
          <label class="f">Anything they won't wear? <small>Optional. Heels, patterns, ties, collars, bows, scratchy fabrics…</small><input type="text" data-p="nope" data-i="${i}" value="${esc(p.nope)}"></label>
        </div>`).join("")}
      <button type="button" class="add" id="addp">+ Add someone</button>
    </div>`,
    ok: () => {
      const bad = A.people.findIndex(p => !p.name.trim() || !p.age);
      return bad < 0 ? "" : `Add a name and age for ${A.people[bad].name.trim() || "person " + (bad + 1)}.`;
    }},

  {id: "level", render: () => `
    <div class="step">
      <span class="eyebrow">2 of 6</span>
      <h2>How dressy would you like to be?</h2>
      ${bigChips("level", DRESS, A.level)}
    </div>`, ok: () => A.level ? "" : "Pick one (\"Not sure\" is a great answer)."},

  {id: "colors", render: () => `
    <div class="step">
      <span class="eyebrow">3 of 6</span>
      <h2>Any colors you love, or never want to see?</h2>
      <p class="sub">Optional. We'll keep the never colors out of prints too.</p>
      <label class="f">Colors you love<input type="text" data-f="love" value="${esc(A.love)}" placeholder="Sage, rust, cream…"></label>
      <label class="f">Never, please<input type="text" data-f="never" value="${esc(A.never)}" placeholder="Orange, bright red…"></label>
    </div>`, ok: () => ""},

  {id: "prints", render: () => `
    <div class="step">
      <span class="eyebrow">4 of 6</span>
      <h2>How do you feel about prints?</h2>
      ${bigChips("prints", PRINTS, A.prints)}
    </div>`, ok: () => A.prints ? "" : "Pick one."},

  {id: "own", render: () => `
    <div class="step">
      <span class="eyebrow">5 of 6</span>
      <h2>Anything you already own and want to wear?</h2>
      <p class="sub">Optional. Shoes count! Tell us what it is and who it's for. You'll add photos when you send your answers.</p>
      <textarea data-f="own" placeholder="Mom: my cream cable sweater. Ava: her brown boots.">${esc(A.own)}</textarea>
      <div><p class="q">Will the photos hang in your home?</p>${chips("room", [ROOM_YES, "No"], A.room)}</div>
    </div>`, ok: () => ""},

  {id: "extra", render: () => {
    const room = A.room === ROOM_YES;
    const photos = A.own.trim() || room;
    return `
    <div class="step">
      <span class="eyebrow">6 of 6</span>
      <h2>Anything else I should know?</h2>
      <p class="sub">Optional. Comfort needs, pregnancy, mobility or sensory needs, modesty, or anything you're nervous about.</p>
      <textarea data-f="extra">${esc(A.extra)}</textarea>
      ${photos ? `<p class="tip">Your ${CFG.sms && !CFG.email ? "text" : "email"} opens next with everything written in. Attach your photos${A.own.trim() ? " of the pieces you own" : ""}${room ? (A.own.trim() ? " and" : "") + " of the room" : ""}, then hit send.</p>` : `<p class="sub">Your ${CFG.sms && !CFG.email ? "text" : "email"} opens next with everything written in. Just hit send.</p>`}
      <div class="send">
        ${CFG.email ? `<a class="btn" data-m="email" target="_blank" rel="noopener">Email my answers to ${esc(CFG.studio)}</a>` : ""}
        ${CFG.sms ? `<a class="btn ${CFG.email ? "ghost" : ""}" data-m="sms" target="_blank" rel="noopener">Text my answers${CFG.email ? " instead" : ` to ${esc(CFG.studio)}`}</a>` : ""}
        ${!CFG.email && !CFG.sms ? `<button type="button" class="btn" id="copy">Copy my answers</button>` : ""}
      </div>
      <p class="sub" id="copied" hidden></p>
      <textarea class="raw" id="raw" readonly hidden></textarea>
    </div>`;
  }, ok: () => ""},

  {id: "thanks", render: () => `
    <div class="step" style="text-align:center;align-items:center">
      <span class="eyebrow">All done</span>
      <p class="done">Thank you, <em>${esc(A.who.trim())}!</em></p>
      <p class="sub">Hit send in your ${CFG.sms && !CFG.email ? "texts" : "email"} and ${esc(CFG.studio)} will put together your outfit page.</p>
      <button type="button" class="btn ghost" id="copy" style="flex:0 0 auto">Didn't open? Copy my answers</button>
      <p class="sub" id="copied" hidden></p>
      <textarea class="raw" id="raw" readonly hidden></textarea>
      <button type="button" class="link" id="edit">Go back and change something</button>
    </div>`, ok: () => ""},
];

// Answers ride in the URL #fragment, which browsers never send to the server: they stay on the client's phone.
function packed(o) {
  const bytes = new TextEncoder().encode(JSON.stringify(o));
  let bin = ""; bytes.forEach(b => bin += String.fromCharCode(b));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function sendUrl(m) {
  const room = A.room === ROOM_YES;
  const tip = (A.own.trim() || room) ? `Attach your photos${A.own.trim() ? " of the pieces you own" : ""}${room ? (A.own.trim() ? " and" : "") + " of the room" : ""} before you send.` : "";
  return CFG.send + "#" + packed({s: CFG.studio, e: CFG.email, p: CFG.sms, j: `Outfit questions: ${familyLabel()}`, b: answersText(), t: tip, m});
}
function refreshSend() { main.querySelectorAll("a[data-m]").forEach(a => { a.href = sendUrl(a.dataset.m); }); }
function familyLabel() {
  const f = A.family.trim();
  return f ? `The ${f} family` : `${A.who.trim()}'s family`;
}
function personLine(p) {
  const age = p.age === "Kid" && p.kidAge ? `Kid, ${p.kidAge}` : p.age;
  const bits = [age, p.shop, ["Baby", "Toddler"].includes(p.age) ? "" : p.dress === "Basics only" ? "basics only, no dressing up" : (p.dress === "Happy to" ? "happy to dress up" : "")].filter(Boolean);
  return `${p.name.trim()}: ${bits.join(", ")}${p.nope.trim() ? `. Won't wear: ${p.nope.trim()}` : ""}`;
}
function answersText() {
  return [
    `Hi! Here are our answers for the outfit plan.`,
    ``,
    `Just Wear This outfit questions`,
    `${familyLabel()} (from ${A.who.trim()})`,
    ``,
    `1. Who's coming`,
    ...A.people.map(p => `- ${personLine(p)}`),
    `2. How dressy: ${A.level}`,
    `3. Colors we love: ${A.love.trim() || "no preference"}. Never: ${A.never.trim() || "none"}`,
    `4. Prints: ${A.prints}`,
    `5. Already own: ${A.own.trim() || "nothing specific"}${A.own.trim() ? " (photos attached)" : ""}${A.room === ROOM_YES ? ". Photos will hang at home (room photo attached)" : ""}`,
    `6. Anything else: ${A.extra.trim() || "nothing"}`,
  ].join("\n");
}

let cur = 0, err = "";
try { const c = Number(sessionStorage.getItem(KEY + "-step")); if (c > 0 && c < STEPS.length - 1) cur = c; } catch (e) {}
const main = document.getElementById("main"), bar = document.getElementById("bar");
const back = document.getElementById("back"), next = document.getElementById("next"), nav = document.getElementById("nav");

function render(focusTop) {
  const s = STEPS[cur];
  main.innerHTML = s.render() + (err ? `<p class="err" role="alert">${esc(err)}</p>` : "");
  bar.style.width = (cur / (STEPS.length - 1) * 100) + "%";
  back.hidden = cur === 0;
  next.hidden = s.id === "extra";
  nav.hidden = s.id === "thanks";
  next.textContent = cur === 0 ? "Start" : "Next";
  refreshSend();
  const raw = document.getElementById("raw"); if (raw) raw.value = answersText();
  try { sessionStorage.setItem(KEY + "-step", cur); } catch (e) {}
  if (focusTop) { window.scrollTo(0, 0); const h = main.querySelector("h1,h2"); if (h) { h.tabIndex = -1; h.focus({preventScroll: true}); } }
}

main.addEventListener("input", ev => {
  const t = ev.target;
  if (t.dataset.f) A[t.dataset.f] = t.value;
  if (t.dataset.p) A.people[+t.dataset.i][t.dataset.p] = t.value;
  save(); refreshSend();
});
main.addEventListener("click", ev => {
  const c = ev.target.closest(".chip");
  if (c) {
    const k = c.dataset.k, v = c.dataset.v;
    if (c.dataset.i != null) {
      const p = A.people[+c.dataset.i];
      p[k] = p[k] === v ? "" : v;
    } else if (k === "room") A.room = A.room === v ? "" : v;
    else A[k] = A[k] === v ? "" : v;
    save(); err = ""; render(false);
    if (k === "age" && v === "Kid" && c.dataset.i != null) { const n = main.querySelector(`input[data-p=kidAge][data-i="${c.dataset.i}"]`); if (n) n.focus(); }
    return;
  }
  if (ev.target.id === "addp") { A.people.push(blank()); save(); render(false); const ins = main.querySelectorAll("input[data-p=name]"); ins[ins.length - 1].focus(); return; }
  if (ev.target.dataset.rm != null) { A.people.splice(+ev.target.dataset.rm, 1); save(); render(false); return; }
  if (ev.target.id === "edit") { cur = STEPS.length - 2; render(true); return; }
  const send = ev.target.closest("a[data-m]");
  if (send) { refreshSend(); setTimeout(() => { cur = STEPS.length - 1; render(true); }, 400); return; }
  if (ev.target.id === "copy") {
    const raw = document.getElementById("raw"), msg = document.getElementById("copied");
    raw.value = answersText();
    const show = () => { msg.hidden = false; msg.textContent = "Copied! Paste it into a text or email to " + CFG.studio + (CFG.email ? " (" + CFG.email + ")" : "") + (CFG.phone ? " or " + CFG.phone : "") + "."; };
    const fallback = () => { raw.hidden = false; raw.focus(); raw.select(); msg.hidden = false; msg.textContent = "Select all and copy, then paste it into a text or email to " + CFG.studio + "."; };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(raw.value).then(show, fallback); else fallback();
  }
});
next.addEventListener("click", () => {
  err = STEPS[cur].ok();
  if (err) { render(false); return; }
  cur = Math.min(cur + 1, STEPS.length - 1); render(true);
});
back.addEventListener("click", () => { err = ""; cur = Math.max(cur - 1, 0); render(true); });
render(false);
</script>
"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--override", help="JSON file with settings_override keys (studio_name, contact_email, contact_phone, texting)")
    a = ap.parse_args()
    st = json.load(open(os.path.join(HERE, "..", "settings.json")))
    if a.override:
        ov = json.load(open(a.override))
        st.update(ov.get("settings_override", ov))
    build(st, a.out)
