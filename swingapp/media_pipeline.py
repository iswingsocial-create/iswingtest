"""Photos, vidéos et fichiers temporaires. Le fichier original n'est jamais publié."""

import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.utils import timezone
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .models import MediaUpload, Photo, SiteSetting

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None


class MediaError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".avif", ".tif", ".tiff", ".bmp", ".gif"}
REJECT_EXT = {".svg", ".pdf", ".html", ".htm", ".xml", ".zip", ".exe", ".txt"}
VIDEO_FORMATS = {
    "mov", "mp4", "m4a", "3gp", "3g2", "mj2", "m4v",
    "matroska", "webm", "avi", "mpeg", "mpegvideo", "mpegts", "asf",
}


def limit_int(key, default):
    row = SiteSetting.objects.filter(key=key).first()
    if row is None or str(row.value).strip() == "":
        return int(default)
    try:
        return int(str(row.value).strip())
    except ValueError:
        return int(default)


def video_max_bytes():
    return limit_int("video_max_bytes", 2_000_000_000)


def video_max_seconds():
    return limit_int("video_max_seconds", 600)


def photo_max_bytes():
    return limit_int("photo_max_bytes", 50_000_000)


def photo_max_edge():
    return limit_int("photo_max_edge", 2560)


def member_quota_bytes():
    return limit_int("member_media_bytes", 0)


def parallel_conversions():
    return max(1, limit_int("video_parallel", 1))


