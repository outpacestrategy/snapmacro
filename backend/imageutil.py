"""Normalize an uploaded photo before sending it to the vision model.

Handles the real-world iPhone cases in one pass:
  - HEIC/HEIF (iPhone default) -> decoded if pillow-heif is available
  - EXIF rotation -> auto-oriented so the model sees it upright
  - Oversized 12MP photos -> downscaled to MAX_EDGE (cheaper + faster, no quality loss
    that matters for food ID)
  - Re-encoded as clean JPEG

Degrades gracefully: if anything can't be decoded, returns the original bytes + mime
so the pipeline still works (the analyzer's error handling covers the rest).
"""
import io

MAX_EDGE = 1024
JPEG_QUALITY = 85

try:
    from PIL import Image, ImageOps
    _PIL = True
except Exception:  # noqa: BLE001
    _PIL = False

try:
    import pillow_heif  # noqa: F401
    pillow_heif.register_heif_opener()
    _HEIC = True
except Exception:  # noqa: BLE001
    _HEIC = False


def normalize(data: bytes, mime: str = "image/jpeg"):
    """Return (jpeg_bytes, 'image/jpeg'). Falls back to (data, mime) if decode fails."""
    if not _PIL:
        return data, mime
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)          # honor EXIF orientation
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        elif im.mode == "L":
            im = im.convert("RGB")
        w, h = im.size
        scale = min(1.0, MAX_EDGE / float(max(w, h)))
        if scale < 1.0:
            im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
        out = io.BytesIO()
        im.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue(), "image/jpeg"
    except Exception:  # noqa: BLE001 - unknown/corrupt format: let analyzer handle it
        return data, mime


def heic_supported() -> bool:
    return _HEIC
