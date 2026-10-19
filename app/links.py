"""Smart shop links (/s/<piece>-<tier>) and the nightly link check.

A board prints justwearthis.co/s/W-DRS-003-mid. The server sends the client to the store page if it's live; if it
died, to another live price for the same piece; then to the store's own search for that kind of piece; then to the
still-looking page. A link only counts as dead after two failed checks in a row.

Some stores (Target, H&M, Lulus...) block the server, so the nightly check can't see them. Those are checked in a real
browser (Claude in Chrome) and recorded in engine/library/browser_checks.json. A browser result fills in wherever the
server's own result is "unchecked", for BROWSER_DAYS days; a fresher server "ok" or "dead" always wins.
"""
import asyncio, datetime, json, os, re, threading, time
from urllib.parse import quote_plus, urlparse
from zoneinfo import ZoneInfo

import httpx

from . import config

TIERS = ("everyday", "mid", "splurge")
FALLBACK_ORDER = {"everyday": ("everyday", "mid", "splurge"), "mid": ("mid", "everyday", "splurge"),
                  "splurge": ("splurge", "mid", "everyday")}
STILL_LOOKING = "/still-looking/"
CENTRAL = ZoneInfo("America/Chicago")
_lock = threading.Lock()

# ---------------- library ----------------
_catalog = {"mtime": 0, "items": {}}


def pieces():
    m = os.path.getmtime(config.CATALOG)
    if m != _catalog["mtime"]:
        cat = json.load(open(config.CATALOG))
        _catalog["items"] = {it["id"].upper(): it for it in cat["items"]}
        _catalog["mtime"] = m
    return _catalog["items"]


