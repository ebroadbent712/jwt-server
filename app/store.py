"""Tiny file store: connector keys, published pages and logos, all on the persistent disk."""
import json, os, re, secrets, threading, time
from . import config

_lock = threading.Lock()


def _read(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


# ---------- connector keys (one per buyer) ----------
def keys():
    return _read(config.KEYS_FILE, {})


def key_info(key):
    k = keys().get(key or "")
    return k if k and k.get("active", True) else None


def create_key(name, email=""):
    with _lock:
        ks = keys()
        key = "jwt_" + secrets.token_urlsafe(18)
        ks[key] = {"name": name, "email": email, "created": time.strftime("%Y-%m-%d"), "active": True}
        _write(config.KEYS_FILE, ks)
    return key


def set_key_active(key, active):
    with _lock:
        ks = keys()
        if key in ks:
            ks[key]["active"] = bool(active)
            _write(config.KEYS_FILE, ks)
            return True
    return False


# ---------- published pages ----------
PAGE_ID = re.compile(r"^[a-z0-9]{6,24}$")


def _meta_path(pid):
    return os.path.join(config.PAGES, pid + ".json")


def _html_path(pid):
    return os.path.join(config.PAGES, pid + ".html")


def page_meta(pid):
    if not PAGE_ID.match(pid or ""):
        return None
    return _read(_meta_path(pid), None)


def page_html_path(pid):
    p = _html_path(pid)
    return p if PAGE_ID.match(pid or "") and os.path.exists(p) else None


def save_page(key, html, title, kind, pid=None):
    """New page, or replace one this key already owns (so the link the client has keeps working)."""
    with _lock:
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if pid:
            meta = page_meta(pid)
            if not meta or meta.get("key") != key:
                raise PermissionError("That page wasn't published with this connector, so it can't be replaced.")
        else:
            pid = secrets.token_hex(5)  # 10 chars, unguessable enough for a family's outfit page
            meta = {"key": key, "created": now}
        meta.update(title=title, kind=kind, updated=now, versions=meta.get("versions", 0) + 1)
        with open(_html_path(pid), "w") as f:
            f.write(html)
        _write(_meta_path(pid), meta)
    return pid


def pages_for(key):
    out = []
    for fn in os.listdir(config.PAGES):
        if fn.endswith(".json"):
            m = _read(os.path.join(config.PAGES, fn), {})
            if m.get("key") == key:
                out.append(dict(m, id=fn[:-5]))
    return sorted(out, key=lambda m: m.get("updated", ""), reverse=True)


# ---------- logos ----------
def logo_path(key):
    for ext in ("png", "jpg"):
        p = os.path.join(config.LOGOS, f"{_safe(key)}.{ext}")
        if os.path.exists(p):
            return p
    return None


def _safe(key):
    return re.sub(r"[^A-Za-z0-9_-]", "", key)


def save_logo(key, data, ext):
    for old in ("png", "jpg"):
        p = os.path.join(config.LOGOS, f"{_safe(key)}.{old}")
        if os.path.exists(p):
            os.remove(p)
    p = os.path.join(config.LOGOS, f"{_safe(key)}.{ext}")
    with open(p, "wb") as f:
        f.write(data)
    return p
