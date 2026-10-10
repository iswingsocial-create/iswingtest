"""Fournisseurs d'images et traitements de visage appliqués au fichier."""

import os
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


class ImageBlocked(RuntimeError):
    pass


def prepare_jpeg(raw):
    img = ImageOps.exif_transpose(Image.open(BytesIO(raw))).convert("RGB")
    img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    out = BytesIO()
    img.save(out, format="JPEG", quality=82, optimize=True)
    return out.getvalue()


def apply_face(raw, mode):
    img = Image.open(BytesIO(prepare_jpeg(raw))).convert("RGB")
    if mode == "blurred":
        blurred = img.filter(ImageFilter.GaussianBlur(radius=28))
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        width, height = img.size
        draw.ellipse((width * 0.18, height * 0.08, width * 0.82, height * 0.62), fill=255)
        img = Image.composite(blurred, img, mask)
    elif mode == "emoji":
        draw = ImageDraw.Draw(img)
        width, height = img.size
        box = (width * 0.22, height * 0.1, width * 0.78, height * 0.58)
        draw.ellipse(box, fill=(255, 214, 64))
        draw.ellipse((width * 0.36, height * 0.24, width * 0.44, height * 0.32), fill=(40, 30, 20))
        draw.ellipse((width * 0.56, height * 0.24, width * 0.64, height * 0.32), fill=(40, 30, 20))
        draw.arc((width * 0.38, height * 0.3, width * 0.62, height * 0.48), 20, 160, fill=(40, 30, 20), width=max(4, width // 80))
    elif mode != "visible":
        raise ImageBlocked("mode de visage inconnu")
    img = ImageEnhance.Color(img).enhance(1.0)
    out = BytesIO()
    img.save(out, format="JPEG", quality=82, optimize=True)
    return out.getvalue()


class DirectoryProvider:
    name = "directory"

    def __init__(self, root):
        self.root = Path(root) if root else None

    def available(self):
        if self.root and self.root.is_dir():
            return True, str(self.root)
        return False, "dossier d'images absent"

    def generate(self, external_key, slot, prompt, reference):
        path = self.root / external_key / f"{slot}.jpg"
        if not path.is_file():
            path = self.root / f"{external_key}_{slot}.jpg"
        if not path.is_file():
            raise ImageBlocked(f"image source absente : {external_key}/{slot}")
        return apply_face(path.read_bytes(), reference["face"])


class OpenAIProvider:
    name = "openai"

    def available(self):
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            return True, "openai"
        return False, "OPENAI_API_KEY absente"

    def generate(self, external_key, slot, prompt, reference):
        raise ImageBlocked("fournisseur OpenAI non appelé dans cet environnement")


class NoneProvider:
    name = "none"

    def available(self):
        return False, "aucun fournisseur d'images configuré"

    def generate(self, external_key, slot, prompt, reference):
        raise ImageBlocked("génération d'images indisponible")


def provider_from_settings(image_dir=""):
    kind = os.environ.get("ISWING_IMAGE_PROVIDER", "directory" if image_dir else "none")
    if image_dir:
        return DirectoryProvider(image_dir)
    if kind == "openai":
        return OpenAIProvider()
    if kind == "directory" and os.environ.get("ISWING_IMAGE_DIR"):
        return DirectoryProvider(os.environ["ISWING_IMAGE_DIR"])
    return NoneProvider()
