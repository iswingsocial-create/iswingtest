"""Visuels publics de la landing. Le fichier est recompressé, sans métadonnées."""

import io
from pathlib import Path

from PIL import Image, ImageOps

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 500_000


class LandingImageError(ValueError):
    pass


def prepare_landing_image(uploaded, max_w, max_h):
    name = getattr(uploaded, "name", "") or ""
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise LandingImageError("Utilisez un fichier JPG ou WebP.")
    raw = uploaded.read()
    if not raw:
        raise LandingImageError("Le fichier est vide.")
    if len(raw) > 8_000_000:
        raise LandingImageError("Le fichier dépasse 8 Mo. Choisissez une image plus légère.")
    try:
        probe = Image.open(io.BytesIO(raw))
        probe.verify()
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:
        raise LandingImageError("Cette image ne peut pas être lue. Utilisez un JPG ou un WebP.") from exc
    if img.format not in {"JPEG", "PNG", "WEBP"}:
        raise LandingImageError("Utilisez un fichier JPG ou WebP.")
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    img.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
    data = _encode(img)
    while data and len(data) > MAX_BYTES and min(img.size) > 160:
        img = img.resize(
            (max(1, int(img.width * 0.85)), max(1, int(img.height * 0.85))),
            Image.Resampling.LANCZOS,
        )
        data = _encode(img)
    if not data or len(data) > MAX_BYTES:
        raise LandingImageError("L'image reste trop lourde après compression (500 Ko).")
    return data


def _encode(img):
    quality = 82
    best = None
    frame = img.convert("RGB")
    while quality >= 40:
        buf = io.BytesIO()
        frame.save(buf, format="WEBP", quality=quality, method=6)
        best = buf.getvalue()
        if len(best) <= MAX_BYTES:
            return best
        quality -= 10
    return best