# ---------------- health ----------------
def health():
    try:
        return json.load(open(config.HEALTH_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_health(h):
    tmp = config.HEALTH_FILE + ".tmp"
    json.dump(h, open(tmp, "w"), indent=1)
    os.replace(tmp, config.HEALTH_FILE)


BROWSER_DAYS = 21
_browser = {"mtime": 0, "checks": {}}


def browser_checks():
    try:
        m = os.path.getmtime(config.BROWSER_CHECKS)
    except OSError:
        return {}
    if m != _browser["mtime"]:
        try:
            _browser["checks"] = json.load(open(config.BROWSER_CHECKS)).get("links", {})
        except (json.JSONDecodeError, OSError):
            _browser["checks"] = {}
        _browser["mtime"] = m
    return _browser["checks"]


def _fresh(day):
    try:
        d = datetime.date.fromisoformat(day[:10])
    except (TypeError, ValueError):
        return False
    return (datetime.date.today() - d).days <= BROWSER_DAYS


def effective(url, h=None, b=None):
    """The status a link is treated as: {'status': 'ok'|'dead'|'unchecked', 'source': 'server'|'browser'|'none', ...}."""
    h = health() if h is None else h
    b = browser_checks() if b is None else b
    srv, br = h.get(url), b.get(url)
    if srv and (srv.get("dead") or srv.get("status") == "ok"):
        srv_day = (srv.get("checked") or "")[:10]
        if not (br and _fresh(br.get("checked")) and br.get("checked", "")[:10] > srv_day):
            return {"status": "dead" if srv.get("dead") else "ok", "source": "server", "note": srv.get("note", ""),
                    "checked": srv.get("checked", "")}
    if br and _fresh(br.get("checked")) and br.get("status") in ("ok", "dead"):
        return {"status": br["status"], "source": "browser", "note": br.get("note", ""), "checked": br.get("checked", "")}
    if srv:
        return {"status": "unchecked", "source": "server", "note": srv.get("note", ""), "checked": srv.get("checked", "")}
    return {"status": "unchecked", "source": "none", "note": "never checked", "checked": ""}


def is_dead(url, h=None, b=None):
    return effective(url, h, b)["status"] == "dead"


def has_live_link(piece, h=None, b=None):
    """False only when every link the piece has is known dead (or it has none)."""
    us = [u for u in (piece.get("shop_links") or {}).values() if u]
    return any(not is_dead(u, h, b) for u in us)


# ---------------- store search fallback ----------------
SHOPIFY = {"us.boden.com", "www.shopdoen.com", "tnuck.com", "www.hillhousehome.com", "www.littleenglish.com",
           "www.rachelriley.com", "hopeandhenry.com", "balticborn.com", "petalandpup.com", "ryleeandcru.com",
           "fahertybrand.com", "www.toddsnyder.com", "christydawn.com", "shopdressup.com", "www.everlane.com"}
SEARCH = {
    "www.target.com": "https://www.target.com/s?searchTerm={q}",
    "oldnavy.gap.com": "https://oldnavy.gap.com/browse/search.do?searchText={q}",
    "www.gap.com": "https://www.gap.com/browse/search.do?searchText={q}",
    "www.gapfactory.com": "https://www.gapfactory.com/browse/search.do?searchText={q}",
    "bananarepublic.gap.com": "https://bananarepublic.gap.com/browse/search.do?searchText={q}",
    "www2.hm.com": "https://www2.hm.com/en_us/search-results.html?q={q}",
    "www.nordstrom.com": "https://www.nordstrom.com/sr?keyword={q}",
    "www.jcrew.com": "https://www.jcrew.com/r/search/?N=0&Nloc=en&Ntrm={q}",
    "factory.jcrew.com": "https://factory.jcrew.com/r/search/?N=0&Nloc=en&Ntrm={q}",
    "www.llbean.com": "https://www.llbean.com/llb/search/?freeText={q}",
    "www.kohls.com": "https://www.kohls.com/search.jsp?search={q}",
    "www.amazon.com": "https://www.amazon.com/s?k={q}",
    "www.quince.com": "https://www.quince.com/search?query={q}",
    "www.lulus.com": "https://www.lulus.com/searchresults?q={q}",
}
PERSON_WORD = {"women": "women's", "men": "men's", "girls": "girls", "boys": "boys", "toddlers": "toddler",
               "babies": "baby", "teen girls": "girls", "teen boys": "boys"}


def search_url(piece, store_url):
    host = urlparse(store_url).netloc.lower()
    tpl = SEARCH.get(host) or (f"https://{host}/search?q={{q}}" if host in SHOPIFY else None)
    if not tpl:
        return None
    words = f"{PERSON_WORD.get(piece.get('person', ''), '')} {piece.get('name', '')}".strip()
    return tpl.format(q=quote_plus(words))


# ---------------- resolving /s/ links ----------------
def resolve(code):
    """code like 'W-DRS-003-mid' or 'W-DRS-003'. Returns (url, how)."""
    code = code.strip().strip("/")
    m = re.match(r"^(.+?)(?:-(everyday|mid|splurge))?$", code, re.I)
    pid, tier = m.group(1).upper(), (m.group(2) or "mid").lower()
    piece = pieces().get(pid)
    if not piece:
        return STILL_LOOKING, "unknown piece"
    links = piece.get("shop_links") or {}
    h, b = health(), browser_checks()
    for t in FALLBACK_ORDER[tier]:
        u = links.get(t)
        if u and not is_dead(u, h, b):
            return u, "direct" if t == tier else f"fallback:{t}"
    for t in FALLBACK_ORDER[tier]:  # every link dead: the store's own search for this kind of piece
        u = links.get(t)
        s = search_url(piece, u) if u else None
        if s:
            return s, "store search"
    return STILL_LOOKING, "still looking"


# ---------------- the check ----------------
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/128.0 Safari/537.36")
IN_STOCK = re.compile(r'schema\.org/InStock|"availability"\s*:\s*"InStock"')
OUT_STOCK = re.compile(r'schema\.org/(OutOfStock|SoldOut|Discontinued)|"availability"\s*:\s*"(OutOfStock|SoldOut)"')
JCREW_PLATFORM = {"www.jcrew.com", "jcrew.com", "factory.jcrew.com", "www.madewell.com"}
GAP_FAMILY = {"oldnavy.gap.com", "www.gap.com", "www.gapfactory.com", "bananarepublic.gap.com"}
# Stores that wall off automated visits. We still try; a wall reads as "unchecked", never as dead.
WALLED = {"www.target.com", "www2.hm.com", "www.lulus.com", "www.sezane.com", "shop.mango.com",
          "www.samedelman.com", "www.kohls.com", "www.amazon.com", "www.hannaandersson.com", "www.walmart.com"}


def _title(html):
    m = re.search(r"<title[^>]*>([^<]*)", html, re.I)
    return (m.group(1) if m else "").strip()


async def check_one(client, url):
    """Returns ('ok'|'dead'|'unchecked', note)."""
    p = urlparse(url)
    host = p.netloc.lower()
    try:
        m = re.search(r"/products/([^/?#]+)", p.path)
        if m and host in SHOPIFY:
            r = await client.get(f"https://{host}/products/{m.group(1)}.js")
            if r.status_code == 404:
                return "dead", "not found"
            if r.status_code == 200:
                j = r.json()
                return ("ok", "available") if j.get("available") else ("dead", "sold out in every size")
            return "unchecked", f"status {r.status_code}"
        r = await client.get(url)
        body = r.text
        fin = urlparse(str(r.url))
        if r.status_code in (404, 410):
            return "dead", "not found"
        if r.status_code in (401, 403, 429, 503) or len(body) < 12000:
            return "unchecked", f"blocked ({r.status_code})"
        title = _title(body)
        ins, oos = len(IN_STOCK.findall(body)), len(OUT_STOCK.findall(body))
        if re.search(r"page not available|product not found|item not available|page not found", title, re.I):
            return "dead", title[:60]
        if fin.path.rstrip("/") != p.path.rstrip("/"):
            same_item = (re.search(r"/(\d{5,})(?:\D|$)", p.path) and re.search(r"/(\d{5,})(?:\D|$)", p.path).group(1) in fin.path)
            if not same_item and (re.search(r"/(c|plp|search|browse/category|shop/[a-z-]+/?$)", fin.path) or fin.path in ("", "/")):
                return "dead", f"now goes to {fin.path[:50]}"
        if host in GAP_FAMILY:
            if not title.replace("| Old Navy", "").strip():
                return "dead", "no product"
            return ("ok", f"{ins} in stock") if ins else (("dead", "sold out") if oos else ("unchecked", "no stock data"))
        if ins:
            return "ok", f"{ins} in stock"
        if oos or host in JCREW_PLATFORM:
            return "dead", "sold out"
        if host == "www.landsend.com":
            return "ok", "page live"
        return "unchecked", "no stock data"
    except Exception as e:  # network trouble is never a reason to call a link dead
        return "unchecked", type(e).__name__


async def check_all(only_host=None):
    urls = {}
    for pid, it in pieces().items():
        for t, u in (it.get("shop_links") or {}).items():
            if u:
                urls.setdefault(u, []).append(f"{pid}-{t}")
    by_host = {}
    for u in urls:
        h = urlparse(u).netloc.lower()
        if not only_host or h == only_host:
            by_host.setdefault(h, []).append(u)
    results = {}
    started = time.strftime("%Y-%m-%d %H:%M")
    limits = httpx.Limits(max_connections=8)
    async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"},
                                 follow_redirects=True, timeout=25, limits=limits) as client:
        async def run_host(host, lst):
            for u in lst:  # one store at a time, slowly, so nobody's bot wall trips
                results[u] = await check_one(client, u)
                await asyncio.sleep(2.5)
        await asyncio.gather(*(run_host(h, l) for h, l in by_host.items()))
    now = time.strftime("%Y-%m-%d %H:%M")
    with _lock:
        h = health()
        for u, (status, note) in results.items():
            rec = h.get(u, {})
            fails = rec.get("fails", 0) + 1 if status == "dead" else 0
            rec.update(status=status, note=note, checked=now, fails=fails,
                       dead=fails >= 2 or (status == "dead" and rec.get("dead", False)),
                       pieces=urls.get(u, []))
            if status == "ok":
                rec["dead"] = False
            h[u] = rec
        # forget links that left the library
        for u in list(h):
            if u not in urls:
                del h[u]
        _save_health(h)
    s = summary()
    try:
        json.dump({"started": started, "finished": time.strftime("%Y-%m-%d %H:%M"), "host": only_host or "all",
                   "checked": len(results), "summary": s}, open(config.CHECK_RUN_FILE, "w"), indent=1)
    except OSError:
        pass
    return s


def last_run():
    try:
        return json.load(open(config.CHECK_RUN_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def all_links():
    """{url: [piece-tier, ...]} for every link in the library."""
    urls = {}
    for pid, it in pieces().items():
        for t, u in (it.get("shop_links") or {}).items():
            if u:
                urls.setdefault(u, []).append(f"{pid}-{t}")
    return urls


def summary():
    h, b = health(), browser_checks()
    urls = all_links()
    counts = {"ok": 0, "dead": 0, "unchecked": 0}
    by_source = {"server": 0, "browser": 0}
    for u in urls:
        e = effective(u, h, b)
        counts[e["status"]] += 1
        if e["status"] != "unchecked":
            by_source[e["source"]] += 1
    no_live = sorted(pid for pid, it in pieces().items()
                     if [u for u in (it.get("shop_links") or {}).values() if u] and not has_live_link(it, h, b))
    return {"links": len(urls), **counts, "checked_by": by_source, "pieces_with_no_live_link": no_live}


async def nightly():
    """Runs inside the web server: every night at CHECK_HOUR Central."""
    while True:
        now = datetime.datetime.now(CENTRAL)
        nxt = now.replace(hour=config.CHECK_HOUR, minute=15, second=0, microsecond=0)
        if nxt <= now:
            nxt += datetime.timedelta(days=1)
        await asyncio.sleep((nxt - now).total_seconds())
        try:
            await check_all()
        except Exception as e:
            print("link check failed:", e, flush=True)
