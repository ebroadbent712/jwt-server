# Just Wear This server

One Render web service for justwearthis.co:

| Address | What it does |
|---|---|
| `/` and everything in `site/` | The public website |
| `/s/<piece>-<tier>` | Smart shop links. Live store page if it works; otherwise another live price for the same piece; then the store's own search for that kind of piece; then `/still-looking/` |
| `/p/<id>` | A family's published outfit page (not indexed by search engines) |
| `/q/<id>` | A photographer's published questionnaire |
| `/mcp/<key>` | The publish connector a photographer adds to Claude (tools: `publish_plan`, `publish_questionnaire`, `list_my_pages`) |
| `/admin` | Admin page (asks for the admin password): make a connector link for a buyer, see all links, open the link report |
| `/admin/keys?token=…` | Same list as JSON; `POST name=…&email=…` makes a new one |
| `/admin/links?token=…` | Shop link health report; `POST` runs a check now |
| `/start/` | The family version: questions, then pay $19 (or a beta code), then the plan |
| `/o/<order>` | A family's order: "styling your family" while it builds, then straight to her plan |
| `/o/<order>/swap` | Swap a piece, as often as she likes until photo day (same plan link) |
| `/api/stripe/webhook` | Stripe tells the server a payment went through |
| `/healthz` | Health check for Render |

The nightly link check runs inside the service at 3:15am Central. A link only counts as dead after two failed checks in
a row; stores that wall off automated visits (Target, H&M, Lulus and a few others) are marked "not checkable", never dead.

## Pieces

- `engine/` is a copy of the just-wear-this skill (scripts, library, fonts). Pages are built with the same code the
  plugin uses. Refresh it when the library changes: `tools/sync.sh`.
- `site/` is the website (copied from the JWT workspace).
- `data/` (on Render: the 1 GB disk at `/var/data`) holds connector keys, published pages and link health.

## Deploy (Render)

1. New → Blueprint → pick this repo. Render reads `render.yaml` (Starter web service + 1 GB disk).
2. Set `ADMIN_TOKEN` in the service's Environment tab (any long random phrase; never share it).
3. Custom domains: add `justwearthis.co` and `www.justwearthis.co`, then point GoDaddy DNS at Render.

## Run locally

```
pip install -r requirements.txt
DATA_DIR=./data ADMIN_TOKEN=dev LINK_CHECK=off uvicorn app.main:app --port 8000
```

## Family version settings (Render → Environment)

| Key | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | From console.anthropic.com. Without it, `/start/` says "not quite open yet". `fake` = test mode |
| `ANTHROPIC_MODEL` | Optional; defaults to `claude-sonnet-5-5` |
| `STRIPE_SECRET_KEY` | Stripe → Developers → API keys → Secret key |
| `STRIPE_WEBHOOK_SECRET` | Stripe → Developers → Webhooks → endpoint `https://justwearthis.co/api/stripe/webhook`, event `checkout.session.completed` → Signing secret |
| `RESEND_API_KEY` | From resend.com, after the justwearthis.co domain is verified |
| `MAIL_FROM` | Optional; defaults to `Just Wear This <hello@justwearthis.co>` |
| `MAIL_REPLY_TO` | Optional; where replies to plan emails go |
| `ALERT_EMAIL` | Where a failed build is reported |

Beta codes (one use each) are made on `/admin`.
