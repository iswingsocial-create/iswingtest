import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import date, timedelta
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone
from PIL import Image

from swingapp.integrations import (
    get_integration,
    push_payload,
    remember_device,
    save_integration,
    secrets,
    test_stripe,
)
from swingapp.media_pipeline import (
    MediaError,
    assert_member_room,
    fit_1080,
    prepare_image,
    queue_video,
    validate_video_info,
)
from swingapp.models import Campaign, OutboundEmail, Photo, Profile, PushDevice, SiteSetting


def jpeg_bytes(color=(255, 220, 20), size=(80, 48)):
    img = Image.new("RGB", size, color)
    out = BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


class MediaStackTests(TestCase):
    def make(self, email, name="Membre"):
        user = get_user_model().objects.create_user(
            email=email, password="motdepasse10", birth_date=date(1990, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        profile = Profile.objects.create(
            user=user, display_name=name, city="Lyon", bio="bio",
            validated_at=timezone.now(), trial_ends_at=timezone.now() + timedelta(days=7),
        )
        return user, profile

    def staff(self):
        user = get_user_model().objects.create_superuser(email="media-staff@example.com", password="motdepasse10")
        self.client.force_login(user)
        session = self.client.session
        session["staff_2fa"] = True
        session.save()
        return user

    def test_limits_and_fit_do_not_upscale(self):
        info = {"formats": {"mp4"}, "width": 320, "height": 180, "duration": 601, "fps": 30}
        with self.assertRaises(MediaError) as raised:
            validate_video_info(info, 1000)
        self.assertEqual(raised.exception.code, "duration")
        info["duration"] = 2
        with self.assertRaises(MediaError) as raised:
            validate_video_info(info, 2_000_000_001)
        self.assertEqual(raised.exception.code, "size")
        with self.assertRaises(MediaError):
            validate_video_info({"formats": {"wav"}, "width": 10, "height": 10, "duration": 1}, 100)
        self.assertEqual(fit_1080(320, 180), (320, 180))
        self.assertEqual(fit_1080(180, 320), (180, 320))
        self.assertLessEqual(fit_1080(4000, 2000)[1], 1080)

    def test_member_quota_stays_open_until_a_value_is_saved(self):
        _, profile = self.make("quota@example.com")
        assert_member_room(profile, 2_000_000_000)
        SiteSetting.objects.create(key="member_media_bytes", value="10")
        with self.assertRaises(MediaError):
            assert_member_room(profile, 11)

    def test_documents_are_refused_and_gif_needs_confirmation(self):
        svg = SimpleUploadedFile("dessin.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", content_type="image/svg+xml")
        with self.assertRaises(MediaError):
            prepare_image(svg)
        pdf = SimpleUploadedFile("note.pdf", b"%PDF-1.4 faux", content_type="application/pdf")
        with self.assertRaises(MediaError):
            prepare_image(pdf)
        frames = [Image.new("RGB", (16, 16), color) for color in ((255, 0, 0), (0, 0, 255))]
        raw = BytesIO()
        frames[0].save(raw, format="GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
        gif = SimpleUploadedFile("anim.gif", raw.getvalue(), content_type="image/gif")
        with self.assertRaises(MediaError) as raised:
            prepare_image(gif)
        self.assertEqual(raised.exception.code, "animated")
        gif.seek(0)
        prepared = prepare_image(gif, confirm_gif=True)
        self.assertEqual(prepared.ext, "webp")
        self.assertTrue(prepared.display.startswith(b"RIFF"))

    def test_heic_avif_and_masks_are_baked_into_pixels(self):
        src = Image.new("RGB", (64, 40), (250, 240, 10))
        heic = BytesIO()
        src.save(heic, format="HEIF")
        prepared = prepare_image(SimpleUploadedFile("phone.heic", heic.getvalue(), content_type="image/heic"))
        self.assertEqual(prepared.ext, "jpg")
        avif = BytesIO()
        src.save(avif, format="AVIF")
        prepared = prepare_image(SimpleUploadedFile("phone.avif", avif.getvalue(), content_type="image/avif"))
        self.assertGreater(len(prepared.display), 100)
        masked = prepare_image(
            SimpleUploadedFile("face.jpg", jpeg_bytes(), content_type="image/jpeg"),
            masks=[
                {"type": "sticker", "x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8, "rotation": 0, "emoji": "●"},
                {"type": "blur", "x": 0.0, "y": 0.0, "w": 0.2, "h": 0.2, "rotation": 12, "strength": 8},
            ],
        )
        opened = Image.open(BytesIO(masked.display))
        pixel = opened.getpixel((opened.width // 2, opened.height // 2))
        self.assertLess(pixel[0], 80)
        self.assertNotEqual(masked.display, jpeg_bytes())
        self.assertNotEqual(masked.thumb, masked.display)

    def test_profile_page_lists_formats(self):
        user, _ = self.make("page@example.com")
        self.client.force_login(user)
        res = self.client.get("/moi/?onglet=medias")
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "HEIC")
        self.assertNotContains(res, "MTS")
        self.assertNotContains(res, "2 000 000 000")
        self.assertNotContains(res, "ajustée si possible")
        self.assertNotContains(res, "sans déformation")
        self.assertContains(res, "media-block", count=2)
        self.assertContains(res, 'data-sticker="happy"')
        self.assertContains(res, 'data-sticker="devil"')
        self.assertContains(res, 'data-sticker="pineapple"')
        self.assertContains(res, "ne garantit pas")
        js = __import__("pathlib").Path("static/js/masks.js").read_text(encoding="utf-8")
        self.assertIn("ellipse", js)
        self.assertIn("pineapple", js)
        self.assertNotIn("fillRect", js)
        en = self.client.get("/moi/?onglet=medias&lang=en")
        self.assertNotContains(en, "without stretching")
        es = self.client.get("/moi/?onglet=medias&lang=es")
        self.assertNotContains(es, "sin deformarlo")
        legal = self.client.get("/legal/medias/?lang=fr")
        self.assertContains(legal, "Limites techniques")
        self.assertContains(legal, "HEIC")
        self.assertContains(legal, "2 560")
        self.assertContains(legal, "10 minutes")
        self.assertContains(self.client.get("/legal/medias/?lang=en"), "Technical limits")
        self.assertContains(self.client.get("/legal/medias/?lang=es"), "Límites técnicos")

    def test_stickers_and_oval_blur_are_baked_in(self):
        from swingapp.media_pipeline import apply_masks

        img = Image.new("RGB", (80, 80), (0, 0, 0))
        px = img.load()
        for y in range(80):
            for x in range(80):
                px[x, y] = (255, 255, 255) if ((x // 2) + (y // 2)) % 2 == 0 else (0, 0, 0)
        corner = img.getpixel((0, 0))
        center_before = img.getpixel((40, 40))
        blurred = apply_masks(img, [{"type": "blur", "x": 0, "y": 0, "w": 1, "h": 1, "strength": 14}])
        self.assertEqual(blurred.getpixel((0, 0)), corner)
        self.assertEqual(blurred.getpixel((79, 79)), img.getpixel((79, 79)))
        self.assertNotEqual(blurred.getpixel((40, 40)), center_before)
        box = {"type": "sticker", "x": 0.2, "y": 0.2, "w": 0.6, "h": 0.6, "rotation": 0}
        happy = apply_masks(img, [{**box, "emoji": "happy"}])
        devil = apply_masks(img, [{**box, "emoji": "devil"}])
        pine = apply_masks(img, [{**box, "emoji": "pineapple"}])
        hy, dy, py = happy.getpixel((40, 40)), devil.getpixel((40, 40)), pine.getpixel((40, 40))
        self.assertGreater(hy[0], 200)
        self.assertGreater(hy[1], 160)
        self.assertGreater(dy[0], 140)
        self.assertLess(dy[1], 90)
        self.assertGreater(py[0], 180)
        self.assertGreater(py[1], 140)
        self.assertTrue(any(pine.getpixel((40, y))[1] > pine.getpixel((40, y))[0] + 20 for y in range(16, 30)))

    def test_private_media_range_stays_forbidden(self):
        owner, profile = self.make("owner-media@example.com", "Owner")
        other, _ = self.make("other-media@example.com", "Other")
        photo = Photo(profile=profile, is_private=True, moderation_status="approved", media_type="photo")
        photo.image.save("secret.jpg", SimpleUploadedFile("secret.jpg", jpeg_bytes((1, 2, 3))), save=True)
        self.client.force_login(other)
        denied = self.client.get(f"/photos/{photo.id}/", HTTP_RANGE="bytes=0-8")
        self.assertEqual(denied.status_code, 403)
        thumb = self.client.get(f"/photos/{photo.id}/?thumb=1", HTTP_RANGE="bytes=0-8")
        self.assertEqual(thumb.status_code, 403)
        self.client.force_login(owner)
        allowed = self.client.get(f"/photos/{photo.id}/", HTTP_RANGE="bytes=0-8")
        self.assertEqual(allowed.status_code, 206)

    def test_secrets_blank_field_keeps_previous_value(self):
        save_integration("stripe", {"currency": "usd"}, {"secret_test": "sk_live_do_not_call"}, True, "test")
        save_integration("stripe", {"currency": "eur"}, {"secret_test": ""}, True, "test")
        self.assertEqual(secrets(get_integration("stripe"))["secret_test"], "sk_live_do_not_call")
        self.assertEqual(get_integration("stripe").public_data["currency"], "eur")
        ok, text = test_stripe()
        self.assertFalse(ok)
        self.assertIn("production", text.lower())

    def test_configuration_page_does_not_send_campaigns(self):
        user, profile = self.make("camp-media@example.com")
        before = OutboundEmail.objects.count()
        camp = Campaign.objects.create(
            sender=user, subject="Plus tard", body="Bonjour", status="scheduled",
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        self.staff()
        page = self.client.get("/gestion/configuration/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "non opérationnel")
        payments = self.client.get("/gestion/configuration/?onglet=paiements")
        self.assertContains(payments, "CCBill")
        self.assertContains(payments, "sk_test_")
        self.assertContains(payments, "Clé API secrète de test")
        look = self.client.get("/gestion/configuration/?onglet=apparence")
        self.assertContains(look, "Thème du site")
        self.assertNotContains(page, "sk_live")
        self.assertEqual(OutboundEmail.objects.count(), before)
        camp.refresh_from_db()
        self.assertEqual(camp.status, "scheduled")
        self.assertEqual(profile.display_name, "Membre")

    def test_appearance_tab_replaces_logo_theme_and_category(self):
        self.staff()
        before = OutboundEmail.objects.count()
        upload = SimpleUploadedFile("logo.png", jpeg_bytes((10, 20, 200), (64, 64)), content_type="image/jpeg")
        category = SimpleUploadedFile("bdsm.png", jpeg_bytes((200, 40, 40), (48, 48)), content_type="image/jpeg")
        res = self.client.post("/gestion/configuration/?onglet=apparence", {
            "onglet": "apparence",
            "action": "save",
            "theme": "clair",
            "logo": upload,
            "cat_bdsm": category,
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(SiteSetting.get("theme", ""), "clair")
        self.assertEqual(OutboundEmail.objects.count(), before)
        look = self.client.get("/gestion/configuration/?onglet=apparence")
        self.assertContains(look, 'data-theme="clair"')
        logo = b"".join(self.client.get("/brand/icons/logo.png").streaming_content)
        tile = b"".join(self.client.get("/brand/categories/bdsm.png").streaming_content)
        self.assertTrue(logo.startswith(b"\x89PNG"))
        self.assertTrue(tile.startswith(b"\x89PNG"))
        reset = self.client.post("/gestion/configuration/?onglet=apparence", {
            "onglet": "apparence", "action": "reset", "reset": "bdsm",
        })
        self.assertEqual(reset.status_code, 302)
        original = b"".join(self.client.get("/brand/categories/bdsm.png").streaming_content)
        self.assertNotEqual(original, tile)
        self.client.post("/gestion/configuration/?onglet=apparence", {
            "onglet": "apparence", "action": "reset", "reset": "all",
        })
        self.assertEqual(SiteSetting.get("theme", ""), "clair")

    def test_robots_hide_profiles(self):
        res = self.client.get("/robots.txt")
        self.assertContains(res, "Disallow: /profil/")
        self.assertContains(res, "Disallow: /photos/")

    def test_push_payload_is_discrete_and_logout_detaches_device(self):
        payload = push_payload("message", "/messages/9/")
        self.assertEqual(payload["title"], "iSwing")
        self.assertNotIn("Alice", payload["body"])
        self.assertNotIn("/messages/9/", payload["body"])
        user, _ = self.make("push@example.com", "Alice")
        endpoint = "https://push.example/alice"
        remember_device(user, endpoint, "p256dh-value", "auth-value", "test")
        self.client.force_login(user)
        session = self.client.session
        session["push_endpoint"] = endpoint
        session["push_user"] = user.id
        session.save()
        self.client.post("/comptes/deconnexion/")
        device = PushDevice.objects.get(user=user)
        self.assertTrue(device.disabled)

    def test_login_switch_disables_previous_push_device(self):
        first, _ = self.make("first-push@example.com", "Premier")
        second, _ = self.make("second-push@example.com", "Second")
        endpoint = "https://push.example/shared"
        remember_device(first, endpoint, "p256dh-value", "auth-value", "test")
        self.client.force_login(first)
        session = self.client.session
        session["push_endpoint"] = endpoint
        session["push_user"] = first.id
        session.save()
        self.client.post("/comptes/connexion/", {"email": second.email, "password": "motdepasse10"})
        digest = hashlib.sha256(endpoint.encode()).hexdigest()
        self.assertTrue(PushDevice.objects.get(endpoint_hash=digest).disabled)

    def test_chunk_cancel_and_resume(self):
        user, profile = self.make("chunks@example.com")
        self.client.force_login(user)
        first = SimpleUploadedFile("a.bin", b"A" * 1000, content_type="application/octet-stream")
        res = self.client.post("/moi/medias/morceau/", {
            "index": "0", "total_size": "3000", "filename": "clip.bin", "kind": "video",
            "visibility": "private", "media_rights": "1", "chunk": first,
        })
        self.assertEqual(res.status_code, 200)
        token = res.json()["upload_id"]
        self.assertEqual(res.json()["next_index"], 1)
        again = SimpleUploadedFile("a.bin", b"B" * 1000, content_type="application/octet-stream")
        res = self.client.post("/moi/medias/morceau/", {
            "upload_id": token, "index": "0", "total_size": "3000", "media_rights": "1", "chunk": again,
        })
        self.assertEqual(res.json()["received"], 1000)
        res = self.client.post("/moi/medias/morceau/", {"upload_id": token, "cancel": "1", "index": "0", "total_size": "3000"})
        self.assertTrue(res.json().get("canceled"))
        self.assertEqual(profile.photos.count(), 0)


def _ffmpeg():
    return shutil.which("ffmpeg")


def _encode(args, dest):
    proc = subprocess.run(args, capture_output=True, timeout=60)
    if proc.returncode != 0 or not os.path.isfile(dest):
        raise RuntimeError((proc.stderr or b"")[-400:])
    return dest


class VideoConversionTests(TestCase):
    def setUp(self):
        if not _ffmpeg():
            self.skipTest("ffmpeg absent")
        self.user = get_user_model().objects.create_user(
            email="video@example.com", password="motdepasse10", birth_date=date(1990, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        self.profile = Profile.objects.create(
            user=self.user, display_name="Video", city="Lyon", bio="bio",
            validated_at=timezone.now(), trial_ends_at=timezone.now() + timedelta(days=7),
        )
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))

    def _run(self, name, cmd):
        dest = os.path.join(self.tmp, name)
        return _encode([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", *cmd, dest], dest)

    def _publish(self, path, private=False):
        from pathlib import Path

        from django.conf import settings

        folder = Path(settings.PRIVATE_MEDIA_ROOT) / "incoming"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{os.path.basename(path)}-{id(path)}.bin"
        shutil.copy(path, target)
        photo = queue_video(self.profile, str(target), private, os.path.basename(path))
        photo.refresh_from_db()
        return photo, target

    def test_generated_sources_become_faststart_mp4_and_drop_the_original(self):
        land = self._run("land.mov", ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=0.3", "-c:v", "libx265", "-tag:v", "hvc1", "-an"])
        port = self._run("port.mov", ["-f", "lavfi", "-i", "testsrc=size=180x320:rate=10:duration=0.3", "-c:v", "libx265", "-tag:v", "hvc1", "-an"])
        webm = self._run("android.webm", ["-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=0.3", "-c:v", "libvpx-vp9", "-an"])
        base = self._run("base.mp4", ["-f", "lavfi", "-i", "color=c=red:s=320x180:d=0.3", "-c:v", "libx264", "-an"])
        turned = os.path.join(self.tmp, "turned.mp4")
        _encode([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-display_rotation", "90", "-i", base, "-c", "copy", turned], turned)
        heard = self._run("heard.mp4", ["-f", "lavfi", "-i", "testsrc=size=160x90:rate=10:duration=0.3", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.3", "-c:v", "libx264", "-c:a", "aac", "-shortest"])
        hdr = self._run("hdr.mp4", ["-f", "lavfi", "-i", "testsrc=size=64x64:rate=10:duration=0.2", "-vf", "format=yuv420p10le", "-c:v", "libx265", "-pix_fmt", "yuv420p10le", "-color_trc", "smpte2084", "-color_primaries", "bt2020", "-colorspace", "bt2020nc", "-an"])
        published = {}
        copies = {}
        for key, path in (("land", land), ("port", port), ("webm", webm), ("turned", turned), ("heard", heard), ("hdr", hdr)):
            photo, copy = self._publish(path, private=(key == "webm"))
            published[key] = photo
            copies[key] = copy
            self.assertEqual(photo.processing_status, "ready", photo.processing_error)
            self.assertFalse(photo.source_path)
            self.assertFalse(copy.exists())
            with open(photo.video.path, "rb") as handle:
                self.assertIn(b"ftyp", handle.read(64))
            self.assertLessEqual(max(photo.width, photo.height), 1080)
            self.assertNotIn("incoming", photo.video.path.replace("\\", "/"))
        self.assertGreater(published["port"].height, published["port"].width)
        self.assertGreater(published["turned"].height, published["turned"].width)
        self.assertLessEqual(published["land"].height, published["land"].width)
        probe = subprocess.run([_ffmpeg(), "-hide_banner", "-i", published["heard"].video.path], capture_output=True, timeout=20)
        self.assertIn(b"Audio: aac", probe.stderr)
        self.client.force_login(self.user)
        owned = self.client.get(f"/photos/{published['land'].id}/fichier/", HTTP_RANGE="bytes=0-16")
        self.assertEqual(owned.status_code, 206)
        self.assertNotIn("no-store", owned["Cache-Control"])
        self.assertIn("bytes", owned["Accept-Ranges"])
        self.assertEqual(len(b"".join(owned.streaming_content)), 17)
        with open(published["land"].video.path, "rb") as handle:
            head = handle.read(2_000_000)
        self.assertGreaterEqual(head.find(b"moov"), 0)
        self.assertLess(head.find(b"moov"), head.find(b"mdat") if b"mdat" in head else len(head))
        page = self.client.get("/moi/?onglet=medias")
        self.assertContains(page, "playsinline")
        probe_land = subprocess.run([_ffmpeg(), "-hide_banner", "-i", published["land"].video.path], capture_output=True, timeout=20)
        self.assertIn(b"h264", probe_land.stderr)
        self.assertIn(b"yuv420p", probe_land.stderr)
        MediaStackTests.make(self, "stranger-video@example.com")
        self.client.logout()
        stranger = get_user_model().objects.get(email="stranger-video@example.com")
        self.client.force_login(stranger)
        hidden = self.client.get(f"/photos/{published['webm'].id}/fichier/", HTTP_RANGE="bytes=0-16")
        self.assertEqual(hidden.status_code, 403)

    def test_damaged_file_is_not_published(self):
        path = os.path.join(self.tmp, "broken.mp4")
        with open(path, "wb") as handle:
            handle.write(b"\x00\x00\x00\x18ftypmp42" + os.urandom(200))
        photo, copy = self._publish(path)
        self.assertEqual(photo.processing_status, "failed")
        self.assertFalse(photo.video)
        self.assertTrue(copy.exists())
        self.client.force_login(self.user)
        res = self.client.get(f"/photos/{photo.id}/fichier/")
        self.assertEqual(res.status_code, 409)
        self.assertNotIn(copy.read_bytes()[:24], res.content)
        poster = self.client.get(f"/photos/{photo.id}/")
        self.assertIn("image/jpeg", poster["Content-Type"])
        self.assertNotEqual(b"".join(poster.streaming_content), copy.read_bytes())
