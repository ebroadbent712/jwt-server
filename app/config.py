"""Paths and settings shared by the whole server."""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine")          # copy of the just-wear-this skill (scripts, library, fonts)
SITE = os.path.join(ROOT, "site")              # the public website (index.html, img/, still-looking/ ...)
CATALOG = os.path.join(ENGINE, "library", "catalog.json")

# Render mounts a persistent disk here (see render.yaml). Locally it falls back to ./data.
DATA = os.environ.get("DATA_DIR") or os.path.join(ROOT, "data")
PAGES = os.path.join(DATA, "pages")
LOGOS = os.path.join(DATA, "logos")
KEYS_FILE = os.path.join(DATA, "keys.json")
HEALTH_FILE = os.path.join(DATA, "link_health.json")

PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://justwearthis.co").rstrip("/")
# Set in the Render dashboard (never in the code): protects /admin.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
# Nightly link check time, US Central.
CHECK_HOUR = int(os.environ.get("LINK_CHECK_HOUR", "3"))
CHECK_ENABLED = os.environ.get("LINK_CHECK", "on") != "off"

for d in (DATA, PAGES, LOGOS):
    os.makedirs(d, exist_ok=True)