def _incoming():
    root = Path(settings.PRIVATE_MEDIA_ROOT) / "incoming"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _ffmpeg():
    binary = shutil.which("ffmpeg")
    if not binary:
        raise MediaError("ffmpeg", "FFmpeg est absent du serveur. La vidéo n'a pas été publiée.")
    return binary


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def probe_media(path):
    """Lit le conteneur réel. L'extension du nom de fichier n'est pas une preuve."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        proc = _run(
            [ffprobe, "-v", "error", "-show_format", "-show_streams", "-of", "json", path],
            60,
        )
        if proc.returncode == 0 and proc.stdout:
            import json

            try:
                data = json.loads(proc.stdout.decode("utf-8", "replace"))
            except json.JSONDecodeError:
                data = None
            if data:
                return _probe_from_json(data, proc.stderr.decode("utf-8", "replace"))
        err = (proc.stderr or b"").decode("utf-8", "replace")
        if _protected(err):
            raise MediaError("protected", "Le fichier est protégé ou chiffré. Il ne peut pas être converti.")
        if _damaged(err):
            raise MediaError("damaged", "Le fichier semble endommagé ou incomplet.")
    proc = _run([_ffmpeg(), "-hide_banner", "-i", path], 60)
    text = (proc.stderr or b"").decode("utf-8", "replace")
    if _protected(text):
        raise MediaError("protected", "Le fichier est protégé ou chiffré. Il ne peut pas être converti.")
    if _damaged(text) or "Invalid data found" in text:
        raise MediaError("damaged", "Le fichier semble endommagé ou incomplet.")
    return _probe_from_ffmpeg_text(text)


def _protected(text):
    low = text.lower()
    return "drm" in low or "encryption" in low or "encrypted" in low or "cenc" in low


def _damaged(text):
    low = text.lower()
    return any(part in low for part in ("moov atom not found", "invalid data", "end of file", "truncated", "invalid nal"))


def _probe_from_json(data, err):
    if _protected(err):
        raise MediaError("protected", "Le fichier est protégé ou chiffré. Il ne peut pas être converti.")
    fmt = (data.get("format") or {})
    names = {part.strip() for part in (fmt.get("format_name") or "").split(",") if part.strip()}
    video = None
    audio = False
    for stream in data.get("streams") or []:
        if stream.get("codec_type") == "video" and video is None and stream.get("codec_name") not in ("mjpeg", "png"):
            video = stream
        elif stream.get("codec_type") == "audio":
            audio = True
    if video is None:
        for stream in data.get("streams") or []:
            if stream.get("codec_type") == "video":
                video = stream
                break
    if video is None:
        raise MediaError("undecodable", "Aucune piste vidéo décodable n'a été trouvée.")
    width = int(video.get("width") or 0)
    height = int(video.get("height") or 0)
    rotation = 0
    tag = str((video.get("tags") or {}).get("rotate") or "")
    try:
        if tag and abs(int(float(tag))) in (90, 270):
            rotation = abs(int(float(tag)))
    except ValueError:
        rotation = 0
    for side in video.get("side_data_list") or []:
        raw = side.get("rotation")
        if raw is None:
            continue
        try:
            rotation = abs(int(float(raw)))
        except (TypeError, ValueError):
            continue
    if rotation in (90, 270):
        width, height = height, width
    try:
        duration = float(fmt.get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0
    fps = _fps(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    transfer = (video.get("color_transfer") or "").lower()
    return {
        "formats": names,
        "codec": video.get("codec_name") or "",
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "audio": audio,
        "hdr": transfer in ("smpte2084", "arib-std-b67"),
    }


def _fps(raw):
    if not raw or raw == "0/0":
        return 30
    if "/" in str(raw):
        num, den = str(raw).split("/", 1)
        try:
            den = float(den) or 1
            return max(1, float(num) / den)
        except ValueError:
            return 30
    try:
        return float(raw)
    except ValueError:
        return 30


def _probe_from_ffmpeg_text(text):
    if "Input #" not in text or "Video:" not in text:
        raise MediaError("undecodable", "Le fichier n'est pas une vidéo décodable.")
    formats = set()
    match = re.search(r"Input #\d+,\s*([^,]+(?:,\s*[^,]+)*?),\s*from", text)
    if match:
        formats = {part.strip() for part in match.group(1).split(",")}
    duration = 0
    found = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if found:
        duration = int(found.group(1)) * 3600 + int(found.group(2)) * 60 + float(found.group(3))
    video = re.search(r"Video:\s*([^\s,]+).*?(\d{2,5})x(\d{2,5})", text)
    if not video:
        raise MediaError("undecodable", "Aucune piste vidéo décodable n'a été trouvée.")
    width, height = int(video.group(2)), int(video.group(3))
    found_rot = re.search(r"rotation of (-?\d+(?:\.\d+)?)", text)
    if found_rot and abs(int(float(found_rot.group(1)))) in (90, 270):
        width, height = height, width
    fps_match = re.search(r"(\d+(?:\.\d+)?)\s*fps", text)
    fps = float(fps_match.group(1)) if fps_match else 30
    hdr = "smpte2084" in text or "arib-std-b67" in text
    return {
        "formats": formats,
        "codec": video.group(1),
        "width": width,
        "height": height,
        "duration": duration,
        "fps": fps,
        "audio": "Audio:" in text,
        "hdr": hdr,
    }


def validate_video_info(info, size):
    formats = info.get("formats") or set()
    if not formats or not (formats & VIDEO_FORMATS):
        raise MediaError("format", "Le conteneur réel n'est pas un format vidéo pris en charge, même si l'extension semble connue.")
    if size > video_max_bytes():
        raise MediaError("size", "La vidéo dépasse 2 000 000 000 octets, ou la limite configurée.")
    duration = info.get("duration") or 0
    if duration <= 0:
        raise MediaError("duration", "La durée de la vidéo n'a pas pu être lue.")
    if duration > video_max_seconds() + 0.05:
        raise MediaError("duration", "La vidéo dépasse la durée maximale (10 minutes, sauf réglage différent).")
    if not info.get("width") or not info.get("height"):
        raise MediaError("undecodable", "Les dimensions de la vidéo sont illisibles.")
    return info


def fit_1080(width, height):
    if width >= height:
        max_w, max_h = 1920, 1080
    else:
        max_w, max_h = 1080, 1920
    if width and height and abs(width - height) / max(width, height) < 0.02:
        max_w = max_h = 1080
    scale = min(max_w / width, max_h / height, 1)
    return max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2)


def target_video_bitrate(width, height, fps):
    ref = 1920 * 1080
    rate = 6_000_000 * ((width * height) / ref) * ((fps or 30) / 30)
    return int(max(400_000, min(8_000_000, rate)))


def estimate_bytes(width, height, fps, duration):
    bitrate = target_video_bitrate(width, height, fps)
    return int((bitrate + 128_000) * max(duration, 0) / 8)


def _filter_names():
    if getattr(_filter_names, "cache", None) is not None:
        return _filter_names.cache
    try:
        proc = _run([_ffmpeg(), "-hide_banner", "-filters"], 20)
        text = (proc.stdout or b"").decode("utf-8", "replace")
    except Exception:
        text = ""
    _filter_names.cache = set(re.findall(r"\b([a-z0-9_]+)\b", text))
    return _filter_names.cache


def _scale_filter():
    return (
        "scale="
        "w='if(gt(abs(iw-ih),0.02*max(iw,ih)),if(gte(iw,ih),min(1920,iw),min(1080,iw)),min(1080,iw))':"
        "h='if(gt(abs(iw-ih),0.02*max(iw,ih)),if(gte(iw,ih),min(1080,ih),min(1920,ih)),min(1080,ih))':"
        "force_original_aspect_ratio=decrease:force_divisible_by=2,format=yuv420p"
    )


def _vf(info):
    scale = _scale_filter()
    names = _filter_names()
    if info.get("hdr") and "zscale" in names and "tonemap" in names:
        return (
            "zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
            "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv," + scale
        )
    return scale


def convert_video_file(src, dst):
    info = validate_video_info(probe_media(src), os.path.getsize(src))
    out_w, out_h = fit_1080(info["width"], info["height"])
    bitrate = target_video_bitrate(out_w, out_h, info["fps"])
    estimate = estimate_bytes(out_w, out_h, info["fps"], info["duration"])
    timeout = min(3600, int(info["duration"] * 30) + 90)
    extra = ["-an"]
    if info.get("audio"):
        extra = ["-c:a", "aac", "-profile:a", "aac_low", "-b:a", "128k", "-ac", "2", "-ar", "48000"]
    if info.get("hdr"):
        extra += ["-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]
    cmd = [
        _ffmpeg(), "-y", "-i", src,
        "-vf", _vf(info),
        "-c:v", "libx264", "-profile:v", "main", "-level", "4.1", "-pix_fmt", "yuv420p",
        "-preset", "veryfast", "-tag:v", "avc1",
        "-b:v", str(bitrate), "-maxrate", str(min(8_000_000, bitrate)), "-bufsize", str(bitrate * 2),
        "-movflags", "+faststart",
        *extra,
        dst,
    ]
    proc = _run(cmd, timeout)
    if proc.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) < 32:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-400:]
        if _protected(err):
            raise MediaError("protected", "Le fichier est protégé ou chiffré. Il ne peut pas être converti.")
        if _damaged(err):
            raise MediaError("damaged", "Le fichier semble endommagé. La conversion a été arrêtée et rien n'a été publié.")
        raise MediaError("convert", "La conversion a échoué. Le fichier original n'a pas été publié.")
    with open(dst, "rb") as handle:
        head = handle.read(64)
    if b"ftyp" not in head:
        raise MediaError("convert", "Le fichier converti n'est pas un MP4 lisible. Rien n'a été publié.")
    _ensure_faststart(dst)
    info["estimate"] = estimate
    info["output_bytes"] = os.path.getsize(dst)
    info["out_width"] = out_w
    info["out_height"] = out_h
    return info


def poster_from_video(src, duration):
    dest = src + ".poster.jpg"
    ss = "0.2" if duration < 1 else "1"
    proc = _run([_ffmpeg(), "-y", "-ss", ss, "-i", src, "-frames:v", "1", dest], 60)
    if proc.returncode != 0 or not os.path.isfile(dest):
        from .services import poster_for_video

        data = poster_for_video().read()
        return data
    with open(dest, "rb") as handle:
        data = handle.read()
    os.remove(dest)
    return data


def _open_image(uploaded):
    cap = limit_int("photo_max_pixels", 80_000_000)
    Image.MAX_IMAGE_PIXELS = cap
    if hasattr(uploaded, "seek"):
        uploaded.seek(0)
        head = uploaded.read(32)
        uploaded.seek(0)
    else:
        with open(uploaded, "rb") as handle:
            head = handle.read(32)
    lowered = head.lower()
    if head.startswith(b"%PDF") or b"<svg" in lowered or head.startswith(b"<!DOCTYPE") or head.startswith(b"<?xml"):
        raise MediaError("document", "Les PDF, SVG et autres documents ne sont pas acceptés comme photos.")
    try:
        img = Image.open(uploaded)
        img.load()
    except Image.DecompressionBombError as exc:
        raise MediaError("dimensions", "Cette image est trop grande une fois décodée.") from exc
    except Exception as exc:
        raise MediaError("undecodable", "Cette photo est illisible, endommagée, ou son format n'est pas pris en charge sur ce serveur.") from exc
    if getattr(img, "format", "") == "SVG":
        raise MediaError("document", "Les fichiers SVG ne sont pas acceptés comme photos.")
    pixels = (img.width or 0) * (img.height or 0)
    if pixels > cap:
        raise MediaError("dimensions", "Cette image dépasse la taille décodée autorisée.")
    return img


def apply_masks(img, masks):
    if not masks:
        return img.convert("RGB")
    base = img.convert("RGBA")
    width, height = base.size
    for raw in list(masks)[:12]:
        if not isinstance(raw, dict):
            continue
        try:
            x = float(raw.get("x", 0))
            y = float(raw.get("y", 0))
            w = float(raw.get("w", 0.2))
            h = float(raw.get("h", 0.2))
            rotation = float(raw.get("rotation") or 0)
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        box_w = max(8, int(w * width))
        box_h = max(8, int(h * height))
        left = int(x * width)
        top = int(y * height)
        kind = raw.get("type") or "sticker"
        if kind == "blur":
            strength = min(40, max(2, int(float(raw.get("strength") or 12))))
            crop = base.crop((left, top, min(width, left + box_w), min(height, top + box_h)))
            if crop.width < 2 or crop.height < 2:
                continue
            blurred = crop.filter(ImageFilter.GaussianBlur(radius=strength)).convert("RGBA")
            mask = Image.new("L", blurred.size, 0)
            ImageDraw.Draw(mask).ellipse((0, 0, blurred.width - 1, blurred.height - 1), fill=255)
            blurred.putalpha(mask)
            ox, oy = left, top
            if rotation:
                blurred = blurred.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
                ox = left - (blurred.width - box_w) // 2
                oy = top - (blurred.height - box_h) // 2
            _composite(base, blurred, ox, oy)
            continue
        sticker = _sticker_layer(box_w, box_h, raw.get("emoji") or "●")
        ox, oy = left, top
        if rotation:
            sticker = sticker.rotate(-rotation, expand=True, resample=Image.Resampling.BICUBIC)
            ox = left - (sticker.width - box_w) // 2
            oy = top - (sticker.height - box_h) // 2
        _composite(base, sticker, ox, oy)
    return base.convert("RGB")


def _composite(base, layer, ox, oy):
    if ox >= base.width or oy >= base.height or layer.width < 1 or layer.height < 1:
        return
    if ox < 0 or oy < 0:
        layer = layer.crop((max(0, -ox), max(0, -oy), layer.width, layer.height))
        ox, oy = max(0, ox), max(0, oy)
    if ox + layer.width > base.width or oy + layer.height > base.height:
        layer = layer.crop((0, 0, max(0, base.width - ox), max(0, base.height - oy)))
    if layer.width < 1 or layer.height < 1:
        return
    base.alpha_composite(layer, (ox, oy))


def _sticker_layer(box_w, box_h, code):
    glyph = _emoji_sticker(box_w, box_h, code)
    if glyph is not None:
        return glyph
    sticker = Image.new("RGBA", (box_w, box_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sticker)
    code = (code or "●")[:16]
    if code == "happy":
        draw.ellipse((1, 1, box_w - 2, box_h - 2), fill=(255, 214, 40, 255))
        _eyes(draw, box_w, box_h, 0.35)
        draw.arc(
            (box_w * 0.22, box_h * 0.42, box_w * 0.78, box_h * 0.82),
            20, 160, fill=(20, 16, 32, 255), width=max(2, box_w // 16),
        )
    elif code == "devil":
        draw.polygon(
            [(box_w * 0.22, box_h * 0.30), (box_w * 0.32, box_h * 0.02), (box_w * 0.42, box_h * 0.30)],
            fill=(180, 24, 40, 255),
        )
        draw.polygon(
            [(box_w * 0.58, box_h * 0.30), (box_w * 0.68, box_h * 0.02), (box_w * 0.78, box_h * 0.30)],
            fill=(180, 24, 40, 255),
        )
        draw.ellipse((box_w * 0.12, box_h * 0.18, box_w * 0.88, box_h * 0.96), fill=(196, 32, 48, 255))
        _eyes(draw, box_w, box_h, 0.48)
        draw.arc(
            (box_w * 0.28, box_h * 0.55, box_w * 0.72, box_h * 0.86),
            10, 170, fill=(20, 16, 32, 255), width=max(2, box_w // 18),
        )
    elif code == "pineapple":
        draw.polygon([(box_w * 0.50, box_h * 0.02), (box_w * 0.30, box_h * 0.32), (box_w * 0.48, box_h * 0.18)], fill=(36, 140, 52, 255))
        draw.polygon([(box_w * 0.50, box_h * 0.02), (box_w * 0.70, box_h * 0.32), (box_w * 0.52, box_h * 0.18)], fill=(24, 110, 40, 255))
        draw.ellipse((box_w * 0.22, box_h * 0.22, box_w * 0.78, box_h * 0.96), fill=(240, 196, 40, 255))
    else:
        draw.rounded_rectangle((0, 0, box_w - 1, box_h - 1), radius=max(4, box_w // 6), fill=(12, 8, 24, 255))
        draw.text((box_w // 4, box_h // 3), code[:4], fill=(255, 255, 255, 255))
    return sticker


_STICKER_FILES = {
    "happy": "1f60a.png",
    "😊": "1f60a.png",
    "devil": "1f608.png",
    "😈": "1f608.png",
    "pineapple": "1f34d.png",
    "🍍": "1f34d.png",
}


def _emoji_sticker(box_w, box_h, code):
    name = _STICKER_FILES.get((code or "").strip())
    if not name:
        return None
    path = Path(__file__).resolve().parent / "stickers" / name
    if not path.is_file():
        return None
    glyph = Image.open(path).convert("RGBA")
    return glyph.resize((max(8, box_w), max(8, box_h)), Image.Resampling.LANCZOS)


def _eyes(draw, box_w, box_h, top):
    ew, eh = max(2, box_w // 12), max(2, box_h // 10)
    for origin in (0.30, 0.62):
        x = box_w * origin
        y = box_h * top
        draw.ellipse((x, y, x + ew, y + eh), fill=(20, 16, 32, 255))


def prepare_image(uploaded, crop=None, masks=None, confirm_gif=False):
    if hasattr(uploaded, "size") and uploaded.size and uploaded.size > photo_max_bytes():
        raise MediaError("size", "La photo dépasse la limite configurée.")
    name = (getattr(uploaded, "name", "") or "").lower()
    ext = os.path.splitext(name)[1]
    if ext in REJECT_EXT:
        raise MediaError("document", "Les PDF, SVG et autres documents ne sont pas acceptés comme photos.")
    img = _open_image(uploaded)
    animated = bool(getattr(img, "is_animated", False) or getattr(img, "n_frames", 1) > 1)
    if animated and not confirm_gif:
        raise MediaError(
            "animated",
            "Ce GIF est animé. Cochez la confirmation pour conserver l'animation en WebP, ou il ne sera pas enregistré.",
        )
    if animated and confirm_gif:
        return _animated_webp(img, masks, crop)
    img = ImageOps.exif_transpose(img)
    if crop:
        img = _crop(img, crop)
    img = apply_masks(img, masks)
    return _still(img)


def _crop(img, crop):
    try:
        x, y, w, h = (float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3]))
    except (TypeError, ValueError, IndexError):
        return img
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1):
        return img
    width, height = img.size
    box = (int(x * width), int(y * height), int((x + w) * width), int((y + h) * height))
    if box[2] <= box[0] or box[3] <= box[1]:
        return img
    return img.crop(box)


def _still(img):
    rgb = img.convert("RGB")
    edge = photo_max_edge()
    rgb.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    rgb = ImageEnhance.Color(rgb).enhance(1)
    display = _jpeg_bytes(rgb, 84)
    thumb = rgb.copy()
    thumb.thumbnail((limit_int("photo_thumb_edge", 480),) * 2, Image.Resampling.LANCZOS)
    return PreparedImage(display, _jpeg_bytes(thumb, 78), "jpg", rgb.width, rgb.height)


def _jpeg_bytes(img, quality):
    import io

    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _animated_webp(img, masks=None, crop=None):
    import io

    frames = []
    durations = []
    edge = photo_max_edge()
    count = min(getattr(img, "n_frames", 1), 48)
    for index in range(count):
        img.seek(index)
        frame = ImageOps.exif_transpose(img.convert("RGBA"))
        if crop:
            frame = _crop(frame, crop)
        frame.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        if masks:
            frame = apply_masks(frame, masks)
        frames.append(frame.convert("RGBA"))
        durations.append(int(img.info.get("duration") or 100))
    out = io.BytesIO()
    frames[0].save(out, format="WEBP", save_all=True, append_images=frames[1:], duration=durations, loop=0, quality=75)
    thumb = frames[0].convert("RGB")
    thumb.thumbnail((480, 480), Image.Resampling.LANCZOS)
    return PreparedImage(out.getvalue(), _jpeg_bytes(thumb, 78), "webp", frames[0].width, frames[0].height)


class PreparedImage:
    def __init__(self, display, thumb, ext, width, height):
        self.display = display
        self.thumb = thumb
        self.ext = ext
        self.width = width
        self.height = height
        self._pos = 0

    def read(self):
        if self._pos:
            return b""
        self._pos = 1
        return self.display

    def seek(self, pos):
        self._pos = 0 if pos == 0 else 1


def member_usage(profile):
    total = 0
    for photo in profile.photos.all():
        if photo.byte_size:
            total += photo.byte_size
            continue
        for field in (photo.image, photo.video, photo.thumb):
            try:
                if field and field.name:
                    total += field.size
            except Exception:
                continue
    return total


def assert_member_room(profile, extra):
    quota = member_quota_bytes()
    if quota and member_usage(profile) + extra > quota:
        raise MediaError("quota", "Le quota de médias de ce membre est atteint.")


def save_photo_files(photo, prepared, private, approve):
    photo.image.save(f"photo.{prepared.ext}", ContentFile(prepared.display), save=False)
    photo.thumb.save("thumb.jpg", ContentFile(prepared.thumb), save=False)
    photo.byte_size = len(prepared.display) + len(prepared.thumb)
    photo.width = prepared.width
    photo.height = prepared.height
    photo.processing_status = "ready"
    photo.processing_error = ""
    photo.media_type = "photo"
    photo.is_private = private
    photo.moderation_status = "approved" if approve else "pending"
    photo.is_primary = (not private) and photo.moderation_status == "approved" and not photo.profile.photos.filter(
        is_primary=True, is_private=False, media_type="photo"
    ).exclude(pk=photo.pk).exists()
    photo.save()
    return photo


def store_source(upload, suffix):
    token = uuid.uuid4().hex
    path = _incoming() / f"{token}{suffix}"
    with path.open("wb") as handle:
        if hasattr(upload, "chunks"):
            for chunk in upload.chunks():
                handle.write(chunk)
        else:
            data = upload.read() if hasattr(upload, "read") else upload
            handle.write(data)
    return str(path)


def queue_video(profile, source_path, private, original_name="", title=""):
    size = os.path.getsize(source_path)
    if size > video_max_bytes():
        os.remove(source_path)
        raise MediaError("size", "La vidéo dépasse 2 000 000 000 octets, ou la limite configurée.")
    assert_member_room(profile, size)
    photo = Photo(
        profile=profile,
        is_private=private,
        media_type="video",
        position=profile.photos.count(),
        processing_status="checking",
        source_path=source_path,
        byte_size=size,
        is_primary=False,
        moderation_status="pending",
        title=(title or "")[:80],
    )
    from .services import poster_for_video

    poster = poster_for_video()
    photo.image.save("poster.jpg", ContentFile(poster.read()), save=False)
    photo.save()
    enqueue_video(photo.id)
    return photo


def _lock_path(photo_id):
    folder = _incoming() / "locks"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{int(photo_id)}.lock"


def _acquire_lock(photo_id, stale=3 * 3600):
    path = _lock_path(photo_id)
    if path.exists() and time.time() - path.stat().st_mtime > stale:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return None
    os.close(fd)
    return path


def _release_lock(photo_id):
    _lock_path(photo_id).unlink(missing_ok=True)


def recover_stale_conversions():
    recovered = 0
    for photo in Photo.objects.filter(media_type="video", processing_status="converting"):
        path = _lock_path(photo.id)
        stale = (not path.exists()) or (time.time() - path.stat().st_mtime > 3 * 3600)
        if not stale:
            continue
        _release_lock(photo.id)
        Photo.objects.filter(pk=photo.id, processing_status="converting").update(processing_status="pending")
        recovered += 1
    return recovered


def enqueue_video(photo_id):
    if getattr(settings, "MEDIA_PROCESS_EAGER", False):
        process_photo(photo_id)
        return
    busy = Photo.objects.filter(media_type="video", processing_status="converting").count()
    if busy >= parallel_conversions():
        Photo.objects.filter(pk=photo_id, processing_status__in=("checking", "uploading")).update(processing_status="pending")
        return
    threading.Thread(target=_thread_process, args=(photo_id,), daemon=True).start()


def _thread_process(photo_id):
    close_old_connections()
    try:
        process_photo(photo_id)
    finally:
        close_old_connections()


def process_photo(photo_id):
    photo = Photo.objects.filter(pk=photo_id).first()
    if photo is None or photo.media_type != "video" or photo.processing_status == "ready":
        return
    if _acquire_lock(photo_id) is None:
        return
    dst = ""
    try:
        claimed = Photo.objects.filter(
            pk=photo.id, processing_status__in=("checking", "pending", "uploading", "failed", "converting")
        ).update(processing_status="converting")
        if not claimed:
            return
        photo.refresh_from_db()
        src = photo.source_path or (photo.video.path if photo.video else "")
        if not src or not os.path.isfile(src):
            _fail(photo, "Le fichier source est introuvable. Rien n'a été publié.")
            return
        dst = str(_incoming() / f"{uuid.uuid4().hex}.mp4")
        info = convert_video_file(src, dst)
        poster = poster_from_video(dst, info["duration"])
        prepared = prepare_image(ContentFile(poster, name="poster.jpg"))
        from django.core.files import File

        if photo.video:
            photo.video.delete(save=False)
        with open(dst, "rb") as handle:
            photo.video.save("video.mp4", File(handle), save=False)
        if photo.image:
            photo.image.delete(save=False)
        if photo.thumb:
            photo.thumb.delete(save=False)
        photo.image.save(f"poster.{prepared.ext}", ContentFile(prepared.display), save=False)
        photo.thumb.save("thumb.jpg", ContentFile(prepared.thumb), save=False)
        photo.byte_size = info["output_bytes"] + len(prepared.display)
        photo.estimated_bytes = info["estimate"]
        photo.duration_s = info["duration"]
        photo.width = info["out_width"]
        photo.height = info["out_height"]
        photo.processing_status = "ready"
        photo.processing_error = ""
        photo.source_path = ""
        photo.moderation_status = "approved" if settings.AUTO_APPROVE_PHOTOS else "pending"
        photo.save()
        _discard(src)
    except MediaError as exc:
        _fail(photo, str(exc))
    except Exception:
        _fail(photo, "La conversion a échoué. Le fichier original n'a pas été publié.")
    finally:
        _release_lock(photo_id)
        if dst and os.path.isfile(dst):
            os.remove(dst)


def _fail(photo, message):
    if photo.video:
        photo.video.delete(save=False)
    photo.processing_status = "failed"
    photo.processing_error = message[:200]
    photo.moderation_status = "pending"
    photo.byte_size = 0
    photo.save()


def _discard(path):
    if path and os.path.isfile(path) and "incoming" in path.replace("\\", "/"):
        os.remove(path)


def state_label(photo):
    status = photo.processing_status or "ready"
    if status == "failed":
        return "Échec"
    if status == "uploading":
        return "Importation"
    if status == "checking":
        return "Vérification"
    if status in ("converting", "pending"):
        return "Conversion"
    if photo.moderation_status == "pending":
        return "En modération"
    if photo.moderation_status == "approved":
        return "Disponible"
    if photo.moderation_status == "rejected":
        return "Refusé"
    return "Disponible"


def cleanup_abandoned(hours=24):
    cutoff = timezone.now() - timedelta(hours=hours)
    removed = 0
    recover_stale_conversions()
    for row in MediaUpload.objects.filter(created_at__lt=cutoff).exclude(status__in=("ready", "canceled")):
        _discard(row.temp_path)
        row.status = "canceled"
        row.save(update_fields=["status"])
        removed += 1
    for photo in Photo.objects.filter(processing_status="failed", created_at__lt=cutoff).exclude(source_path=""):
        _discard(photo.source_path)
        photo.source_path = ""
        photo.save(update_fields=["source_path"])
        removed += 1
    return removed


def append_chunk(upload, index, blob):
    if upload.status == "canceled":
        raise MediaError("chunk", "Cette importation a été annulée.")
    if index != upload.next_index:
        if index < upload.next_index:
            return upload
        raise MediaError("chunk", "Morceau inattendu. Reprenez à partir du dernier morceau reçu.")
    if upload.received + len(blob) > upload.total_size:
        raise MediaError("size", "La taille annoncée est dépassée.")
    if upload.total_size > video_max_bytes():
        raise MediaError("size", "La vidéo dépasse la limite de poids.")
    path = Path(upload.temp_path)
    with path.open("ab") as handle:
        handle.write(blob)
    upload.received += len(blob)
    upload.next_index += 1
    if upload.received >= upload.total_size:
        upload.status = "checking"
    upload.save(update_fields=["received", "next_index", "status", "updated_at"])
    return upload


def begin_upload(profile, kind, filename, total_size, private):
    if total_size <= 0 or total_size > (video_max_bytes() if kind == "video" else photo_max_bytes()):
        raise MediaError("size", "La taille du fichier n'est pas acceptée.")
    assert_member_room(profile, total_size)
    token = uuid.uuid4().hex
    suffix = ".bin" if kind == "video" else ".img"
    path = _incoming() / f"{token}{suffix}"
    path.touch()
    return MediaUpload.objects.create(
        token=token,
        profile=profile,
        kind=kind,
        filename=(filename or "")[:120],
        total_size=total_size,
        is_private=private,
        temp_path=str(path),
        status="uploading",
    )


def finish_upload(upload, masks=None, confirm_gif=False, approve=False):
    if upload.status == "canceled":
        raise MediaError("chunk", "Cette importation a été annulée.")
    if upload.photo_id and upload.status == "ready":
        return upload.photo
    if upload.received != upload.total_size or not os.path.isfile(upload.temp_path):
        raise MediaError("damaged", "L'importation est incomplète.")
    if upload.kind == "video":
        photo = queue_video(upload.profile, upload.temp_path, upload.is_private, upload.filename)
        upload.photo = photo
        upload.status = "ready"
        upload.temp_path = ""
        upload.save(update_fields=["photo", "status", "temp_path", "updated_at"])
        return photo
    with open(upload.temp_path, "rb") as handle:
        prepared = prepare_image(handle, masks=masks, confirm_gif=confirm_gif)
    photo = Photo(profile=upload.profile, position=upload.profile.photos.count())
    save_photo_files(photo, prepared, upload.is_private, approve)
    _discard(upload.temp_path)
    upload.temp_path = ""
    upload.photo = photo
    upload.status = "ready"
    upload.save(update_fields=["photo", "status", "temp_path", "updated_at"])
    return photo


def storage_snapshot():
    root = Path(settings.MEDIA_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    measurable = 0 < usage.total < 1024 ** 5
    photos = Photo.objects.filter(media_type="photo")
    videos = Photo.objects.filter(media_type="video")

    def weight(qs):
        return sum(row.byte_size or 0 for row in qs.only("byte_size"))

    free_ratio = (usage.free / usage.total) if measurable else 1
    alert_at = limit_int("storage_alert_percent", 85)
    used_percent = int(100 - free_ratio * 100) if measurable else None
    return {
        "total": usage.total if measurable else 0,
        "used": usage.used if measurable else 0,
        "free": usage.free if measurable else 0,
        "measurable": measurable,
        "used_percent": used_percent,
        "alert": bool(measurable and used_percent is not None and used_percent >= alert_at),
        "alert_percent": alert_at,
        "photos": photos.count(),
        "photo_bytes": weight(photos),
        "videos": videos.count(),
        "video_bytes": weight(videos),
        "queue": Photo.objects.filter(media_type="video", processing_status__in=("checking", "converting", "pending", "uploading")).count(),
        "failed": Photo.objects.filter(processing_status="failed").count(),
        "video_max_bytes": video_max_bytes(),
        "video_max_seconds": video_max_seconds(),
        "photo_max_bytes": photo_max_bytes(),
        "member_quota": member_quota_bytes(),
        "parallel": parallel_conversions(),
    }


def _ensure_faststart(path):
    """Le téléphone a besoin du descriptif au début du fichier pour démarrer la lecture."""
    with open(path, "rb") as handle:
        head = handle.read(2_000_000)
    moov = head.find(b"moov")
    mdat = head.find(b"mdat")
    if moov != -1 and (mdat == -1 or moov < mdat):
        return
    fixed = path + ".fast.mp4"
    proc = _run([_ffmpeg(), "-y", "-i", path, "-c", "copy", "-movflags", "+faststart", fixed], 180)
    if proc.returncode == 0 and os.path.isfile(fixed) and os.path.getsize(fixed) > 32:
        os.replace(fixed, path)
    elif os.path.isfile(fixed):
        os.remove(fixed)


def ranged_response(request, path, content_type, playback=False):
    from django.http import HttpResponse, StreamingHttpResponse

    size = os.path.getsize(path)
    cache = "private, max-age=3600" if playback else "private, no-store"
    header = (request.META.get("HTTP_RANGE") or "").strip()
    if "," in header:
        header = ""
    start, end, status = 0, size - 1, 200
    if header:
        match = re.match(r"bytes=(\d*)-(\d*)$", header, re.I)
        if not match or (match.group(1) == "" and match.group(2) == ""):
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Accept-Ranges"] = "bytes"
            return response
        if match.group(1) == "":
            suffix = int(match.group(2) or 0)
            start = max(0, size - suffix)
        else:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
        end = min(end, size - 1)
        if start >= size or start > end:
            response = HttpResponse(status=416)
            response["Content-Range"] = f"bytes */{size}"
            response["Accept-Ranges"] = "bytes"
            return response
        status = 206
    length = end - start + 1

    def chunks():
        with open(path, "rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining:
                data = handle.read(min(64 * 1024, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = StreamingHttpResponse(chunks(), status=status, content_type=content_type)
    response["Content-Length"] = str(length)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = cache
    response["Content-Disposition"] = "inline"
    if status == 206:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    return response
