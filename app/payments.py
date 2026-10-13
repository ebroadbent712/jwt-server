"""Stripe Checkout for the $19 family plan (plain HTTPS, no SDK) and single-use beta codes."""
import hashlib, hmac, json, re, secrets, threading, time

import httpx

from . import config, store

_lock = threading.Lock()


class PaymentError(Exception):
    pass


def checkout_url(order):
    """Makes a Stripe Checkout Session for this order and returns its URL."""
    if not config.STRIPE_SECRET_KEY:
        raise PaymentError("Checkout isn't switched on yet.")
    base = config.PUBLIC_BASE
    data = {
        "mode": "payment",
        "success_url": f"{base}/o/{order['id']}?paid=1",
        "cancel_url": f"{base}/start/?back=1",
        "client_reference_id": order["id"],
        "customer_email": order["email"],
        "metadata[order]": order["id"],
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "usd",
        "line_items[0][price_data][unit_amount]": str(config.PRICE_CENTS),
        "line_items[0][price_data][product_data][name]": "Family outfit plan",
        "line_items[0][price_data][product_data][description]": "One outfit plan for your whole family, with swaps until photo day.",
        "allow_promotion_codes": "true",
    }
    r = httpx.post("https://api.stripe.com/v1/checkout/sessions", data=data, timeout=20,
                   auth=(config.STRIPE_SECRET_KEY, ""))
    if r.status_code >= 300:
        raise PaymentError(f"Stripe {r.status_code}: {r.text[:200]}")
    s = r.json()
    return s["url"], s["id"]


def verify_webhook(payload: bytes, header: str, tolerance=300):
    """Checks Stripe's signature (t=...,v1=...) the same way the official library does."""
    if not config.STRIPE_WEBHOOK_SECRET:
        raise PaymentError("STRIPE_WEBHOOK_SECRET isn't set.")
    parts = dict(p.split("=", 1) for p in (header or "").split(",") if "=" in p)
    sigs = [v for k, v in (p.split("=", 1) for p in (header or "").split(",") if "=" in p) if k == "v1"]
    ts = parts.get("t", "")
    if not ts or not sigs:
        raise PaymentError("Missing signature.")
    expected = hmac.new(config.STRIPE_WEBHOOK_SECRET.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in sigs):
        raise PaymentError("Bad signature.")
    if abs(time.time() - int(ts)) > tolerance:
        raise PaymentError("Signature too old.")
    return json.loads(payload)


# ---------- beta codes (single use, made on the admin page) ----------
def codes():
    return store._read(config.CODES_FILE, {})


def make_codes(n, note=""):
    with _lock:
        cs = codes()
        out = []
        for _ in range(max(1, min(int(n), 50))):
            c = "BETA-" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(5))
            cs[c] = {"note": note, "made": time.strftime("%Y-%m-%d"), "used_by": None}
            out.append(c)
        store._write(config.CODES_FILE, cs)
    return out


def norm(code):
    return re.sub(r"[^A-Z0-9-]", "", (code or "").upper())


def code_ok(code):
    c = codes().get(norm(code))
    return bool(c) and not c.get("used_by")


def use_code(code, order_id):
    with _lock:
        cs = codes()
        c = cs.get(norm(code))
        if not c or c.get("used_by"):
            return False
        c["used_by"] = order_id
        c["used"] = time.strftime("%Y-%m-%dT%H:%M")
        store._write(config.CODES_FILE, cs)
        return True
