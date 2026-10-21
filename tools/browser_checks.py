"""Browser link checks: the stores that block the server get checked in Emily's Chrome (Claude in Chrome).

  python3 tools/browser_checks.py list [--all] [--limit N]   links due for a browser check, walled stores first
  python3 tools/browser_checks.py record results.json         merge results into engine/library/browser_checks.json

results.json: [{"url": ..., "status": "ok"|"dead"|"unchecked", "note": "..."}]. "unchecked" entries are skipped.
After recording, commit and push: Render redeploys and the server uses the results for 7 days.
Runs Tuesdays and Fridays; each run checks every store link not already checked in the last 2 days.

PACE: one product page at a time, about 10 seconds apart, by opening it in the tab. Never fire fetch() loops at a
store: H&M blocked Emily's own browser ("Access Denied") after a fast burst on Oct 15. Stop a store at the first
block page and come back another day. A block page is never a reason to call a link dead.

How to check one link in Chrome: open the URL, wait ~2s, then run PROBE (below) in the page. Read it as:
  dead  = redirected to a category/search page, a not-found page, OutOfStock only, or only "Notify me" buttons
  ok    = an "Add to bag/cart" button (InStock in the page data helps confirm)
  Check the color too when the store encodes it in the link (Old Navy/Gap pid, Target preselect).
"""
import datetime, json, os, sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "engine", "library", "catalog.json")
OUT = os.path.join(ROOT, "engine", "library", "browser_checks.json")
DAYS = 7
RECHECK_AFTER = 2  # days; so the Tuesday and Friday runs each check every link
WALLED = {"www.target.com", "www2.hm.com", "www.lulus.com", "www.sezane.com", "shop.mango.com", "www.samedelman.com",
          "www.kohls.com", "www.amazon.com", "www.hannaandersson.com", "www.walmart.com", "www.janieandjack.com"}

PROBE = r"""const ld=[...document.querySelectorAll('script[type="application/ld+json"]')].map(s=>s.textContent).join(' ');
({url:location.pathname.slice(0,90),title:document.title.slice(0,80),
  av:[...new Set(ld.match(/(InStock|OutOfStock|SoldOut|Discontinued)/g)||[])],
  btn:[...document.querySelectorAll('button')].map(b=>b.innerText.trim())
      .filter(t=>/add to (bag|cart)|sold out|out of stock|notify me|unavailable/i.test(t)).slice(0,3),
  body:/(no longer available|page (you're|you are) looking for|not found|out of stock|isn't available)/i
      .exec(document.body.innerText)?.[0]||''})"""


def load():
    try:
        return json.load(open(OUT))
    except FileNotFoundError:
        return {"note": "Written by tools/browser_checks.py. See app/links.py.", "links": {}}


def due(show_all=False):
    cat = json.load(open(CATALOG))
    done = load()["links"]
    today = datetime.date.today()
    rows = []
    for it in cat["items"]:
        for tier, u in (it.get("shop_links") or {}).items():
            if not u:
                continue
            rec = done.get(u)
            fresh = rec and (today - datetime.date.fromisoformat(rec["checked"][:10])).days < RECHECK_AFTER
            host = urlparse(u).netloc.lower()
            if show_all or (host in WALLED and not fresh):
                rows.append((host not in WALLED, host, it["id"], tier, it["name"], u))
    rows.sort()
    return rows


def record(path):
    data = load()
    today = datetime.date.today().isoformat()
    n = 0
    for r in json.load(open(path)):
        if r.get("status") not in ("ok", "dead"):
            continue
        data["links"][r["url"]] = {"status": r["status"], "note": r.get("note", ""), "checked": r.get("checked", today)}
        n += 1
    data["links"] = dict(sorted(data["links"].items()))
    json.dump(data, open(OUT, "w"), indent=1, ensure_ascii=False)
    print(f"recorded {n} results -> {OUT}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "record":
        record(sys.argv[2])
    else:
        rows = due("--all" in sys.argv)
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else len(rows)
        for _, host, pid, tier, name, u in rows[:lim]:
            print(f"{pid}\t{tier}\t{host}\t{name}\t{u}")
        print(f"{len(rows)} due", file=sys.stderr)
