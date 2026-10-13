"""The publish connector (MCP). A photographer adds https://justwearthis.co/mcp/<her key> as a connector in Claude;
the Just Wear This skill then calls these tools to put each family's page at justwearthis.co/p/<id>."""
import json
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.transport_security import TransportSecuritySettings

from . import config, render, store

mcp = FastMCP(
    "Just Wear This",
    instructions=(
        "Publishes Just Wear This client pages. After building a family's outfit plan, call publish_plan with the "
        "plan JSON and the photographer's business details; send the returned link to the photographer. To change a "
        "plan she already sent, call publish_plan again with the same page_id so her client's link keeps working."),
    stateless_http=True,
    json_response=True,
    # Public server on justwearthis.co (access is by each buyer's key), so the localhost-only host check is off.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
mcp.settings.streamable_http_path = "/"


def _key(ctx: Context):
    req = ctx.request_context.request
    key = getattr(req.state, "jwt_key", None) if req is not None else None
    info = store.key_info(key)
    if not info:
        raise ValueError("This connector link isn't active. Ask Just Wear This for a working connector link.")
    return key


def _reply(pid, kind, checks, replaced):
    url = f"{config.PUBLIC_BASE}/{'p' if kind == 'plan' else 'q'}/{pid}"
    return json.dumps({
        "url": url,
        "page_id": pid,
        "updated_existing_page": replaced,
        "checks": checks,
        "next": ("Send this link to the photographer. Keep the page_id: pass it back to publish_plan for any change, "
                 "so the client's link stays the same.") if kind == "plan" else
                ("Send this link to the photographer; she shares the same link with every client."),
    }, ensure_ascii=False)


@mcp.tool()
def publish_plan(plan: dict, business: dict, ctx: Context, page_id: str = "") -> str:
    """Publish (or update) a family's outfit page and get its public link.

    plan: the same plan JSON the skill builds (family_name, title_right, subtitle_right, dress_level, color_story,
      people [{label, items [library ids], note}], headline, story, why_it_works, prep_checklist, owned, palette...).
      Photos (owned-piece photos, hero_photo) can't be sent; owned pieces show with the library picture and label.
    business: the photographer's details: studio_name (required), website, contact_email, contact_phone,
      texting (true if clients may text), recommendations, disclosure.
    page_id: leave empty for a new family. To change a plan already sent, pass the page_id from the first publish.
    """
    key = _key(ctx)
    html, title, checks = render.build_plan_page(plan, business)
    pid = store.save_page(key, html, title, "plan", page_id or None)
    return _reply(pid, "plan", checks, bool(page_id))


@mcp.tool()
def publish_questionnaire(business: dict, ctx: Context, page_id: str = "") -> str:
    """Publish (or update) the photographer's client questionnaire page: one link she sends to every client.

    business: studio_name (required), contact_email, contact_phone, texting.
    page_id: pass the earlier page_id to update her existing questionnaire instead of making a new link.
    """
    key = _key(ctx)
    html, title, checks = render.build_questionnaire(business)
    pid = store.save_page(key, html, title, "questionnaire", page_id or None)
    return _reply(pid, "questionnaire", checks, bool(page_id))


@mcp.tool()
def list_my_pages(ctx: Context) -> str:
    """List the pages this photographer has published (newest first), with their links and page_ids."""
    key = _key(ctx)
    out = [{"title": m.get("title"), "page_id": m["id"], "updated": m.get("updated"),
            "url": f"{config.PUBLIC_BASE}/{'p' if m.get('kind') == 'plan' else 'q'}/{m['id']}"} for m in store.pages_for(key)[:50]]
    return json.dumps(out, ensure_ascii=False)
