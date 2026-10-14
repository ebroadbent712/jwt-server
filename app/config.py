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
ORDERS = os.path.join(DATA, "orders")
THUMBS = os.path.join(DATA, "thumbs")
CODES_FILE = os.path.join(DATA, "codes.json")

PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "https://justwearthis.co").rstrip("/")
# Set in the Render dashboard (never in the code): protects /admin.
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
# Nightly link check time, US Central.
CHECK_HOUR = int(os.environ.get("LINK_CHECK_HOUR", "3"))
CHECK_ENABLED = os.environ.get("LINK_CHECK", "on") != "off"

# ---- family version (all set in the Render dashboard, never in the code) ----
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")      # "fake" = test mode, no API calls
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
PRICE_CENTS = int(os.environ.get("PRICE_CENTS", "1900"))
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Just Wear This <hello@justwearthis.co>")
MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "")              # shown on family plan pages                 # where failed builds are reported

for d in (DATA, PAGES, LOGOS, ORDERS, THUMBS):
    os.makedirs(d, exist_ok=True)
