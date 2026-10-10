"""Apparence : thème, logo et vignettes. Les fichiers choisis restent dans data/brand."""

from io import BytesIO
from pathlib import Path

from django.conf import settings
from PIL import Image, ImageOps

from .choices import CATEGORY_CODES

THEMES = (
    ("violet", "Violet", "Le thème actuel, fond noir et violet."),
    ("nuit", "Nuit", "Noir et gris, sans violet."),
    ("clair", "Clair", "Fond clair pour lire plus facilement."),
)

CATEGORY_LABELS = {
    "trio_mfm": "Trio MFM",
    "trio_fmf": "Trio FMF",
    "echangisme": "Échangisme",
    "melangisme": "Mélangisme",
    "groupe": "Rencontres en groupe",
    "gangbang": "Gangbang",
    "bdsm": "BDSM",
    "fetichismes": "Fétichismes",
    "voyeurisme": "Voyeurisme et exhibitionnisme",
    "jeux_role": "Jeux de rôle et scénarios",
    "toutes": "Toutes",
}


def theme_choice():
    from .models import SiteSetting

    value = SiteSetting.get("theme", "violet")
    return value if value in {code for code, _label, _help in THEMES} else "violet"


def brand_root():
    root = Path(settings.BASE_DIR) / "data" / "brand"
    root.mkdir(parents=True, exist_ok=True)
    return root


def brand_path(asset):
    parts = [part for part in str(asset).replace("\\", "/").split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return None
    relative = Path(*parts)
    custom_root = (Path(settings.BASE_DIR) / "data" / "brand").resolve()
    custom = (custom_root / relative).resolve()
    if (custom == custom_root or custom_root in custom.parents) and custom.is_file():
        return custom
    static_root = (Path(settings.BASE_DIR) / "static").resolve()
    static = (static_root / relative).resolve()
    if (static == static_root or static_root in static.parents) and static.is_file():
        return static
    return None


def brand_stamp():
    latest = 0
    roots = (
        Path(settings.BASE_DIR) / "data" / "brand",
        Path(settings.BASE_DIR) / "static" / "categories",
        Path(settings.BASE_DIR) / "static" / "icons",
    )
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                latest = max(latest, int(path.stat().st_mtime))
    return latest


def _png(uploaded, size):
    if getattr(uploaded, "size", 0) and uploaded.size > 8_000_000:
        raise ValueError("Image trop lourde (8 Mo maximum).")
    raw = uploaded.read(16) if hasattr(uploaded, "read") else b""
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
    if raw.startswith(b"%PDF") or raw.startswith(b"<") or raw.startswith(b"<?xml"):
        raise ValueError("Utilisez une image PNG, JPEG ou WebP. Les PDF et SVG ne sont pas acceptés.")
    try:
        img = ImageOps.exif_transpose(Image.open(uploaded))
        img.load()
    except Exception as exc:
        raise ValueError("Cette image est illisible.") from exc
    img = img.convert("RGBA")
    img = ImageOps.fit(img, (size, size), Image.Resampling.LANCZOS)
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def save_png(relative, uploaded, size):
    payload = _png(uploaded, size)
    path = brand_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def remove_custom(relative):
    path = brand_root() / relative
    if path.is_file():
        path.unlink()


def category_rows():
    rows = []
    custom_root = Path(settings.BASE_DIR) / "data" / "brand" / "categories"
    for code in ("toutes", *CATEGORY_CODES):
        rows.append({
            "code": code,
            "label": CATEGORY_LABELS.get(code, code),
            "custom": (custom_root / f"{code}.png").is_file(),
        })
    return rows
