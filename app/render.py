"""Builds the client pages on the server with the same engine the plugin uses, so Claude only has to send the plan."""
import json, os, re, subprocess, sys, tempfile, threading
from . import config

_build_lock = threading.Lock()  # one build at a time; the Starter instance has half a CPU
SCRIPTS = os.path.join(config.ENGINE, "scripts")

BUSINESS_KEYS = ("studio_name", "website", "contact_email", "contact_phone", "texting", "recommendations", "disclosure")


class BuildError(Exception):
    pass


def _business(b):
    b = b or {}
    out = {k: b[k] for k in BUSINESS_KEYS if k in b and b[k] not in (None, "")}
    if "texting" in out:
        out["texting"] = bool(out["texting"])
    return out


def _crop_ok(c):
    return (isinstance(c, list) and len(c) == 4 and all(isinstance(x, (int, float)) and 0 <= x <= 1 for x in c)
            and c[0] < c[2] and c[1] < c[3])


def _clean_plan(plan, business, photos=None):
    if not isinstance(plan, dict) or not plan.get("family_name") or not plan.get("people"):
        raise BuildError("The plan needs at least family_name and people (each with a label and items).")
    plan = json.loads(json.dumps(plan))  # private copy
    # Files on the photographer's side can't reach the server: owned pieces keep their label and the library
    # picture stands in; a session photo is skipped. Photos a mom uploaded on /start/ are on the server's disk
    # (photos = photo id -> file) and do go on her board.
    notes = []
    for o in plan.get("owned", []):
        if isinstance(o, dict) and photos and o.get("photo") in photos:
            o["photo"] = photos[o["photo"]]
            if "crop" in o and not _crop_ok(o["crop"]):
                o.pop("crop")
        elif isinstance(o, dict) and o.pop("photo", None):
            o.pop("crop", None)
            notes.append(f"{o.get('label') or o.get('id')}: shown with the library picture (photos can't be sent to the page server yet).")
    if plan.pop("hero_photo", None):
        notes.append("The session photo isn't on the page (photos can't be sent to the page server yet).")
    plan["settings_override"] = dict(plan.get("settings_override") or {}, **_business(business))
    return plan, notes


def _run(args, cwd):
    p = subprocess.run([sys.executable] + args, cwd=cwd, capture_output=True, text=True, timeout=180)
    out = (p.stdout or "") + (p.stderr or "")
    if p.returncode != 0:
        msg = out.strip().splitlines()[-1] if out.strip() else "unknown error"
        raise BuildError(msg)
    return out


def build_plan_page(plan, business, photos=None):
    """Returns (html, title, checks) for the client's outfit page."""
    plan, notes = _clean_plan(plan, business, photos)
    with _build_lock, tempfile.TemporaryDirectory() as tmp:
        pf = os.path.join(tmp, "plan.json")
        json.dump(plan, open(pf, "w"))
        out = _run([os.path.join(SCRIPTS, "build_experience.py"), pf, "--out", tmp], tmp)
        files = [f for f in os.listdir(tmp) if f.endswith("-plan.html")]
        if not files:
            raise BuildError("The page didn't build: " + out.strip()[-300:])
        html = open(os.path.join(tmp, files[0])).read()
    checks = [l.strip() for l in out.splitlines() if l.startswith("CHECK")] + notes
    return html, f"{plan['family_name']} Outfit Plan", checks


def build_questionnaire(business):
    b = _business(business)
    if not b.get("studio_name"):
        raise BuildError("studio_name is missing: ask the photographer for their business details first.")
    with _build_lock, tempfile.TemporaryDirectory() as tmp:
        of = os.path.join(tmp, "override.json")
        json.dump(b, open(of, "w"))
        out = _run([os.path.join(SCRIPTS, "build_questionnaire.py"), "--out", tmp, "--override", of], tmp)
        files = [f for f in os.listdir(tmp) if f.endswith("-questionnaire.html")]
        if not files:
            raise BuildError("The questionnaire didn't build: " + out.strip()[-300:])
        html = open(os.path.join(tmp, files[0])).read()
    checks = [l.strip() for l in out.splitlines() if re.match(r"^(CHECK|Note|WARNING)", l)]
    return html, "Outfit Questions", checks
