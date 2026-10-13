"""Emails for the family version, sent through Resend. With no RESEND_API_KEY they're skipped (and logged)."""
import html
import httpx

from . import config


def _send(to, subject, body_html, text):
    if not config.RESEND_API_KEY or not to:
        print(f"[mail skipped] to={to} subject={subject}")
        return False
    payload = {"from": config.MAIL_FROM, "to": [to], "subject": subject, "html": body_html, "text": text}
    if config.MAIL_REPLY_TO:
        payload["reply_to"] = config.MAIL_REPLY_TO
    try:
        r = httpx.post("https://api.resend.com/emails", timeout=20, json=payload,
                       headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"})
        if r.status_code >= 300:
            print(f"[mail failed] {r.status_code} {r.text[:200]}")
            return False
        return True
    except httpx.HTTPError as e:
        print(f"[mail failed] {e}")
        return False


def _wrap(inner):
    return f"""<div style="font-family:Helvetica,Arial,sans-serif;font-size:16px;line-height:1.55;color:#121212;max-width:520px;margin:0 auto;padding:24px">
<div style="font-weight:700;letter-spacing:.02em;text-transform:uppercase;border-bottom:1px solid #121212;padding-bottom:10px;margin-bottom:20px">Just Wear This.</div>
{inner}</div>"""


def _button(url, label):
    return (f'<p style="margin:26px 0"><a href="{url}" style="background:#121212;color:#fff;text-decoration:none;'
            f'padding:14px 22px;display:inline-block;letter-spacing:.12em;text-transform:uppercase;font-size:13px">{label}</a></p>')


def plan_ready(o):
    a, url = o["answers"], o["url"]
    swap = f"{config.PUBLIC_BASE}/o/{o['id']}/swap"
    name = html.escape(a["who"])
    body = _wrap(f"""<p>Hi {name},</p>
<p>Your family's outfit plan is ready. Everyone's outfit is on one page: tap any piece to shop it, and check things off as they arrive.</p>
{_button(url, "Open my plan")}
<p>Want something different? You can <a href="{swap}" style="color:#121212">swap a piece</a> as many times as you like until photo day.</p>
<p>Save this email so you can find your plan again.</p>
<p>Have fun at your photos!</p>""")
    text = (f"Hi {a['who']},\n\nYour family's outfit plan is ready: {url}\n\nTap any piece to shop it, and check things off "
            f"as they arrive. Want something different? Swap a piece until photo day: {swap}\n\nSave this email so you can find "
            f"your plan again.\n\nJust Wear This")
    return _send(o["email"], "Your family's outfit plan is ready", body, text)


def plan_updated(o):
    a, url = o["answers"], o["url"]
    body = _wrap(f"""<p>Hi {html.escape(a['who'])},</p><p>Your swap is done. Same link as before, with your new piece in place.</p>
{_button(url, "See my plan")}""")
    return _send(o["email"], "Your outfit plan is updated", body, f"Your swap is done. Same link as before: {url}")


def alert_emily(o):
    if not config.ALERT_EMAIL:
        return False
    body = _wrap(f"<p>A family plan didn't build.</p><p>Order {o['id']} ({html.escape(o.get('email', ''))})<br>"
                 f"{html.escape(o.get('error', ''))}</p><p>Open /admin to rebuild it.</p>")
    return _send(config.ALERT_EMAIL, "Just Wear This: a plan didn't build", body, f"Order {o['id']} failed: {o.get('error')}")
