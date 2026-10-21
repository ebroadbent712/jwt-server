"""Takes the background out of a mom's photo of her own piece, in its own process, before the page is built.

The cutout model needs about 300 MB while it runs. Doing it here, one photo at a time and before the page build
starts, keeps the server, the model and the page build from all being in memory together on the small Render
instance. The page engine then gets a photo on white and never loads the model itself.

    python -m app.photo_clean <photo.jpg> <out.png> [left top right bottom]
Writes out.png (the piece on white) and exits 0, or exits 3 when the cutout can't be done well."""
import os, sys

from PIL import Image, ImageOps

ENGINE_SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "engine", "scripts")


def main(src, out, crop=None):
    sys.path.insert(0, ENGINE_SCRIPTS)
    import clean_photo
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.enable_cpu_mem_arena = False  # lower peak memory; speed barely changes for one small photo
    so.intra_op_num_threads = 1
    clean_photo._session = ort.InferenceSession(clean_photo.MODEL, so, providers=["CPUExecutionProvider"])
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    if crop:
        W, H = im.size
        l, t, r, b = crop
        im = im.crop((int(l * W), int(t * H), int(r * W), int(b * H)))
    im.thumbnail((1000, 1000), Image.LANCZOS)  # the size the engine works at
    cut = clean_photo.cutout(im)
    if cut is None:
        return 3
    cut.save(out, "PNG")
    return 0


if __name__ == "__main__":
    a = sys.argv[1:]
    sys.exit(main(a[0], a[1], [float(x) for x in a[2:6]] if len(a) >= 6 else None))
