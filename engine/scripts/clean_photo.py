"""Take the background out of a client's phone photo so their piece sits on the board like a flat lay.

Uses a small bundled model (assets/models/u2netp.onnx, about 4.6 MB) run with onnxruntime.
If onnxruntime isn't installed it is installed once (about 30 seconds). If anything fails, or the
result looks wrong, cutout() returns None and the board falls back to the framed photo."""
import os
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(os.path.dirname(HERE), "assets", "models", "u2netp.onnx")
_session = None
_failed = False


def _ort():
    try:
        import onnxruntime
        return onnxruntime
    except ImportError:
        pass
    print("Cleaning up the photo background (one-time setup, about 30 seconds)...", flush=True)
    for extra in ([], ["--break-system-packages"]):
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "onnxruntime", *extra],
                               capture_output=True, timeout=180)
            if r.returncode == 0:
                import importlib
                importlib.invalidate_caches()
                import onnxruntime
                return onnxruntime
        except Exception:
            pass
    return None


def _get_session():
    global _session, _failed
    if _session is not None or _failed:
        return _session
    ort = _ort() if os.path.isfile(MODEL) else None
    if ort is None:
        _failed = True
        return None
    try:
        _session = ort.InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    except Exception:
        _failed = True
    return _session


def _mask(sess, im):
    small = im.convert("RGB").resize((320, 320), Image.LANCZOS)
    x = np.asarray(small).astype(np.float32) / 255.0
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
    out = (out - out.min()) / max(out.max() - out.min(), 1e-6)
    return Image.fromarray((out * 255).astype(np.uint8)).resize(im.size, Image.LANCZOS)


def cutout(im):
    """The piece on pure white, trimmed with a little margin, or None if it can't be done well."""
    sess = _get_session()
    if sess is None:
        return None
    try:
        m = _mask(sess, im)
    except Exception:
        return None
    a = np.asarray(m).astype(np.float32) / 255.0
    from scipy import ndimage
    fg = a > 0.5
    lab, n = ndimage.label(fg)
    if n == 0:
        return None
    sizes = ndimage.sum(fg, lab, range(1, n + 1))
    fg = ndimage.binary_fill_holes(lab == (np.argmax(sizes) + 1))  # the main piece only, no stray bits
    share = fg.mean()
    if not 0.08 < share < 0.92:  # found almost nothing, or couldn't tell the piece from the background
        return None
    ys, xs = np.nonzero(fg)
    box_share = ((ys.max() - ys.min() + 1) * (xs.max() - xs.min() + 1)) / fg.size
    if share / box_share < 0.35:  # scattered, not one garment
        return None
    unsure = ((a > 0.15) & (a < 0.85)).sum() / max(fg.sum(), 1)
    if unsure > 0.12:  # too much the model couldn't decide on (ghosted edges): use the framed photo instead
        return None
    # hard edge from the main shape, then a slight feather
    m = Image.fromarray((fg * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2))
    white = Image.new("RGB", im.size, "white")
    white.paste(im.convert("RGB"), mask=m)
    pad = int(0.03 * max(im.size))
    l, t = max(0, xs.min() - pad), max(0, ys.min() - pad)
    r, b = min(im.width, xs.max() + pad), min(im.height, ys.max() + pad)
    return white.crop((l, t, r, b))
