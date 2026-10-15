from datetime import date, timedelta
from io import BytesIO
import threading
from urllib.parse import urlparse

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from PIL import Image

from swingapp.models import AuditLog, Block, Campaign, CampaignDelivery, DailyUsage, EmailToken, Like, Match, MatchUsage, Message, Notice, OutboundEmail, Partner, Photo, PhotoGrant, PrivateAccess, Profile, Report, Subscription
from swingapp.models import new_token
from swingapp.services import QuotaError, consume_like, create_like, find_contact_info


def jpeg():
    img = Image.new("RGB", (40, 40), (80, 20, 120))
    out = BytesIO()
    img.save(out, format="JPEG")
    return ContentFile(out.getvalue(), name="t.jpg")


class RulesTests(TestCase):
    def make(self, email, name):
        user = get_user_model().objects.create_user(
            email=email, password="motdepasse10", birth_date=date(1990, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        profile = Profile.objects.create(user=user, display_name=name, city="Lyon", bio="bio", validated_at=timezone.now(), trial_ends_at=timezone.now() + timedelta(days=7))
        photo = Photo(profile=profile, is_primary=True, moderation_status="approved")
        photo.image.save("t.jpg", jpeg(), save=True)
        return user, profile

    def as_staff(self, user):
        self.client.force_login(user)
        session = self.client.session
        session["staff_2fa"] = True
        session.save()

    def test_underage_rejected(self):
        res = self.client.post("/comptes/inscription/", {
            "email": "jeune@example.com", "password": "motdepasse10", "birth_date_year": "2015", "birth_date_month": "1", "birth_date_day": "1",
            "display_name": "X", "kind": "single", "accept": "on",
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email="jeune@example.com").exists())

    def test_mutual_like_creates_match(self):
        _, a = self.make("a@example.com", "A")
        _, b = self.make("b@example.com", "B")
        self.assertIsNone(create_like(a, b)[0])
        match, already = create_like(b, a)
        self.assertIsNotNone(match)
        self.assertFalse(already)
        self.assertEqual(Match.objects.count(), 1)

    def test_staff_is_unlimited_without_subscription(self):
        user, _ = self.make("admin-test@example.com", "Admin")
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        user.profile.trial_ends_at = timezone.now() - timedelta(days=3)
        user.profile.save(update_fields=["trial_ends_at"])
        for _ in range(12):
            consume_like(user)

    def test_like_quota_locked(self):
        user, a = self.make("q@example.com", "Q")
        _, b = self.make("b2@example.com", "B2")
        for _ in range(10):
            consume_like(user)
        with self.assertRaises(QuotaError):
            consume_like(user)

    def test_private_photo_forbidden(self):
        user, a = self.make("p@example.com", "P")
        other, _ = self.make("o@example.com", "O")
        photo = Photo(profile=a, is_private=True, moderation_status="approved")
        photo.image.save("p.jpg", jpeg(), save=True)
        self.client.force_login(other)
        res = self.client.get(f"/photos/{photo.id}/")
        self.assertEqual(res.status_code, 403)

    def test_webhook_rejects_bad_signature(self):
        res = self.client.post("/paiements/webhook/", data=b"{}", content_type="application/json", HTTP_X_ISWING_SIGNATURE="nope")
        self.assertIn(res.status_code, (403, 503))

    def test_confirm_not_global_in_js(self):
        from pathlib import Path
        js = Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("data-confirm", js)
        self.assertNotIn("document.addEventListener(\"click\", function () { confirm", js)

    def test_tabs_follow_language(self):
        user, _ = self.make("lang@example.com", "Lang")
        self.client.force_login(user)
        session = self.client.session
        session["lang"] = "en"
        session.save()
        res = self.client.get("/moi/")
        self.assertContains(res, "Identity")
        self.assertContains(res, "Search")
        self.assertContains(res, "Visibility")
        self.assertNotContains(res, "Identité")

    def test_header_menu_bell_and_footer_languages(self):
        user, profile = self.make("nav@example.com", "Nav")
        Notice.objects.create(profile=profile, kind="like", body="bonjour")
        self.client.force_login(user)
        fr = self.client.get("/decouvrir/")
        self.assertContains(fr, 'id="menu-btn"')
        self.assertContains(fr, 'id="main-menu"')
        self.assertContains(fr, 'aria-label="Menu"')
        self.assertContains(fr, 'href="/decouvrir/" aria-current="page"')
        self.assertContains(fr, 'href="/matchs/"')
        self.assertContains(fr, 'href="/messages/"')
        self.assertContains(fr, 'href="/moi/"')
        self.assertContains(fr, 'href="/abonnement/"')
        self.assertContains(fr, 'href="/parametres/"')
        self.assertContains(fr, 'class="icon-btn bell"')
        self.assertContains(fr, 'aria-label="Notifications (1)"')
        self.assertContains(fr, 'class="badge"')
        self.assertContains(fr, 'aria-label="Langue"')
        self.assertContains(fr, 'lang="en"')
        self.assertNotContains(fr, "tabbar")
        self.assertNotContains(fr, ">Notifications<")
        me = self.client.get("/moi/")
        self.assertContains(me, "Utiliser ce cadrage")
        self.assertContains(me, "Garder la photo entière")
        self.assertContains(me, 'class="crop-body"')
        self.assertContains(me, 'class="row crop-actions"')
        self.assertContains(me, 'id="crop-apply"')
        en = self.client.get("/moi/?lang=en")
        self.assertContains(en, "Discover")
        self.assertContains(en, "My profile")
        self.assertContains(en, "Subscription")
        self.assertContains(en, "Use this crop")
        self.assertContains(en, "Keep the whole photo")
        self.assertContains(en, 'aria-label="Language"')
        self.assertContains(en, 'aria-label="Notifications (1)"')
        self.assertNotContains(en, "Découvrir")
        self.assertNotContains(en, "Utiliser ce cadrage")
        es = self.client.get("/matchs/?lang=es")
        self.assertContains(es, "Menú")
        self.assertContains(es, "Mi perfil")
        self.assertContains(es, 'aria-label="Idioma"')
        self.assertContains(es, 'aria-label="Avisos (1)"')
        self.assertContains(es, 'href="/matchs/" aria-current="page"')
        self.client.logout()
        guest = self.client.get("/")
        self.assertNotContains(guest, 'id="menu-btn"')
        self.assertContains(guest, 'aria-label="Langue"')
        from pathlib import Path
        css = Path("static/css/app.css").read_text(encoding="utf-8")
        self.assertIn(".crop-actions", css)
        self.assertIn("max-height: calc(100dvh - 1rem)", css)
        self.assertIn("aspect-ratio: 4 / 5", css)
        self.assertNotIn(".tabbar", css)
        js = Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("Escape", js)
        self.assertIn("main-menu", js)

    def test_discover_shows_one_card(self):
        user, _ = self.make("me@example.com", "Me")
        self.make("c1@example.com", "C1")
        self.make("c2@example.com", "C2")
        self.client.force_login(user)
        res = self.client.get("/decouvrir/")
        self.assertEqual(res.content.count(b"tinder-card"), 1)

    def test_cities_are_not_a_short_list(self):
        res = self.client.get("/villes/?q=Par")
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(len(res.json()["results"]), 1)

    def test_uploaded_photo_respects_exif_orientation(self):
        user, profile = self.make("exif@example.com", "Exif")
        self.client.force_login(user)
        img = Image.new("RGB", (40, 12), (200, 20, 20))
        exif = img.getexif()
        exif[274] = 6
        raw = BytesIO()
        img.save(raw, format="JPEG", exif=exif)
        raw.seek(0)
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile("side.jpg", raw.getvalue(), content_type="image/jpeg")
        seed_ids = set(profile.photos.values_list("id", flat=True))
        res = self.client.post("/moi/photos/", {"image": upload, "visibility": "public", "media_rights": "1", "media_minor": "1", "media_host": "1"})
        self.assertEqual(res.status_code, 302)
        photo = profile.photos.exclude(id__in=seed_ids).order_by("-id").first()
        self.assertIsNotNone(photo)
        saved = Image.open(photo.image.path)
        self.assertGreater(saved.height, saved.width)

    def test_legal_page_and_own_preview(self):
        user, profile = self.make("own@example.com", "Own")
        self.client.force_login(user)
        res = self.client.get(f"/profil/{profile.id}/")
        self.assertContains(res, "Own")
        page = self.client.get("/legal/confidentialite/")
        self.assertContains(page, "Langlois")

    def test_city_is_visible_on_profile_and_discover(self):
        user, _ = self.make("city-me@example.com", "Me")
        _, other = self.make("city-other@example.com", "Nantes")
        other.city = "Nantes"
        other.save(update_fields=["city"])
        self.client.force_login(user)
        self.assertContains(self.client.get("/decouvrir/"), "Nantes")
        self.assertContains(self.client.get(f"/profil/{other.id}/"), "Nantes")

    def test_like_is_saved_once_and_quota_is_explained(self):
        user, actor = self.make("like@example.com", "Like")
        _, target = self.make("liked@example.com", "Liked")
        self.client.force_login(user)
        res = self.client.post(f"/actions/like/{target.id}/")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["liked"])
        self.assertFalse(res.json()["already"])
        again = self.client.post(f"/actions/like/{target.id}/")
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json()["already"])
        self.assertEqual(Like.objects.filter(actor=actor, target=target).count(), 1)
        _, extra = self.make("extra@example.com", "Extra")
        for _ in range(10):
            from swingapp.services import consume_like
            try:
                consume_like(user)
            except QuotaError:
                break
        blocked = self.client.post(f"/actions/like/{extra.id}/")
        self.assertEqual(blocked.status_code, 403)
        self.assertIn("like", blocked.json()["error"].lower())

    def test_ten_distinct_likes_then_eleventh_refused(self):
        user, me = self.make("ten@example.com", "Ten")
        self.client.force_login(user)
        for i in range(10):
            _, target = self.make(f"ten-{i}@example.com", f"T{i}")
            res = self.client.post(f"/actions/like/{target.id}/", {"client_key": f"ten-{i}"})
            self.assertEqual(res.status_code, 200, res.content)
            self.assertFalse(res.json()["already"])
        self.assertEqual(Like.objects.filter(actor=me).count(), 10)
        self.assertEqual(DailyUsage.objects.get(user=user, day=timezone.now().date()).likes, 10)
        _, extra = self.make("ten-11@example.com", "T11")
        blocked = self.client.post(f"/actions/like/{extra.id}/", {"client_key": "ten-11"})
        self.assertEqual(blocked.status_code, 403)
        self.assertFalse(blocked.json()["ok"])
        self.assertEqual(blocked.json()["likes_left"], 0)
        self.assertEqual(Like.objects.filter(actor=me).count(), 10)

    def test_same_client_key_does_not_spend_two_likes(self):
        user, me = self.make("key@example.com", "Key")
        _, target = self.make("key-t@example.com", "KeyT")
        self.client.force_login(user)
        first = self.client.post(f"/actions/like/{target.id}/", {"client_key": "same-key"})
        second = self.client.post(f"/actions/like/{target.id}/", {"client_key": "same-key"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["already"])
        self.assertEqual(Like.objects.filter(actor=me, target=target).count(), 1)
        self.assertEqual(DailyUsage.objects.get(user=user, day=timezone.now().date()).likes, 1)

    def test_new_day_resets_like_quota(self):
        user, _ = self.make("day@example.com", "Day")
        DailyUsage.objects.create(user=user, day=timezone.now().date() - timedelta(days=1), likes=10)
        consume_like(user)
        self.assertEqual(DailyUsage.objects.get(user=user, day=timezone.now().date()).likes, 1)

    def test_two_messages_per_side_then_third_refused(self):
        user_a, a = self.make("msg-a@example.com", "MsgA")
        user_b, b = self.make("msg-b@example.com", "MsgB")
        create_like(a, b)
        match, _ = create_like(b, a)
        for user, prefix in ((user_a, "a"), (user_b, "b")):
            self.client.force_login(user)
            for n in range(2):
                res = self.client.post(f"/messages/{match.id}/", {"body": f"{prefix}-{n}", "client_key": f"{prefix}-{n}"})
                self.assertEqual(res.status_code, 302)
            third = self.client.post(f"/messages/{match.id}/", {"body": f"{prefix}-2", "client_key": f"{prefix}-2"})
            self.assertEqual(third.status_code, 200)
            self.assertContains(third, "utilisé les messages")
            self.assertEqual(MatchUsage.objects.get(user=user, match=match).messages_sent, 2)

    def test_find_contact_info(self):
        self.assertEqual(find_contact_info("appelle-moi au 06 12 34 56 78"), "phone")
        self.assertEqual(find_contact_info("mon num: +1 514-555-1234"), "phone")
        self.assertEqual(find_contact_info("écris à lea.dupont@example.com"), "email")
        self.assertEqual(find_contact_info("lea@example.com"), "email")
        self.assertEqual(find_contact_info("suis-moi @lea_dupont"), "handle")
        self.assertEqual(find_contact_info("retrouve @lea"), "handle")
        self.assertEqual(find_contact_info("né le 12.05.1990 à Lyon"), "")
        self.assertEqual(find_contact_info("j'ai 2 chiens et 3 chats"), "")
        self.assertEqual(find_contact_info("rdv demain vers 18h"), "")
        self.assertEqual(find_contact_info("salut, ça va ?"), "")

    def _match_pair(self):
        user_a, a = self.make("ct-a@example.com", "CtA")
        user_b, b = self.make("ct-b@example.com", "CtB")
        create_like(a, b)
        match, _ = create_like(b, a)
        return user_a, a, user_b, b, match

    def test_trial_cannot_share_contact_info(self):
        user_a, a, user_b, b, match = self._match_pair()
        self.client.force_login(user_a)
        samples = [
            "appelle-moi au 06 12 34 56 78",
            "+1 514-555-1234",
            "lea@example.com",
            "retrouve @lea",
        ]
        for index, body in enumerate(samples):
            res = self.client.post(f"/messages/{match.id}/", {"body": body, "client_key": f"ct-block-{index}"})
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, "premium")
            self.assertNotContains(res, "Message object")
        self.assertFalse(Message.objects.filter(match=match, sender=a).exists())
        for body, key in (("né le 12.05.1990", "ct-ok-date"), ("j'ai 2 chiens", "ct-ok-dogs")):
            ok = self.client.post(f"/messages/{match.id}/", {"body": body, "client_key": key})
            self.assertEqual(ok.status_code, 302)
        self.assertEqual(Message.objects.filter(match=match, sender=a).count(), 2)
        self.assertEqual(MatchUsage.objects.get(user=user_a, match=match).messages_sent, 2)

    def test_premium_can_share_contact_info_with_notice(self):
        user_a, a, user_b, b, match = self._match_pair()
        Subscription.objects.update_or_create(
            user=user_a,
            defaults={"status": "active", "current_period_end": timezone.now() + timedelta(days=10)},
        )
        self.client.force_login(user_a)
        res = self.client.post(f"/messages/{match.id}/", {"body": "mon mail: a@example.com", "client_key": "ct-2"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Message.objects.filter(match=match, sender=a).exists())
        page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(page, "responsabilit")
        self.assertContains(page, 'class="contact-note"')
        self.assertNotContains(page, "Message object")
        self.client.force_login(user_b)
        other_page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(other_page, "a@example.com")
        self.assertNotContains(other_page, 'class="contact-note"')

    def test_shared_private_photo_grants_access(self):
        user_a, a, user_b, b, match = self._match_pair()
        photo = Photo(profile=a, is_primary=False, is_private=True, moderation_status="approved")
        photo.image.save("priv.jpg", jpeg(), save=True)
        other = Photo(profile=a, is_primary=False, is_private=True, moderation_status="approved")
        other.image.save("other.jpg", jpeg(), save=True)
        self.client.force_login(user_b)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/photos/{other.id}/").status_code, 200)
        match.closed_at = timezone.now()
        match.save(update_fields=["closed_at"])
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        match.closed_at = None
        match.save(update_fields=["closed_at"])
        self.client.force_login(user_a)
        res = self.client.post(f"/messages/{match.id}/", {"photo": str(photo.id), "client_key": "ct-3"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(PhotoGrant.objects.filter(photo=photo, grantee=b, revoked_at__isnull=True).exists())
        self.client.force_login(user_b)
        got = self.client.get(f"/photos/{photo.id}/")
        self.assertEqual(got.status_code, 200)
        page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(page, "shared-photo")
        self.assertContains(page, f"/photos/{photo.id}/")
        self.assertNotContains(page, "Message object")
        match.closed_at = timezone.now()
        match.save(update_fields=["closed_at"])
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/photos/{other.id}/").status_code, 403)
        PhotoGrant.objects.filter(photo=photo, grantee=b).update(revoked_at=timezone.now())
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        match.closed_at = None
        match.save(update_fields=["closed_at"])
        self.client.force_login(user_a)
        again = self.client.post(f"/messages/{match.id}/", {"photo": str(photo.id), "body": "encore", "client_key": "ct-3b"})
        self.assertEqual(again.status_code, 302)
        self.assertTrue(PhotoGrant.objects.filter(photo=photo, grantee=b, revoked_at__isnull=True).exists())
        self.client.force_login(user_b)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 200)

    def test_thread_renders_avatars_not_message_objects(self):
        user_a, a, user_b, b, match = self._match_pair()
        self.client.force_login(user_a)
        self.client.post(f"/messages/{match.id}/", {"body": "bonjour", "client_key": "ct-4"})
        self.client.force_login(user_b)
        self.client.post(f"/messages/{match.id}/", {"body": "salut", "client_key": "ct-5"})
        page = self.client.get(f"/messages/{match.id}/")
        self.assertNotContains(page, "Message object")
        self.assertContains(page, 'class="avatar"', count=2)
        self.assertContains(page, "bonjour")
        self.assertContains(page, "salut")
        poll = self.client.get(f"/messages/{match.id}/poll/?after=0")
        rows = poll.json()["messages"]
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row.get("avatar") for row in rows))
        js = __import__("pathlib").Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn('className = "avatar"', js)
        self.assertIn("shared-photo", js)

    def test_inbox_lists_avatar_preview_and_unread(self):
        user_a, a, user_b, b, match = self._match_pair()
        self.client.force_login(user_a)
        sent = self.client.post(f"/messages/{match.id}/", {"body": "bonjour les amis", "client_key": "in-1"})
        self.assertEqual(sent.status_code, 302)
        again = self.client.post(f"/messages/{match.id}/", {"body": "bonjour les amis", "client_key": "in-1"})
        self.assertEqual(again.status_code, 302)
        self.assertEqual(Notice.objects.filter(profile=b, kind="message").count(), 1)
        self.assertFalse(Notice.objects.filter(profile=a, kind="message").exists())
        note = Notice.objects.get(profile=b, kind="message")
        self.assertIn(f"/messages/{match.id}/", note.url)
        self.assertIn("bonjour", note.body)
        self.client.force_login(user_b)
        page = self.client.get("/messages/")
        self.assertContains(page, "inbox-item")
        self.assertContains(page, "inbox-item unread")
        self.assertContains(page, 'class="avatar"')
        self.assertContains(page, a.display_name)
        self.assertContains(page, "bonjour les amis")
        self.assertContains(page, 'class="badge"')
        notices = self.client.get("/notifications/")
        self.assertContains(notices, "bonjour les amis")
        self.assertContains(notices, f"/messages/{match.id}/")
        opened = self.client.get(f"/messages/{match.id}/")
        self.assertEqual(opened.status_code, 200)
        again_list = self.client.get("/messages/")
        self.assertNotContains(again_list, "inbox-item unread")

    def test_open_match_unlocks_private_photos(self):
        user_a, a = self.make("priv-a@example.com", "PrivA")
        user_b, b = self.make("priv-b@example.com", "PrivB")
        photo = Photo(profile=a, is_private=True, moderation_status="approved")
        photo.image.save("secret.jpg", jpeg(), save=True)
        self.client.force_login(user_b)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        create_like(a, b)
        match, _ = create_like(b, a)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 200)
        match.closed_at = timezone.now()
        match.save(update_fields=["closed_at"])
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)

    def test_one_consent_checkbox_sets_every_flag(self):
        page = self.client.get("/comptes/inscription/")
        self.assertEqual(page.content.decode().count('type="checkbox"'), 1)
        self.assertContains(page, "conditions")
        self.assertContains(page, "intime")
        self.assertContains(page, "médias")
        self.assertContains(page, "communications")
        res = self.client.post("/comptes/inscription/", {
            "email": "one-box@example.com", "password": "motdepasse10", "birth_date_year": "1991", "birth_date_month": "3", "birth_date_day": "3",
            "display_name": "Une", "kind": "single", "accept": "on",
        })
        self.assertEqual(res.status_code, 200)
        created = get_user_model().objects.get(email="one-box@example.com")
        self.assertTrue(created.adult_declared)
        self.assertIsNotNone(created.terms_accepted_at)
        self.assertTrue(created.intimate_consent)
        self.assertTrue(created.prefs_consent)
        self.assertTrue(created.reco_consent)
        self.assertTrue(created.promo_consent)
        media = __import__("pathlib").Path("templates/edit_profile.html").read_text(encoding="utf-8")
        self.assertEqual(media.count('name="media_rights"'), 3)
        self.assertNotIn('name="media_minor"', media)
        self.assertNotIn('name="media_host"', media)
        invite = __import__("pathlib").Path("templates/invitation.html").read_text(encoding="utf-8")
        self.assertEqual(invite.count('type="checkbox"'), 2)

    def test_partner_login_signs_messages_with_both_names(self):
        owner, profile = self.make("chave@example.com", "chave")
        profile.kind = "couple"
        profile.save(update_fields=["kind"])
        partner = Partner.objects.create(
            profile=profile, display_name="monica", birth_date=date(1992, 2, 2), consent_email="monica@example.com",
        )
        raw, digest = new_token()
        EmailToken.objects.create(user=owner, purpose="partner", token_hash=digest, expires_at=timezone.now() + timedelta(days=2))
        res = self.client.post(f"/invitation/partenaire/{raw}/", {
            "accept": "1", "password": "motdepasse10", "password2": "motdepasse10",
        })
        self.assertEqual(res.status_code, 302)
        partner.refresh_from_db()
        self.assertIsNotNone(partner.consent_at)
        self.assertEqual(partner.user.email, "monica@example.com")
        self.assertEqual(Profile.objects.filter(user__email="monica@example.com").count(), 0)
        home = self.client.get("/decouvrir/")
        self.assertEqual(home.status_code, 200)
        self.assertEqual(Profile.objects.filter(user__email="monica@example.com").count(), 0)
        _, other = self.make("dest-couple@example.com", "Dest")
        create_like(profile, other)
        match, _ = create_like(other, profile)
        sent = self.client.post(f"/messages/{match.id}/", {"body": "coucou", "client_key": "monica-1"})
        self.assertEqual(sent.status_code, 302)
        msg = Message.objects.get(match=match, body="coucou")
        self.assertEqual(msg.author_label, "chave (monica)")
        self.client.force_login(other.user)
        page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(page, "chave (monica)")
        self.client.force_login(owner)
        mine = self.client.post(f"/messages/{match.id}/", {"body": "salut", "client_key": "chave-1"})
        self.assertEqual(mine.status_code, 302)
        self.assertTrue(Message.objects.filter(match=match, body="salut", author_label="chave").exists())
        self.assertEqual(MatchUsage.objects.get(user=owner, match=match).messages_sent, 2)
        self.client.force_login(owner)
        seen = self.client.get(f"/messages/{match.id}/")
        self.assertContains(seen, "chave (monica)")
        self.assertContains(seen, ">chave<")

    def test_discover_empty_is_not_the_quota_warning(self):
        user, _ = self.make("empty-deck@example.com", "Empty")
        self.client.force_login(user)
        page = self.client.get("/decouvrir/")
        self.assertContains(page, "Aucun nouveau profil pour le moment")
        self.assertContains(page, "Likes restants aujourd")
        self.assertContains(page, "discover-empty")
        self.assertNotContains(page, "id=\"likes-done\"")
        self.assertContains(page, 'data-left="10"')
        js = __import__("pathlib").Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("data-busy", js)
        self.assertIn("client_key", js)
        self.assertIn("leaving", js)
        self.assertNotIn("location.reload()", js)

    def test_plans_are_visible_without_stripe(self):
        user, _ = self.make("bill@example.com", "Bill")
        self.client.force_login(user)
        page = self.client.get("/abonnement/")
        self.assertContains(page, "Premium")
        self.assertContains(page, "29.99")
        journey = self.client.get("/abonnement/souscrire/")
        self.assertContains(journey, "29.99")
        self.assertContains(journey, "Premium")

    def test_private_access_is_not_granted_by_a_like(self):
        owner, profile = self.make("owner@example.com", "Owner")
        member, other = self.make("member@example.com", "Member")
        photo = Photo(profile=profile, is_private=True, moderation_status="approved")
        photo.image.save("p.jpg", jpeg(), save=True)
        self.client.force_login(member)
        self.client.post(f"/actions/like/{profile.id}/")
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        self.client.post(f"/acces-prive/{profile.id}/demander/")
        self.client.force_login(owner)
        access = PrivateAccess.objects.get(owner=profile, grantee=other)
        self.client.post(f"/acces-prive/{access.id}/decider/", {"choice": "accept"})
        self.client.force_login(member)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 200)

    def test_report_blocks_both_ways_without_suspending(self):
        user, reporter = self.make("rep@example.com", "Rep")
        _, target = self.make("tgt@example.com", "Tgt")
        self.client.force_login(user)
        res = self.client.post(f"/signaler/{target.id}/", {"reason_code": "spam", "comment": "essai"})
        self.assertEqual(res.status_code, 302)
        report = Report.objects.get(reporter=reporter, target=target)
        self.assertEqual(report.reason_code, "spam")
        self.assertEqual(report.comment, "essai")
        target.refresh_from_db()
        self.assertFalse(target.suspended)
        self.assertTrue(Block.objects.filter(blocker=reporter, blocked=target).exists())
        self.assertTrue(Block.objects.filter(blocker=target, blocked=reporter).exists())
        self.client.force_login(user)
        self.assertEqual(self.client.post(f"/actions/like/{target.id}/").status_code, 403)


class BrokenMail:
    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, email_messages):
        raise OSError("smtp down")


class AdminFlowTests(RulesTests):
    def test_block_stands_without_a_report(self):
        user, actor = self.make("blocker@example.com", "Blocker")
        _, target = self.make("blocked@example.com", "Blocked")
        self.client.force_login(user)
        page = self.client.get(f"/profil/{target.id}/")
        self.assertContains(page, "Confirmer le blocage")
        self.assertContains(page, "Vous ne pourrez plus consulter vos profils respectifs")
        res = self.client.post(f"/bloquer/{target.id}/", HTTP_X_REQUESTED_WITH="fetch")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["ok"], True)
        self.assertEqual(Report.objects.count(), 0)
        self.assertTrue(Block.objects.filter(blocker=actor, blocked=target).exists())
        self.assertTrue(Block.objects.filter(blocker=target, blocked=actor).exists())

    def test_report_after_block_notifies_inbox_and_keeps_data(self):
        user, actor = self.make("rep2@example.com", "Rep2")
        target_user, target = self.make("tgt2@example.com", "Tgt2")
        Subscription.objects.create(user=target_user, status="active", current_period_end=timezone.now() + timedelta(days=10))
        photo = Photo.objects.get(profile=target)
        self.client.force_login(user)
        self.client.post(f"/bloquer/{target.id}/", HTTP_X_REQUESTED_WITH="fetch")
        res = self.client.post(
            f"/signaler/{target.id}/",
            {"reason_code": "harassment", "comment": "details", "related": "Profil"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(res.status_code, 200)
        report = Report.objects.get(reporter=actor, target=target)
        mail = OutboundEmail.objects.get(kind="report", ref=str(report.id))
        self.assertEqual(mail.to_email, "Info@iswing.live")
        self.assertIn("harassment", mail.body)
        self.assertIn("details", mail.body)
        self.assertIn(f"/gestion/signalements/{report.id}/", mail.body)
        self.assertNotIn("/photos/", mail.body)
        self.assertEqual(mail.status, "sent")
        self.assertTrue(Photo.objects.filter(pk=photo.pk).exists())
        self.assertTrue(Subscription.objects.filter(user=target_user, status="active").exists())
        target.refresh_from_db()
        self.assertFalse(target.suspended)

    @override_settings(EMAIL_BACKEND="swingapp.tests.BrokenMail")
    def test_email_failure_keeps_block_and_report(self):
        user, actor = self.make("rep3@example.com", "Rep3")
        _, target = self.make("tgt3@example.com", "Tgt3")
        self.client.force_login(user)
        res = self.client.post(f"/signaler/{target.id}/", {"reason_code": "spam", "comment": "x"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Report.objects.filter(reporter=actor, target=target).exists())
        mail = OutboundEmail.objects.get(kind="report")
        self.assertEqual(mail.status, "failed")
        self.assertTrue(Block.objects.filter(blocker=actor, blocked=target).exists())

    def test_private_media_needs_moderation_permission_and_is_logged(self):
        owner, profile = self.make("priv@example.com", "Priv")
        staff, _ = self.make("mod@example.com", "Mod")
        staff.is_staff = True
        staff.is_superuser = False
        staff.can_moderate = False
        staff.save()
        photo = Photo(profile=profile, is_private=True, moderation_status="approved")
        photo.image.save("p.jpg", jpeg(), save=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        staff.can_moderate = True
        staff.save()
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        session = self.client.session
        session["staff_2fa"] = True
        session.save()
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 200)
        self.assertTrue(AuditLog.objects.filter(actor=staff, action="staff_view_private_photo", target=str(photo.id)).exists())
        stranger, _ = self.make("str@example.com", "Str")
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)

    def test_added_member_must_consent_personally(self):
        admin, _ = self.make("root-add@example.com", "Root")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        res = self.client.post("/gestion/membres/ajouter/", {
            "kind": "couple",
            "display_name": "Nouveau",
            "email": "reel@example.com",
            "birth_date_year": "1992", "birth_date_month": "4", "birth_date_day": "4",
            "partner_name": "Partenaire",
            "partner_birth_year": "1993", "partner_birth_month": "5", "partner_birth_day": "5",
            "partner_email": "partenaire@example.com",
            "send_invite": "1",
            "sub_status": "none",
            "country": "FR",
        })
        self.assertEqual(res.status_code, 302, res.content[:500] if hasattr(res, "content") else res)
        created = get_user_model().objects.get(email="reel@example.com")
        self.assertFalse(created.adult_declared)
        self.assertIsNone(created.terms_accepted_at)
        self.assertFalse(created.intimate_consent)
        self.assertEqual(created.age_proof_status, "unconfirmed")
        self.assertFalse(created.is_demo)
        self.assertIsNone(created.profile.partner.consent_at)
        invite = OutboundEmail.objects.get(kind="invite")
        path = urlparse([line for line in invite.body.splitlines() if line.startswith("http")][0]).path
        self.client.logout()
        self.client.post(path, {"password": "motdepasse10", "password2": "motdepasse10"})
        created.refresh_from_db()
        self.assertFalse(created.adult_declared)
        self.client.post(path, {
            "password": "motdepasse10", "password2": "motdepasse10",
            "age_confirm": "1", "accept": "1", "intimate": "1",
        })
        created.refresh_from_db()
        self.assertTrue(created.adult_declared)
        self.assertIsNotNone(created.terms_accepted_at)
        self.assertEqual(created.age_proof_status, "declared")
        partner_mail = OutboundEmail.objects.get(kind="partner")
        partner_path = urlparse(partner_mail.body.strip().split()[-2] if False else [line for line in partner_mail.body.splitlines() if line.startswith("http")][0]).path
        self.client.post(partner_path, {"accept": "1"})
        self.assertIsNotNone(Partner.objects.get(profile=created.profile).consent_at)

    def test_campaign_respects_promo_and_does_not_duplicate(self):
        admin, _ = self.make("root-msg@example.com", "RootMsg")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        yes, _ = self.make("promo-yes@example.com", "Oui")
        yes.promo_consent = True
        yes.save(update_fields=["promo_consent"])
        self.make("promo-no@example.com", "Non")
        self.as_staff(admin)
        payload = {
            "scope": "all",
            "channel": "notice",
            "is_promo": "1",
            "subject": "Annonce",
            "body": "Bonjour {display_name}",
            "client_key": "campagne-test-1",
            "expected_count": "1",
            "confirm": "1",
            "recipient_ids": [str(yes.id)],
        }
        res = self.client.post("/gestion/communications/nouveau/", payload)
        self.assertEqual(res.status_code, 302)
        self.assertEqual(Campaign.objects.count(), 1)
        delivery = CampaignDelivery.objects.get()
        self.assertEqual(delivery.user.email, "promo-yes@example.com")
        self.assertEqual(delivery.status, "sent")
        self.assertEqual(Notice.objects.filter(kind="team").count(), 1)
        again = self.client.post("/gestion/communications/nouveau/", payload)
        self.assertEqual(again.status_code, 302)
        self.assertEqual(Campaign.objects.count(), 1)
        self.assertEqual(Notice.objects.filter(kind="team").count(), 1)
        service = {
            "scope": "one",
            "one": "promo-no@example.com",
            "channel": "notice",
            "subject": "Information",
            "body": "Bonjour {display_name}",
            "client_key": "campagne-test-2",
            "expected_count": "1",
            "confirm": "1",
            "recipient_ids": [str(get_user_model().objects.get(email="promo-no@example.com").id)],
        }
        self.client.post("/gestion/communications/nouveau/", service)
        self.assertTrue(CampaignDelivery.objects.filter(user__email="promo-no@example.com", status="sent").exists())


class AccessCorrectionTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff
    def test_paused_and_blocked_profiles_are_not_reachable_by_url(self):
        viewer, _ = self.make("view@example.com", "View")
        _, paused = self.make("pause@example.com", "Pause")
        paused.visibility = "paused"
        paused.save(update_fields=["visibility"])
        _, suspended = self.make("sus@example.com", "Sus")
        suspended.suspended = True
        suspended.save(update_fields=["suspended"])
        photo = Photo.objects.get(profile=paused)
        self.client.force_login(viewer)
        self.assertEqual(self.client.get(f"/profil/{paused.id}/").status_code, 403)
        self.assertContains(self.client.get(f"/profil/{paused.id}/"), "pas consultable", status_code=403)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        self.assertEqual(self.client.get(f"/profil/{suspended.id}/").status_code, 403)
        self.assertEqual(self.client.post(f"/actions/like/{paused.id}/").status_code, 403)

    def test_block_revokes_private_grants(self):
        user, actor = self.make("ba@example.com", "BA")
        _, target = self.make("bt@example.com", "BT")
        photo = Photo.objects.filter(profile=target, is_private=False).first()
        from swingapp.models import PhotoGrant

        PhotoGrant.objects.create(photo=photo, grantee=actor)
        self.client.force_login(user)
        self.client.post(f"/bloquer/{target.id}/", HTTP_X_REQUESTED_WITH="fetch")
        grant = PhotoGrant.objects.get(photo=photo, grantee=actor)
        self.assertIsNotNone(grant.revoked_at)

    def test_owner_sees_private_photo_unlocked(self):
        owner, profile = self.make("ownp@example.com", "OwnP")
        photo = Photo(profile=profile, is_private=True, moderation_status="approved")
        photo.image.save("priv.jpg", jpeg(), save=True)
        self.client.force_login(owner)
        page = self.client.get(f"/profil/{profile.id}/")
        self.assertContains(page, f"/photos/{photo.id}/")
        self.assertNotContains(page, "Photo privée")

    def test_admin_without_2fa_cannot_open_gestion_or_admin(self):
        admin, _ = self.make("gate@example.com", "Gate")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.client.force_login(admin)
        self.assertEqual(self.client.get("/gestion/").status_code, 302)
        self.assertIn("/gestion/2fa/", self.client.get("/gestion/")["Location"])
        self.assertEqual(self.client.get("/admin/").status_code, 302)
        self.as_staff(admin)
        self.assertEqual(self.client.get("/gestion/").status_code, 200)

    def test_cancel_without_provider_does_not_pretend_success(self):
        user, _ = self.make("pay@example.com", "Pay")
        Subscription.objects.create(user=user, status="active", provider="stripe", external_id="sub_test", source="provider", current_period_end=timezone.now() + timedelta(days=10))
        self.client.force_login(user)
        with self.settings(STRIPE_SECRET_KEY=""):
            res = self.client.post("/abonnement/annuler/")
        self.assertEqual(res.status_code, 302)
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.status, "active")
        self.assertFalse(sub.cancel_at_period_end)

    def test_webhook_failed_event_can_be_retried(self):
        import hashlib
        import hmac
        import json

        user, _ = self.make("hook@example.com", "Hook")
        body = json.dumps({
            "id": "evt-retry-1",
            "type": "payment.succeeded",
            "email": user.email,
            "subscription_id": "sub_hook",
            "customer_id": "cus_hook",
            "current_period_end": 2000000000,
        }).encode()
        secret = "hook-secret"
        signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with self.settings(PAYMENT_PROVIDER="testpay", PAYMENT_WEBHOOK_SECRET=secret):
            from swingapp.models import PaymentEvent

            PaymentEvent.objects.create(provider="testpay", event_id="evt-retry-1", payload_hash="x", status="failed")
            res = self.client.post("/paiements/webhook/", body, content_type="application/json", HTTP_X_ISWING_SIGNATURE=signature)
        self.assertEqual(res.status_code, 200)
        sub = Subscription.objects.get(user=user)
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.external_id, "sub_hook")
        self.assertEqual(sub.customer_id, "cus_hook")
        self.assertEqual(PaymentEvent.objects.get(event_id="evt-retry-1").status, "processed")

    def test_notices_mark_only_displayed_rows(self):
        user, profile = self.make("note@example.com", "Note")
        from swingapp.models import Notice

        for index in range(45):
            Notice.objects.create(profile=profile, kind="team", body=str(index))
        self.client.force_login(user)
        self.client.get("/notifications/")
        self.assertEqual(Notice.objects.filter(profile=profile, read_at__isnull=False).count(), 40)
        self.assertEqual(Notice.objects.filter(profile=profile, read_at__isnull=True).count(), 5)

    def test_bad_quota_does_not_crash(self):
        admin, _ = self.make("quota@example.com", "Quota")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        res = self.client.post("/gestion/parametres/", {"action": "quotas", "likes": "abc", "messages": "2"})
        self.assertEqual(res.status_code, 302)
        from swingapp.models import SiteSetting

        self.assertNotEqual(SiteSetting.get("trial_daily_likes", "10"), "abc")

    def test_opening_gestion_does_not_send_scheduled_campaign(self):
        admin, _ = self.make("sched@example.com", "Sched")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        member, _ = self.make("later@example.com", "Later")
        camp = Campaign.objects.create(
            sender=admin, subject="Plus tard", body="Bonjour", channel="notice", status="scheduled",
            scheduled_at=timezone.now() - timedelta(minutes=5),
        )
        CampaignDelivery.objects.create(campaign=camp, user=member)
        self.as_staff(admin)
        self.client.get("/gestion/")
        camp.refresh_from_db()
        self.assertEqual(camp.status, "scheduled")
        self.assertEqual(Notice.objects.filter(kind="team").count(), 0)

    def test_admin_preview_shows_paused_profile(self):
        admin, _ = self.make("prev@example.com", "Prev")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        _, paused = self.make("hidden@example.com", "Hidden")
        paused.visibility = "paused"
        paused.save(update_fields=["visibility"])
        self.as_staff(admin)
        page = self.client.get(f"/gestion/membres/{paused.id}/apercu/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Hidden")


    def test_totp_code_roundtrip_and_setup_page(self):
        from swingapp.models import new_totp_secret, totp_now, totp_valid

        secret = new_totp_secret()
        self.assertTrue(totp_valid(secret, totp_now(secret)))
        self.assertFalse(totp_valid(secret, "000000"))
        admin, _ = self.make("otp@example.com", "Otp")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.client.force_login(admin)
        page = self.client.get("/gestion/2fa/")
        self.assertContains(page, "Code actuel")
        self.assertContains(page, "Secret")


class LikeRaceTests(TransactionTestCase):
    def test_parallel_posts_count_one_like(self):
        user = get_user_model().objects.create_user(
            email="race@example.com", password="motdepasse10", birth_date=date(1990, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        me = Profile.objects.create(user=user, display_name="Race", city="Lyon", bio="bio", validated_at=timezone.now(), trial_ends_at=timezone.now() + timedelta(days=7))
        other_user = get_user_model().objects.create_user(
            email="race-t@example.com", password="motdepasse10", birth_date=date(1991, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        target = Profile.objects.create(user=other_user, display_name="RaceT", city="Lyon", bio="bio", validated_at=timezone.now(), trial_ends_at=timezone.now() + timedelta(days=7))
        for owner in (me, target):
            shot = Photo(profile=owner, is_primary=True, moderation_status="approved")
            shot.image.save("race.jpg", jpeg(), save=True)
        results = []
        errors = []
        barrier = threading.Barrier(2)
        clients = []
        for _ in range(2):
            client = Client()
            client.force_login(user)
            clients.append(client)

        def go(client):
            try:
                close_old_connections()
                barrier.wait(timeout=5)
                results.append(client.post(f"/actions/like/{target.id}/", {"client_key": "race-key"}))
            except Exception as exc:
                errors.append(repr(exc))
            finally:
                close_old_connections()

        threads = [threading.Thread(target=go, args=(client,)) for client in clients]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        self.assertEqual(Like.objects.filter(actor=me, target=target).count(), 1)
        self.assertEqual(DailyUsage.objects.get(user=user, day=timezone.now().date()).likes, 1)
        self.assertTrue(all(item.status_code == 200 for item in results))


class V4CorrectionTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def test_demo_profile_can_like_match_and_message(self):
        demo, actor = self.make("lea@iswing.test", "Lea")
        demo.is_demo = True
        demo.save(update_fields=["is_demo"])
        actor.is_demo = True
        actor.save(update_fields=["is_demo"])
        _, target = self.make("reel@example.com", "Reel")
        self.assertFalse(target.is_demo)
        self.assertIsNone(create_like(actor, target)[0])
        match, already = create_like(target, actor)
        self.assertIsNotNone(match)
        self.assertFalse(already)
        self.client.force_login(demo)
        sent = self.client.post(f"/messages/{match.id}/", {"body": "bonjour du profil test"})
        self.assertEqual(sent.status_code, 302)
        self.assertTrue(Message.objects.filter(match=match, body="bonjour du profil test").exists())
        page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(page, "bonjour du profil test")
        self.assertNotContains(page, "fictif")

    def test_badges_match_trial_paid_and_certified(self):
        viewer, _ = self.make("voir-badge@example.com", "Voir")
        user, profile = self.make("cible-badge@example.com", "Cible")
        self.client.force_login(viewer)
        trial = self.client.get(f"/profil/{profile.id}/")
        self.assertContains(trial, 'class="status-badge big">Membre essai')
        discover = self.client.get("/decouvrir/")
        self.assertContains(discover, 'class="status-badge">Membre essai')
        sub = Subscription.objects.get(user=user)
        sub.status = "active"
        sub.current_period_end = timezone.now() + timedelta(days=20)
        sub.save()
        profile.certified = True
        profile.save(update_fields=["certified"])
        paid = self.client.get(f"/profil/{profile.id}/")
        self.assertContains(paid, 'class="status-badge big">Membre<')
        self.assertContains(paid, "Profil certifié")
        self.assertNotContains(paid, "Membre essai")
        sub.status = "past_due"
        sub.save(update_fields=["status"])
        unpaid = self.client.get(f"/profil/{profile.id}/")
        self.assertNotContains(unpaid, "Profil certifié")
        self.assertNotContains(unpaid, 'class="status-badge big">Membre<')
        sub.status = "canceled"
        sub.save(update_fields=["status"])
        self.assertNotContains(self.client.get(f"/profil/{profile.id}/"), "Profil certifié")
        sub.status = "active"
        sub.save(update_fields=["status"])
        self.assertContains(self.client.get(f"/profil/{profile.id}/"), "Profil certifié")

    def test_certification_photo_stays_private_until_paid_badge(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        user, profile = self.make("certif@example.com", "Certif")
        other, _ = self.make("spectateur@example.com", "Spectateur")
        self.client.force_login(user)
        raw = jpeg()
        raw.seek(0)
        res = self.client.post("/moi/certification/", {"image": SimpleUploadedFile("feuille.jpg", raw.read(), content_type="image/jpeg"), "media_rights": "1"})
        self.assertEqual(res.status_code, 302)
        photo = Photo.objects.get(profile=profile, role="certification")
        self.assertTrue(photo.is_private)
        self.assertNotEqual(photo.moderation_status, "approved")
        own = self.client.get("/moi/?onglet=medias")
        self.assertNotContains(own, f"/photos/{photo.id}/")
        self.assertContains(own, "Demander la certification")
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        self.assertNotContains(self.client.get(f"/profil/{profile.id}/"), f"/photos/{photo.id}/")
        self.assertNotContains(self.client.get(f"/profil/{profile.id}/"), "Profil certifié")
        admin, _ = self.make("root-certif@example.com", "RootCert")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        req = profile.certifications.get()
        decided = self.client.post(f"/gestion/certifications/{req.id}/", {"action": "approve"})
        self.assertEqual(decided.status_code, 302)
        profile.refresh_from_db()
        photo.refresh_from_db()
        self.assertTrue(profile.certified)
        self.assertEqual(photo.moderation_status, "approved")
        self.assertTrue(photo.is_private)
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/photos/{photo.id}/").status_code, 403)
        self.assertNotContains(self.client.get(f"/profil/{profile.id}/"), "Profil certifié")
        sub = Subscription.objects.get(user=user)
        sub.status = "active"
        sub.current_period_end = timezone.now() + timedelta(days=12)
        sub.save()
        self.assertContains(self.client.get(f"/profil/{profile.id}/"), "Profil certifié")
        sub.status = "canceled"
        sub.save(update_fields=["status"])
        self.assertNotContains(self.client.get(f"/profil/{profile.id}/"), "Profil certifié")

    def test_notices_are_separate_and_follow_the_member_language(self):
        from swingapp.i18n import t
        from swingapp.services import notice_text, team_code_for_body

        user, profile = self.make("avis-lang@example.com", "Avis")
        long = ("Texte complet de l'avis. " * 40).strip()
        Notice.objects.create(profile=profile, kind="like", body=long, url="/decouvrir/")
        Notice.objects.create(profile=profile, kind="message", body="salut membre", url="/messages/1/")
        note = Notice.objects.create(profile=profile, kind="team", body="texte figé en français", code="notice_certified", url="/notifications/")
        self.client.force_login(user)
        fr = self.client.get("/notifications/?lang=fr")
        self.assertContains(fr, "notice-card", count=3)
        self.assertEqual(fr.content.decode().count("Texte complet de l"), 40)
        self.assertContains(fr, "Votre profil est certifié")
        en = self.client.get("/notifications/?lang=en")
        self.assertContains(en, "Your profile is certified")
        self.assertNotContains(en, "certifié")
        self.assertContains(en, "salut membre")
        self.assertEqual(en.content.decode().count("Texte complet de l"), 40)
        es = self.client.get("/notifications/?lang=es")
        self.assertContains(es, "Su perfil está certificado")
        self.assertEqual(team_code_for_body(t("fr", "team_warning")), "team_warning")
        warning = Notice(kind="team", code="team_warning", params='{"display_name": "Cible"}', body="")
        self.assertIn("Cible", notice_text(warning, "en"))
        self.assertIn("warning", notice_text(warning, "en"))
        self.assertIn("avertissement", notice_text(warning, "fr"))
        self.assertIn("aviso", notice_text(warning, "es"))
        self.assertIn("certified", notice_text(note, "en"))





class V5CorrectionTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def test_couple_stores_two_orientations_and_shows_both_names(self):
        user, profile = self.make("couple-or@example.com", "Alex")
        self.client.force_login(user)
        payload = {
            "display_name": "Alex", "kind": "couple", "orientation": "hetero",
            "city": "Lyon", "bio": "bio", "visibility": "public",
            "p-display_name": "Jo", "p-birth_date": "1992-04-04", "p-gender": "femme", "p-orientation": "bi",
        }
        res = self.client.post("/moi/", payload)
        self.assertEqual(res.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.orientation, "hetero")
        self.assertEqual(profile.partner.display_name, "Jo")
        self.assertEqual(profile.partner.orientation, "bi")
        profile.partner.consent_at = timezone.now()
        profile.partner.save(update_fields=["consent_at"])
        page = self.client.get(f"/profil/{profile.id}/")
        self.assertContains(page, "Alex (Hétérosexuel")
        self.assertContains(page, "Jo (Bisexuel")
        payload["orientation"] = "homo"
        payload["p-display_name"] = "Joelle"
        payload["p-orientation"] = "pan"
        self.client.post("/moi/", payload)
        profile.partner.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(profile.partner.display_name, "Joelle")
        self.assertEqual(profile.partner.orientation, "pan")
        changed = self.client.get(f"/profil/{profile.id}/?lang=en")
        self.assertContains(changed, "Alex (Homosexual)")
        self.assertContains(changed, "Joelle (Pansexual)")

    def test_signup_confirmation_email_follows_the_switch(self):
        from swingapp.models import SiteSetting

        admin, _ = self.make("root-signup@example.com", "RootMail")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        page = self.client.get("/gestion/configuration/?onglet=courriels")
        self.assertContains(page, "Envoyer le courriel de confirmation à l'inscription")
        self.assertContains(page, 'name="send_signup_email"')
        self.assertNotIn(b'name="send_signup_email" value="1" checked', page.content)
        self.assertEqual(SiteSetting.get("send_signup_email", "0"), "0")
        self.client.logout()
        first = self.client.post("/comptes/inscription/", {
            "email": "sans-mail@example.com", "password": "motdepasse10", "birth_date_year": "1991", "birth_date_month": "3", "birth_date_day": "3",
            "display_name": "Sans", "kind": "single", "accept": "on",
        })
        self.assertEqual(first.status_code, 200)
        self.assertFalse(OutboundEmail.objects.filter(kind="verify").exists())
        self.client.logout()
        self.as_staff(admin)
        saved = self.client.post("/gestion/configuration/", {
            "onglet": "courriels", "action": "save", "send_signup_email": "1",
        })
        self.assertEqual(saved.status_code, 302)
        self.assertEqual(SiteSetting.get("send_signup_email", "0"), "1")
        self.client.logout()
        second = self.client.post("/comptes/inscription/", {
            "email": "avec-mail@example.com", "password": "motdepasse10", "birth_date_year": "1991", "birth_date_month": "3", "birth_date_day": "3",
            "display_name": "Avec", "kind": "single", "accept": "on",
        })
        self.assertEqual(second.status_code, 200)
        mail = OutboundEmail.objects.get(kind="verify", to_email="avec-mail@example.com")
        self.assertIn("/comptes/verifier/", mail.body)
        self.assertEqual(OutboundEmail.objects.filter(kind="verify").count(), 1)

    def test_private_media_can_be_attached_from_the_thread(self):
        owner, me = self.make("partage@example.com", "Partage")
        other, them = self.make("recoit@example.com", "Recoit")
        private = Photo(profile=me, is_private=True, moderation_status="approved", title="Soiree")
        private.image.save("p.jpg", jpeg(), save=True)
        video = Photo(profile=me, is_private=True, moderation_status="approved", media_type="video", title="Clip", processing_status="ready")
        video.image.save("v.jpg", jpeg(), save=True)
        hidden = Photo(profile=me, is_private=True, moderation_status="approved", role="certification", title="Secret")
        hidden.image.save("c.jpg", jpeg(), save=True)
        create_like(me, them)
        match, _ = create_like(them, me)
        self.client.force_login(owner)
        renamed = self.client.post(f"/moi/photos/{private.id}/titre/", {"title": "Soiree privee"})
        self.assertEqual(renamed.status_code, 302)
        private.refresh_from_db()
        self.assertEqual(private.title, "Soiree privee")
        page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(page, "attach-item")
        self.assertContains(page, "Soiree privee")
        self.assertContains(page, "Clip")
        self.assertContains(page, f"/photos/{private.id}/?thumb=1")
        self.assertNotContains(page, f"#{private.id}")
        self.assertNotContains(page, "Secret")
        sent = self.client.post(f"/messages/{match.id}/", {"body": "pour toi", "photo": str(private.id)})
        self.assertEqual(sent.status_code, 302)
        self.assertTrue(PhotoGrant.objects.filter(photo=private, grantee=them, revoked_at__isnull=True).exists())
        self.client.force_login(other)
        seen = self.client.get(f"/messages/{match.id}/")
        self.assertContains(seen, f"/photos/{private.id}/")
        self.assertEqual(self.client.get(f"/photos/{private.id}/").status_code, 200)
        self.assertEqual(self.client.get(f"/photos/{hidden.id}/").status_code, 403)


class V6CorrectionTests(TestCase):
    make = RulesTests.make

    def test_match_profile_opens_from_the_thread_and_the_inbox(self):
        user_a, a = self.make("fiche-a@example.com", "FicheA")
        user_b, b = self.make("fiche-b@example.com", "FicheB")
        create_like(a, b)
        match, _ = create_like(b, a)
        self.client.force_login(user_a)
        thread = self.client.get(f"/messages/{match.id}/")
        self.assertContains(thread, f'href="/profil/{b.id}/"')
        self.assertContains(thread, f">{a.display_name}" if False else f">{b.display_name}</a>")
        inbox = self.client.get("/messages/")
        self.assertContains(inbox, f'href="/profil/{b.id}/"')
        self.assertContains(inbox, f'href="/messages/{match.id}/"')
        listed = self.client.get("/matchs/")
        self.assertContains(listed, f'href="/profil/{b.id}/"')
        opened = self.client.get(f"/profil/{b.id}/")
        self.assertEqual(opened.status_code, 200)
        self.assertContains(opened, b.display_name)

    def test_travel_uses_the_destination_then_returns_home(self):
        today = timezone.localdate()
        user, me = self.make("voyage@example.com", "Voyageur")
        other, dest = self.make("montreal@example.com", "Montrealais")
        _home_user, home = self.make("lyon-home@example.com", "Lyonais")
        me.city, me.lat, me.lng = "Lyon", 45.75, 4.85
        me.save(update_fields=["city", "lat", "lng"])
        dest.city, dest.lat, dest.lng = "Montreal", 45.50, -73.57
        dest.save(update_fields=["city", "lat", "lng"])
        home.city, home.lat, home.lng = "Lyon", 45.76, 4.86
        home.save(update_fields=["city", "lat", "lng"])
        self.client.force_login(user)
        form = self.client.get("/moi/")
        self.assertContains(form, "En voyage")
        saved = self.client.post("/moi/voyage/", {
            "city": "Montreal", "country": "CA", "city_lat": "45.50", "city_lng": "-73.57",
            "start": (today - timedelta(days=1)).isoformat(),
            "end": (today + timedelta(days=2)).isoformat(),
        })
        self.assertEqual(saved.status_code, 302)
        me.refresh_from_db()
        self.assertEqual(me.city, "Lyon")
        self.assertAlmostEqual(me.lat, 45.75)
        self.assertEqual(me.travel_city, "Montreal")
        page = self.client.get(f"/profil/{me.id}/")
        self.assertContains(page, "En voyage")
        self.assertContains(page, "Montreal")
        self.assertContains(page, "origine")
        self.assertContains(page, "Lyon")
        self.client.force_login(other)
        near = self.client.get("/decouvrir/?city=Montreal")
        self.assertContains(near, "Voyageur")
        self.assertContains(near, "En voyage")
        self.client.force_login(user)
        away = self.client.get("/decouvrir/?max_km=80")
        self.assertContains(away, "Montrealais")
        self.assertNotContains(away, "Lyonais")
        me.travel_end = today - timedelta(days=1)
        me.save(update_fields=["travel_end"])
        back = self.client.get("/decouvrir/?max_km=80")
        self.assertContains(back, "Lyonais")
        self.assertNotContains(back, "Montrealais")
        self.client.force_login(other)
        gone = self.client.get("/decouvrir/?city=Montreal")
        self.assertNotContains(gone, "Voyageur")
        self.client.force_login(user)
        quiet = self.client.get(f"/profil/{me.id}/")
        self.assertNotContains(quiet, "En voyage")

    def test_saint_sauveur_and_cities_of_ten_thousand(self):
        import sqlite3
        from django.conf import settings

        res = self.client.get("/villes/?q=Saint-Sauveur")
        self.assertEqual(res.status_code, 200)
        rows = [row for row in res.json()["results"] if row["country"] == "CA" and row["name"] == "Saint-Sauveur"]
        self.assertTrue(rows)
        self.assertGreater(rows[0]["lat"], 45)
        self.assertLess(rows[0]["lng"], -70)
        path = settings.BASE_DIR / "swingapp" / "cities.sqlite"
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            big = con.execute("select count(*) from cities where pop >= 10000").fetchone()[0]
            mid = con.execute("select count(*) from cities where pop >= 5000 and pop < 10000").fetchone()[0]
        finally:
            con.close()
        self.assertGreater(big, 40000)
        self.assertGreater(mid, 1000)
        page = self.client.get("/moi/")
        self.client.force_login(self.make("ville-help@example.com", "Villes")[0])
        page = self.client.get("/moi/")
        self.assertContains(page, "5 000")


class V7BusinessTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def _enable(self, plan="97531", push="86420"):
        admin, _ = self.make("root-biz@example.com", "RootBiz")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        self.client.post("/gestion/entreprises/", {
            "action": "settings", "businesses_enabled": "1",
            "business_plan_price": plan, "business_push_price": push,
        })
        self.client.logout()
        return admin

    def _signup(self, email="club@example.com", name="ClubNocturne"):
        res = self.client.post("/entreprises/inscription/", {
            "email": email, "password": "motdepasse10", "birth": "1988-04-04",
            "name": name, "category": "club", "city": "Lyon", "lat": "45.75", "lng": "4.85",
            "address": "1 quai", "description": "Soirees", "website": "https://club.example",
            "ticket_url": "https://tickets.example/club", "accept": "on",
        })
        self.assertEqual(res.status_code, 302)
        return get_user_model().objects.get(email=email)

    def test_module_stays_off_and_out_of_discover(self):
        member, me = self.make("membre-biz@example.com", "MembreBiz")
        self.client.force_login(member)
        self.assertEqual(self.client.get("/entreprises/").status_code, 404)
        self.assertEqual(self.client.get("/evenements/").status_code, 404)
        self.client.logout()
        staff, _ = self.make("staff-off@example.com", "StaffOff")
        staff.is_staff = True
        staff.is_superuser = True
        staff.save()
        self.as_staff(staff)
        off = self.client.get("/gestion/entreprises/")
        self.assertContains(off, "Activer le module Entreprises")
        self.assertNotIn(b"checked", off.content.split(b"businesses_enabled")[1][:80])
        self.client.logout()
        admin = self._enable()
        owner = self._signup()
        biz_profile = owner.profile
        self.assertEqual(biz_profile.kind, "business")
        self.client.force_login(member)
        page = self.client.get("/decouvrir/")
        self.assertNotContains(page, "ClubNocturne")
        from swingapp.services import AccessError, create_like
        with self.assertRaises(AccessError):
            create_like(me, biz_profile)
        self.client.force_login(owner)
        self.assertEqual(self.client.get("/decouvrir/").status_code, 302)
        self.client.logout()
        self.as_staff(admin)
        listed = self.client.get("/gestion/entreprises/")
        self.assertContains(listed, "Activer le module Entreprises")
        self.assertIn(b"checked", listed.content.split(b"businesses_enabled")[1][:80])

    def test_event_rsvp_verification_and_paid_push(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from swingapp.models import BusinessAccount, BusinessInvoice, CampaignDelivery, Event, EventRsvp, Notice, SiteSetting

        admin = self._enable()
        owner = self._signup()
        biz = BusinessAccount.objects.get(profile=owner.profile)
        self.client.force_login(owner)
        doc = self.client.post("/entreprises/moi/justificatif/", {"document": SimpleUploadedFile("kbis.pdf", b"%PDF-1.4", content_type="application/pdf")})
        self.assertEqual(doc.status_code, 302)
        self.client.logout()
        self.as_staff(admin)
        document = biz.documents.get()
        self.client.post("/gestion/entreprises/", {"action": "doc", "document": str(document.id), "decision": "approve"})
        biz.refresh_from_db()
        self.assertTrue(biz.verified)
        self.client.force_login(owner)
        self.assertNotContains(self.client.get("/entreprises/moi/"), "Entreprise vérifiée")
        self.client.logout()
        self.as_staff(admin)
        self.client.post("/gestion/entreprises/", {"action": "plan", "business": str(biz.id), "plan_status": "active", "plan_until": "2027-01-01"})
        self.assertTrue(BusinessInvoice.objects.filter(business=biz, kind="plan", amount=97531).exists())
        self.client.force_login(owner)
        self.assertContains(self.client.get("/entreprises/moi/"), "Entreprise vérifiée")
        saved = self.client.post("/entreprises/moi/evenement/", {
            "title": "Nuit bleue", "category": "party",
            "starts": "2026-11-10T20:00", "ends": "2026-11-11T02:00",
            "place": "Salle 1", "city": "Lyon", "lat": "45.75", "lng": "4.85",
            "description": "Programme", "practical": "Code : noir", "price_note": "40 euros sur place",
            "ticket_url": "https://tickets.example/nuit", "capacity": "1", "published": "1",
        })
        self.assertEqual(saved.status_code, 302)
        self.assertNotContains(self.client.get("/entreprises/moi/"), "86420")
        self.assertNotContains(self.client.get(f"/entreprises/{owner.profile.id}/"), "97531")
        near_user, near = self.make("pres@example.com", "ZoeUnique")
        near.lat, near.lng = 45.76, 4.86
        near.desires = "party"
        near.save()
        near.user.promo_consent = True
        near.user.save(update_fields=["promo_consent"])
        far_user, far = self.make("loin@example.com", "Loin")
        far.lat, far.lng = 48.86, 2.35
        far.save()
        far.user.promo_consent = True
        far.user.save(update_fields=["promo_consent"])
        other_user, _other = self.make("deux@example.com", "Deuxieme")
        self.client.force_login(near_user)
        listing = self.client.get("/evenements/?city=Lyon&category=party&date=2026-11-10")
        self.assertContains(listing, "Nuit bleue")
        event_id = Event.objects.get(title="Nuit bleue").id
        page = self.client.get(f"/evenements/{event_id}/")
        self.assertContains(page, "Je participe")
        self.assertContains(page, "noir")
        first = self.client.post(f"/evenements/{event_id}/inscription/", {"status": "going", "anonymous": "1"})
        self.assertEqual(first.status_code, 302)
        self.assertEqual(EventRsvp.objects.get(user=near_user).status, "going")
        self.client.force_login(other_user)
        self.client.post(f"/evenements/{event_id}/inscription/", {"status": "going"})
        self.assertEqual(EventRsvp.objects.get(user=other_user).status, "waitlist")
        self.client.force_login(owner)
        guests = self.client.get(f"/entreprises/moi/evenements/{event_id}/invites/")
        self.assertContains(guests, "Membre anonyme")
        self.assertNotContains(guests, "ZoeUnique")
        self.assertNotContains(guests, "pres@example.com")
        self.assertNotContains(guests, "deux@example.com")
        preview = self.client.post("/entreprises/moi/push/", {
            "action": "preview", "event": event_id, "city": "Lyon", "lat": "45.75", "lng": "4.85",
            "radius": "40", "category": "party", "body": "Nuit bleue ce soir",
        })
        self.assertContains(preview, "1 membres seront avisés")
        sent = self.client.post("/entreprises/moi/push/", {
            "action": "send", "event": event_id, "city": "Lyon", "lat": "45.75", "lng": "4.85",
            "radius": "40", "category": "party", "body": "Nuit bleue ce soir",
        })
        self.assertEqual(sent.status_code, 302)
        self.assertEqual(CampaignDelivery.objects.filter(user=near_user).count(), 1)
        self.assertFalse(CampaignDelivery.objects.filter(user=far_user).exists())
        self.assertTrue(BusinessInvoice.objects.filter(kind="push", amount=86420).exists())
        self.assertTrue(Notice.objects.filter(profile=near, body__contains="Nuit bleue").exists())
        self.client.logout()
        self.client.force_login(near_user)
        closed = self.client.get(f"/evenements/{event_id}/billets/")
        self.assertEqual(closed.status_code, 404)
        self.client.logout()
        self.as_staff(admin)
        self.client.post("/gestion/entreprises/", {"action": "plan", "business": str(biz.id), "plan_status": "canceled"})
        self.client.force_login(owner)
        self.assertNotContains(self.client.get("/entreprises/moi/"), "Entreprise vérifiée")
        self.client.logout()
        self.as_staff(admin)
        self.client.post("/gestion/entreprises/", {"action": "plan", "business": str(biz.id), "plan_status": "active"})
        self.client.post("/gestion/entreprises/", {
            "action": "settings", "ticketing_enabled": "1", "businesses_enabled": "1",
            "business_plan_price": "97531", "business_push_price": "86420",
        })
        self.client.force_login(near_user)
        standby = self.client.get(f"/evenements/{event_id}/billets/")
        self.assertEqual(standby.status_code, 200)
        self.assertContains(standby, "Aucun paiement")
        self.assertFalse(BusinessInvoice.objects.filter(kind="ticket").exists())
        self.assertEqual(SiteSetting.get("ticketing_enabled", "0"), "1")


class V8CorrectionTests(TestCase):
    make = RulesTests.make

    def test_labels_couple_tab_and_like_redirect(self):
        user, profile = self.make("solo-v8@example.com", "Solo")
        self.client.force_login(user)
        page = self.client.get("/moi/")
        self.assertNotContains(page, 'data-tab="couple"')
        self.assertContains(page, "Je recherche une relation sérieuse")
        es = self.client.get("/moi/?lang=es")
        self.assertContains(es, "Fecha de nacimiento de tu pareja")
        self.assertContains(es, "Seudónimo de tu pareja")
        from swingapp.i18n import t
        self.assertEqual(t("es", "partner_consent_label"), "Consentimiento de tu pareja")
        self.assertEqual(t("es", "partner_gender"), "Género de tu pareja")
        self.assertEqual(t("es", "partner_email"), "Correo de tu pareja")
        self.assertNotContains(es, "Fecha de nacimiento de la pareja")
        other, them = self.make("fiche-v8@example.com", "Fiche")
        discover = self.client.get("/decouvrir/?lang=fr")
        self.assertContains(discover, "Voir la fiche")
        self.assertContains(discover, "Âge minimum")
        self.assertContains(discover, "Âge maximum")
        self.assertNotContains(discover, "Voir ma fiche")
        self.assertNotContains(discover, "Date de naissance min")
        detail = self.client.get(f"/profil/{them.id}/?lang=fr")
        self.assertContains(detail, 'data-redirect="/decouvrir/"')
        js = __import__("pathlib").Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("data-redirect", js)
        self.assertIn("1500", js)
        upload = __import__("pathlib").Path("static/js/upload.js").read_text(encoding="utf-8")
        self.assertNotIn("Choisissez une vidéo", upload)
        self.assertIn("chooseVideo", upload)
        settings = self.client.get("/parametres/?lang=en")
        self.assertContains(settings, "Notifications on this device")
        self.assertContains(settings, "data-no-support")
        self.assertNotContains(settings, "Notifications sur cet appareil")
        profile.kind = "couple"
        profile.save(update_fields=["kind"])
        couple = self.client.get("/moi/")
        self.assertContains(couple, 'data-tab="couple"')

    def test_serious_relationship_is_saved_and_filters_discover(self):
        user, me = self.make("serieux@example.com", "Serieux")
        _other, casual = self.make("casual-v8@example.com", "Casual")
        viewer, _view = self.make("regard-v8@example.com", "Regard")
        self.client.force_login(user)
        saved = self.client.post("/moi/", {
            "display_name": "Serieux", "kind": "single", "city": "Lyon", "bio": "bio",
            "visibility": "public", "seeking_serious": "on",
        })
        self.assertEqual(saved.status_code, 302)
        me.refresh_from_db()
        self.assertTrue(me.seeking_serious)
        self.assertFalse(casual.seeking_serious)
        page = self.client.get(f"/profil/{me.id}/")
        self.assertContains(page, "Recherche une relation sérieuse")
        self.client.force_login(viewer)
        found = self.client.get("/decouvrir/?serious=1")
        self.assertContains(found, "Serieux")
        self.assertNotContains(found, "Casual")
        en = self.client.get("/decouvrir/?lang=en&serious=1")
        self.assertContains(en, "Serious relationship only")
        self.assertContains(en, "Looking for a serious relationship")



class V9BusinessSalesTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def _ready(self):
        admin, _ = self.make("sales-root@example.com", "SalesRoot")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        self.client.post("/gestion/entreprises/", {
            "action": "settings", "businesses_enabled": "1",
            "business_plan_price": "10000", "business_push_price": "2000",
        })
        self.client.logout()
        return admin

    def test_business_signup_has_no_birth_date_and_members_still_do(self):
        self._ready()
        res = self.client.post("/entreprises/inscription/", {
            "email": "societe@example.com", "password": "motdepasse10",
            "name": "Societe", "category": "shop", "city": "Lyon", "accept": "on",
            "address": "12 rue des pins",
        })
        self.assertEqual(res.status_code, 302)
        user = get_user_model().objects.get(email="societe@example.com")
        self.assertIsNone(user.birth_date)
        form = self.client.get("/entreprises/inscription/")
        self.assertNotContains(form, 'name="birth"')
        young = self.client.post("/comptes/inscription/", {
            "email": "mineur-v9@example.com", "password": "motdepasse10", "birth_date_year": "2015", "birth_date_month": "1", "birth_date_day": "1",
        })
        self.assertEqual(young.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email="mineur-v9@example.com").exists())

    def test_push_targets_kinds_and_coupon_and_names_the_business(self):
        from swingapp.models import BusinessAccount, BusinessPush, Notice
        admin = self._ready()
        self.client.post("/entreprises/inscription/", {
            "email": "pub@example.com", "password": "motdepasse10", "name": "PubClub",
            "category": "club", "city": "Lyon", "lat": "45.75", "lng": "4.85", "accept": "on",
        })
        owner = get_user_model().objects.get(email="pub@example.com")
        biz = BusinessAccount.objects.get(profile=owner.profile)
        self.as_staff(admin)
        self.client.post("/gestion/entreprises/", {"action": "plan", "business": str(biz.id), "plan_status": "active"})
        self.client.logout()
        solo_user, solo = self.make("solo-push@example.com", "SoloPush")
        solo.kind = "single"
        solo.lat, solo.lng = 45.76, 4.86
        solo.save()
        solo.user.promo_consent = True
        solo.user.save(update_fields=["promo_consent"])
        pair_user, pair = self.make("pair-push@example.com", "PairPush")
        pair.kind = "couple"
        pair.lat, pair.lng = 45.76, 4.86
        pair.save()
        pair.user.promo_consent = True
        pair.user.save(update_fields=["promo_consent"])
        self.client.force_login(owner)
        page = self.client.get("/entreprises/moi/push/")
        self.assertContains(page, "Membres ciblés")
        self.assertContains(page, "Rabais / coupon")
        self.assertNotContains(page, "Sauna")
        preview = self.client.post("/entreprises/moi/push/", {
            "action": "preview", "purpose": "coupon", "kind": "single",
            "city": "Lyon", "lat": "45.75", "lng": "4.85", "radius": "40",
            "promo_code": "NUIT10", "offer_details": "Moins 10", "offer_ends": "2026-12-01",
            "body": "Coupon du soir",
        })
        self.assertContains(preview, "1 membres seront avisés")
        sent = self.client.post("/entreprises/moi/push/", {
            "action": "send", "purpose": "coupon", "kind": "single",
            "city": "Lyon", "lat": "45.75", "lng": "4.85", "radius": "40",
            "promo_code": "NUIT10", "offer_details": "Moins 10", "offer_ends": "2026-12-01",
            "body": "Coupon du soir",
        })
        self.assertEqual(sent.status_code, 302)
        push = BusinessPush.objects.get()
        self.assertEqual(push.purpose, "coupon")
        self.assertEqual(push.promo_code, "NUIT10")
        self.assertEqual(push.target_kinds, "single")
        note = Notice.objects.get(profile=solo)
        self.assertIn("PubClub", note.body)
        self.assertIn("Coupon du soir", note.body)
        self.assertFalse(Notice.objects.filter(profile=pair).exists())
        self.client.force_login(solo_user)
        self.assertContains(self.client.get("/notifications/"), "PubClub")

    def test_payment_link_commission_crm_map_and_seller_limits(self):
        from unittest.mock import patch
        from django.contrib.auth.models import Group
        from swingapp.models import BusinessAccount, BusinessInvoice, OutboundEmail, Prospect, SiteSetting
        admin = self._ready()
        self.client.post("/entreprises/inscription/", {
            "email": "map@example.com", "password": "motdepasse10", "name": "MapClub",
            "category": "club", "city": "Lyon", "accept": "on", "address": "12 rue des pins",
        })
        owner = get_user_model().objects.get(email="map@example.com")
        biz = BusinessAccount.objects.get(profile=owner.profile)
        self.as_staff(admin)
        self.client.post("/gestion/vendeurs/", {"email": "vendeur@example.com", "password": "motdepasse10"})
        seller = get_user_model().objects.get(email="vendeur@example.com")
        self.assertTrue(seller.groups.filter(name="Vendeurs").exists())
        self.assertTrue(Group.objects.filter(name="Vendeurs").exists())
        biz.sold_by = seller
        biz.plan_status = "active"
        biz.save(update_fields=["sold_by", "plan_status"])
        invoice = BusinessInvoice.objects.create(business=biz, kind="plan", amount=10000, status="due", note="abonnement", sold_by=seller)
        due = BusinessInvoice.objects.create(business=biz, kind="push", amount=2000, status="due", note="push", sold_by=seller)
        SiteSetting.objects.update_or_create(key="business_pay_provider", defaults={"value": "stripe"})
        SiteSetting.objects.update_or_create(key="business_stripe_secret", defaults={"value": "sk_test_dummy"})
        SiteSetting.objects.update_or_create(key="business_currency", defaults={"value": "CAD"})
        link = type("Link", (), {"url": "https://pay.stripe.test/abc", "id": "plink_abc"})()
        with patch("stripe.PaymentLink.create", return_value=link):
            created = self.client.post(f"/gestion/entreprises/factures/{invoice.id}/lien/")
        self.assertEqual(created.status_code, 302)
        invoice.refresh_from_db()
        self.assertEqual(invoice.payment_url, "https://pay.stripe.test/abc")
        self.assertNotContains(self.client.get("/entreprises/"), "10000")
        mailed = self.client.post(f"/gestion/entreprises/factures/{invoice.id}/courriel/")
        self.assertEqual(mailed.status_code, 302)
        self.assertTrue(OutboundEmail.objects.filter(to_email="map@example.com", body__contains="pay.stripe.test").exists())
        self.as_staff(seller)
        denied = self.client.post(f"/gestion/entreprises/factures/{invoice.id}/payee/")
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.client.get("/gestion/membres/").status_code, 403)
        self.assertEqual(self.client.post("/gestion/entreprises/", {"action": "settings", "businesses_enabled": "0"}).status_code, 403)
        menu = self.client.get("/gestion/entreprises/")
        self.assertContains(menu, "CRM")
        self.assertNotContains(menu, "Médias")
        self.client.post("/gestion/crm/", {"name": "Sauna Nord", "email": "nord@example.com", "status": "new", "category": "sauna"})
        Prospect.objects.create(name="Autre", email="autre@example.com", seller=admin, status="new")
        listing = self.client.get("/gestion/crm/")
        self.assertContains(listing, "Sauna Nord")
        self.assertNotContains(listing, "Autre")
        prospect = Prospect.objects.get(name="Sauna Nord")
        self.client.post(f"/gestion/crm/{prospect.id}/convertir/")
        prospect.refresh_from_db()
        self.assertEqual(prospect.status, "client")
        self.assertEqual(prospect.business.sold_by_id, seller.id)
        self.assertIsNone(prospect.business.profile.user.birth_date)
        from swingapp.businesses import commission_rows, settle_invoice_from_stripe
        self.assertEqual(commission_rows(seller), [])
        self.assertTrue(settle_invoice_from_stripe({"id": "cs_1", "metadata": {"invoice_id": str(invoice.id)}}))
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, "paid")
        due.refresh_from_db()
        self.assertEqual(due.status, "due")
        rows = commission_rows(seller)
        self.assertEqual(rows[0]["paid"], 10000)
        self.assertEqual(rows[0]["due"], 5000)
        self.as_staff(admin)
        self.client.post("/gestion/commissions/", {"seller": str(seller.id), "period": rows[0]["period"]})
        self.assertTrue(commission_rows(seller)[0]["paid_out"])
        self.as_staff(seller)
        self.assertEqual(self.client.post("/gestion/commissions/", {"seller": str(seller.id), "period": rows[0]["period"]}).status_code, 403)
        member, _ = self.make("lecteur-map@example.com", "Lecteur")
        self.client.force_login(member)
        page = self.client.get(f"/entreprises/{owner.profile.id}/")
        self.assertContains(page, "https://www.google.com/maps?q=")
        self.assertContains(page, "output=embed")
        biz.address = ""
        biz.save(update_fields=["address"])
        self.assertNotContains(self.client.get(f"/entreprises/{owner.profile.id}/"), "google.com/maps")
        with self.settings(STRIPE_WEBHOOK_SECRET="whsec_test"):
            payload = {"id": "evt_biz", "type": "checkout.session.completed", "data": {"object": {"id": "cs_due", "metadata": {"invoice_id": str(due.id)}}}}
            with patch("stripe.Webhook.construct_event", return_value=payload):
                hook = self.client.post("/paiements/webhook/", data=b"{}", content_type="application/json", HTTP_STRIPE_SIGNATURE="sig")
        self.assertEqual(hook.status_code, 200)
        due.refresh_from_db()
        self.assertEqual(due.status, "paid")



class V10EmailVerificationTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def _switch(self, on):
        from swingapp.models import SiteSetting
        SiteSetting.objects.update_or_create(key="send_signup_email", defaults={"value": "1" if on else "0"})

    def _signup(self, email="nouveau@example.com", lang="fr"):
        if lang != "fr":
            self.client.get(f"/comptes/inscription/?lang={lang}")
        return self.client.post("/comptes/inscription/", {
            "email": email, "password": "motdepasse10", "birth_date_year": "1992", "birth_date_month": "2", "birth_date_day": "2",
            "display_name": "Neuf", "kind": "single", "accept": "on",
        })

    def test_switch_sends_mail_blocks_login_and_resend_waits(self):
        from swingapp.models import EmailToken
        self._switch(False)
        off = self._signup("sans-verif@example.com")
        self.assertEqual(off.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertNotContains(off, "dev_link")
        self.assertNotContains(off, "/comptes/verifier/")
        self.assertFalse(OutboundEmail.objects.filter(kind="verify").exists())
        self.client.logout()
        again = self.client.post("/comptes/connexion/", {"email": "sans-verif@example.com", "password": "motdepasse10"})
        self.assertEqual(again.status_code, 302)
        self.client.logout()
        self._switch(True)
        sent = self._signup("avec-verif@example.com")
        self.assertEqual(sent.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertContains(sent, "courriel de confirmation")
        self.assertNotContains(sent, "/comptes/verifier/")
        self.assertNotIn("dev_link", __import__("pathlib").Path("templates/verify_sent.html").read_text(encoding="utf-8"))
        mail = OutboundEmail.objects.get(kind="verify", to_email="avec-verif@example.com")
        self.assertIn("/comptes/verifier/", mail.body)
        self.assertIn("Bienvenue sur iSwing !", mail.body)
        self.assertIn("/brand/icons/logo.png", mail.html_body)
        self.assertIn("Confirmer mon adresse", mail.html_body)
        self.assertIn("Info@iswing.live", mail.html_body)
        self.assertIn("/legal/conditions/", mail.html_body)
        self.assertIn("ignorez ce courriel", mail.html_body)
        blocked = self.client.post("/comptes/connexion/", {"email": "avec-verif@example.com", "password": "motdepasse10"})
        self.assertEqual(blocked.status_code, 302)
        self.assertIn("/moi/", blocked.url)
        self.assertIn("_auth_user_id", self.client.session)
        too_soon = self.client.post("/comptes/verifier/renvoyer/", {"email": "avec-verif@example.com"})
        self.assertContains(too_soon, "deux minutes")
        self.assertEqual(OutboundEmail.objects.filter(kind="verify", to_email="avec-verif@example.com").count(), 1)
        token = EmailToken.objects.filter(user__email="avec-verif@example.com", purpose="verify").order_by("-id").first()
        token.created_at = timezone.now() - timedelta(minutes=3)
        token.save(update_fields=["created_at"])
        resent = self.client.post("/comptes/verifier/renvoyer/", {"email": "avec-verif@example.com"})
        self.assertContains(resent, "nouveau courriel")
        self.assertEqual(OutboundEmail.objects.filter(kind="verify", to_email="avec-verif@example.com").count(), 2)
        link = mail.body.split("/comptes/verifier/")[1].split()[0].strip()
        opened = self.client.get("/comptes/verifier/" + link)
        # Le lien de vérification connecte automatiquement (302) au lieu d'afficher une page statique.
        self.assertEqual(opened.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        user = get_user_model().objects.get(email="avec-verif@example.com")
        self.assertIsNotNone(user.email_verified_at)

    def test_verification_mail_is_translated(self):
        from swingapp.integrations import render_transactional
        base = "https://iswing.example"
        with self.settings(ISWING_PUBLIC_BASE_URL=base, REPORT_INBOX="Info@iswing.live"):
            _subject, text, html = render_transactional("verify", "en", link=base + "/comptes/verifier/abc/")
            self.assertIn("Welcome to iSwing!", text)
            self.assertIn("Welcome to iSwing!", html)
            self.assertIn("Confirm my address", html)
            self.assertIn(base + "/brand/icons/logo.png", html)
            self.assertIn("/legal/confidentialite/", html)
            self.assertNotIn("Bienvenue", html)
            self.assertNotIn("Bienvenido", html)
            _subject, text, html = render_transactional("verify", "es", link=base + "/comptes/verifier/abc/")
            self.assertIn("¡Bienvenido a iSwing!", html)
            self.assertIn("Confirmar mi dirección", html)
            self.assertIn("ignore este correo", html)
            self.assertNotIn("Welcome", html)
            self.assertNotIn("Bienvenue", html)
            _subject, text, html = render_transactional("verify", "fr", link=base + "/comptes/verifier/abc/")
            self.assertIn("Bienvenue sur iSwing !", html)
            self.assertNotIn("Welcome to iSwing", html)



class V11TransactionalMailTests(TestCase):
    make = RulesTests.make

    def test_password_reset_is_sent_once_and_translated(self):
        buttons = {
            "fr": "Choisir un nouveau mot de passe",
            "en": "Choose a new password",
            "es": "Elegir una nueva contraseña",
        }
        for lang, button in buttons.items():
            user, _ = self.make(f"reset-{lang}@example.com", "Reset")
            self.client.get(f"/comptes/mot-de-passe/?lang={lang}")
            first = self.client.post("/comptes/mot-de-passe/", {"email": user.email})
            self.assertEqual(first.status_code, 200)
            self.assertNotContains(first, "dev_link")
            second = self.client.post("/comptes/mot-de-passe/", {"email": user.email})
            self.assertEqual(second.status_code, 200)
            mails = OutboundEmail.objects.filter(kind="reset", to_email=user.email)
            self.assertEqual(mails.count(), 1)
            mail = mails.get()
            self.assertIn(button, mail.html_body)
            self.assertIn("/brand/icons/logo.png", mail.html_body)
            self.assertIn("/legal/conditions/", mail.html_body)
            self.assertIn("/comptes/mot-de-passe/", mail.body)
            token = mail.body.split("/comptes/mot-de-passe/")[1].split()[0]
            self.assertNotContains(first, token)
            self.assertTrue(mail.html_body.strip())
        missing = self.client.post("/comptes/mot-de-passe/", {"email": "absent@example.com"})
        known = self.client.post("/comptes/mot-de-passe/", {"email": "reset-fr@example.com"})
        self.assertEqual(missing.status_code, known.status_code)
        self.assertNotContains(missing, "absent@example.com")
        self.assertFalse(OutboundEmail.objects.filter(to_email="absent@example.com").exists())
        with self.settings(DEBUG=False):
            quiet = self.client.post("/comptes/mot-de-passe/", {"email": "reset-fr@example.com"})
            fr_token = OutboundEmail.objects.get(kind="reset", to_email="reset-fr@example.com").body.split("/comptes/mot-de-passe/")[1].split()[0].strip("/")
            self.assertNotContains(quiet, "dev_link")
            self.assertNotIn(fr_token, quiet.content.decode())

    def test_invite_partner_and_billing_share_the_branded_layout(self):
        from swingapp.integrations import render_transactional

        expected = {
            "invite": {"fr": "Activer mon compte", "en": "Activate my account", "es": "Activar mi cuenta"},
            "partner": {"fr": "Confirmer ma participation", "en": "Confirm my participation", "es": "Confirmar mi participación"},
            "billing": {"fr": "Payer la facture", "en": "Pay the invoice", "es": "Pagar la factura"},
        }
        foreign = {
            "fr": ("Activate my account", "Pay the invoice", "Welcome to iSwing"),
            "en": ("Activer mon compte", "Payer la facture", "Bienvenido"),
            "es": ("Activer mon compte", "Pay the invoice", "Bienvenue"),
        }
        with self.settings(ISWING_PUBLIC_BASE_URL="https://iswing.example", REPORT_INBOX="Info@iswing.live"):
            for code, labels in expected.items():
                for lang, label in labels.items():
                    _subject, text, html = render_transactional(code, lang, link="https://iswing.example/suite/")
                    self.assertIn(label, html)
                    self.assertIn("https://iswing.example/brand/icons/logo.png", html)
                    self.assertIn("Info@iswing.live", html)
                    self.assertIn("https://iswing.example/suite/", text)
                    self.assertTrue(html.strip())
                    for other in foreign[lang]:
                        self.assertNotIn(other, html)
            _subject, text, html = render_transactional("verify", "fr", link="https://iswing.example/comptes/verifier/abc/")
            self.assertIn("Bienvenue sur iSwing !", html)
            self.assertIn("Confirmer mon adresse", html)
            self.assertNotIn("Choisir un nouveau mot de passe", html)



class V12CoupleCardTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def test_pending_partner_email_opens_the_invite_instead_of_a_second_profile(self):
        _owner, profile = self.make("titulaire@example.com", "couple coquin")
        profile.kind = "couple"
        profile.save(update_fields=["kind"])
        Partner.objects.create(profile=profile, display_name="Eve", birth_date=date(1992, 2, 2), consent_email="eve@example.com")
        before = Profile.objects.count()
        res = self.client.post("/comptes/inscription/", {
            "email": "eve@example.com", "password": "motdepasse10", "birth_date_year": "1991", "birth_date_month": "3", "birth_date_day": "3",
            "display_name": "couple coquin", "kind": "single", "accept": "on",
        })
        self.assertEqual(res.status_code, 302)
        self.assertIn("/invitation/partenaire/", res.url)
        self.assertEqual(Profile.objects.count(), before)
        self.assertFalse(get_user_model().objects.filter(email="eve@example.com").exists())
        page = self.client.get(res.url)
        self.assertContains(page, "deuxième fiche")

    def test_holder_name_is_shown_once_and_old_labels_stay(self):
        from swingapp.services import author_label_for

        owner, profile = self.make("marc@example.com", "couple coquin")
        profile.kind = "couple"
        profile.holder_name = "Marc"
        profile.save(update_fields=["kind", "holder_name"])
        eve = get_user_model().objects.create_user(
            email="eve-seat@example.com", password="motdepasse10", birth_date=date(1992, 2, 2),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        Partner.objects.create(
            profile=profile, display_name="Eve", birth_date=date(1992, 2, 2),
            consent_email="eve-seat@example.com", consent_at=timezone.now(), user=eve,
        )
        self.assertEqual(author_label_for(profile, owner), "couple coquin (Marc)")
        self.assertEqual(author_label_for(profile, eve), "couple coquin (Eve)")
        _viewer, other = self.make("voit@example.com", "Voit")
        match = Match.objects.create(profile_a=profile, profile_b=other)
        Message.objects.create(match=match, sender=profile, body="ancien", author_label="couple coquin")
        profile.holder_name = "Marcel"
        profile.save(update_fields=["holder_name"])
        self.assertEqual(Message.objects.get(body="ancien").author_label, "couple coquin")
        self.assertEqual(author_label_for(profile, owner), "couple coquin (Marcel)")
        profile.holder_name = "Marc"
        profile.save(update_fields=["holder_name"])
        self.client.force_login(other.user)
        page = self.client.get(f"/profil/{profile.id}/")
        self.assertIn("Marc " + chr(38) + "amp; Eve", page.content.decode())
        self.assertContains(page, "couple coquin")
        self.assertNotContains(page, "couple coquin (Eve)")
        # Les matchs actifs sont exclus de Découverte : on ferme le match pour vérifier l'affichage
        match.closed_at = timezone.now()
        match.save(update_fields=["closed_at"])
        deck = self.client.get("/decouvrir/")
        self.assertEqual(deck.content.count("couple coquin".encode()), 1)
        self.assertEqual(Profile.objects.filter(display_name="couple coquin").count(), 1)
        # Et on vérifie l'exclusion : avec le match rouvert, le profil disparaît de Découverte
        match.closed_at = None
        match.save(update_fields=["closed_at"])
        self.assertNotContains(self.client.get("/decouvrir/"), "couple coquin")
        self.client.force_login(eve)
        mine = self.client.get("/moi/")
        self.assertContains(mine, "couple coquin (Eve)")
        self.client.force_login(other.user)
        self.assertNotContains(self.client.get("/decouvrir/"), "couple coquin (Eve)")

    def test_admin_flags_duplicate_pseudos_without_deleting(self):
        admin, _ = self.make("root-dup@example.com", "Root")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        _a, first = self.make("dup-a@example.com", "MemeNom")
        _b, second = self.make("dup-b@example.com", "MemeNom")
        before = Profile.objects.count()
        self.as_staff(admin)
        page = self.client.get("/gestion/membres/?doublons=1")
        self.assertContains(page, "Doublon")
        self.assertContains(page, f"fiche n°{first.id}")
        self.assertContains(page, f"/profil/{second.id}/")
        self.assertEqual(Profile.objects.count(), before)



class V13TravelTabTests(TestCase):
    make = RulesTests.make

    def test_travel_is_a_profile_tab(self):
        user, _profile = self.make("onglet-voyage@example.com", "Tab")
        self.client.force_login(user)
        page = self.client.get("/moi/")
        self.assertContains(page, 'data-tab="voyage"')
        self.assertContains(page, 'data-panel="voyage"')
        self.assertContains(page, 'id="travel-city"')
        self.assertContains(page, 'name="start"')
        self.assertContains(page, 'name="end"')
        self.assertContains(page, ">Voyage</button>")
        self.assertContains(self.client.get("/moi/?lang=es"), ">Viaje</button>")
        self.assertContains(self.client.get("/moi/?lang=en"), ">Travel</button>")
        self.assertNotContains(page, 'id="voyage"')

    def test_password_fields_have_an_eye_and_the_script_toggles_them(self):
        login = self.client.get("/comptes/connexion/")
        self.assertContains(login, 'class="pw-toggle"')
        self.assertContains(login, 'type="password" name="password" required')
        self.assertContains(login, "Afficher le mot de passe")
        register = self.client.get("/comptes/inscription/?lang=es")
        self.assertContains(register, "Mostrar la contraseña")
        self.assertContains(register, "Ocultar la contraseña")
        root = __import__("pathlib").Path("templates")
        for path in root.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            passwords = text.count('type="password"')
            if passwords:
                self.assertEqual(text.count('class="pw-wrap"'), passwords, path)
                self.assertGreaterEqual(text.count("_pw_eye.html"), passwords, path)
        script = __import__("pathlib").Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("pw-toggle", script)
        self.assertIn('input.type = showing ? "text" : "password"', script)
        self.assertIn("aria-pressed", script)

    def test_spanish_profile_word_is_perfil(self):
        from swingapp.i18n import STRINGS, t
        from swingapp.i18n_labels import EXTRA

        self.assertEqual(t("es", "see_profile"), "Ver el perfil")
        self.assertEqual(t("es", "preview_note"), "Así ven su perfil los demás miembros.")
        self.assertEqual(t("es", "public_photo"), "Pública — visible en su perfil")
        self.assertEqual(t("es", "partner_signup_redirect"), "Este correo ya es el de una pareja invitada. Termine la invitación en lugar de crear un segundo perfil.")
        self.assertIn("su perfil", t("es", "media_public_means"))
        self.assertNotIn("ficha", t("es", "media_public_means").lower())
        for table in (STRINGS["es"], EXTRA["es"]):
            for value in table.values():
                self.assertNotIn("ficha", str(value).lower())
        legal = __import__("pathlib").Path("swingapp/legal_seed.py").read_text(encoding="utf-8")
        self.assertIn("Una foto pública es visible en el perfil para los miembros admisibles.", legal)
        self.assertNotIn("en la ficha", legal)

    def test_travel_badge_shows_on_matches_and_inbox_only_while_travelling(self):
        today = timezone.localdate()
        _traveller, away = self.make("loin@example.com", "Voyageur")
        local, home = self.make("ici@example.com", "Local")
        away.travel_city = "Montreal"
        away.travel_country = "CA"
        away.travel_lat = 45.5
        away.travel_lng = -73.57
        away.travel_start = today - timedelta(days=1)
        away.travel_end = today + timedelta(days=2)
        away.save()
        create_like(away, home)
        create_like(home, away)
        self.client.force_login(local)
        self.assertContains(self.client.get("/matchs/"), "En voyage · Montreal")
        self.assertContains(self.client.get("/messages/"), "En voyage · Montreal")
        self.assertContains(self.client.get("/matchs/?lang=en"), "Travelling · Montreal")
        self.assertContains(self.client.get("/messages/?lang=es"), "De viaje · Montreal")
        away.travel_end = today - timedelta(days=1)
        away.save(update_fields=["travel_end"])
        quiet = self.client.get("/matchs/?lang=fr")
        self.assertNotContains(quiet, "En voyage")
        self.assertNotContains(quiet, "Travelling")
        self.assertNotContains(quiet, "De viaje")
        box = self.client.get("/messages/?lang=fr")
        self.assertNotContains(box, "En voyage")
        self.assertNotContains(box, "De viaje")



class V14GpsCityTests(TestCase):
    make = RulesTests.make

    def test_nearest_city_fills_an_empty_place_and_keeps_a_typed_city(self):
        near = self.client.get("/villes/proche/?lat=20.63&lng=-87.07")
        self.assertEqual(near.status_code, 200)
        self.assertEqual(near.json()["name"], "Playa del Carmen")
        self.assertEqual(near.json()["country"], "MX")
        self.assertEqual(self.client.get("/villes/proche/?lat=nope").json(), {})
        self.assertEqual(self.client.get("/villes/proche/").json(), {})

        user, profile = self.make("gps-ville@example.com", "Gps")
        profile.city = "Cancun"
        profile.save(update_fields=["city"])
        self.client.force_login(user)
        saved = self.client.post("/moi/position/", {"lat": "20.63", "lng": "-87.07", "city": ""})
        self.assertEqual(saved.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.city, "Playa del Carmen")
        self.assertAlmostEqual(profile.lat, 20.63)
        self.assertAlmostEqual(profile.lng, -87.07)

        manual = self.client.post("/moi/position/", {"lat": "20.63", "lng": "-87.07", "city": "Cancun"})
        self.assertEqual(manual.status_code, 302)
        profile.refresh_from_db()
        self.assertEqual(profile.city, "Cancun")
        self.assertAlmostEqual(profile.lat, 20.63)

        page = self.client.get("/parametres/")
        self.assertContains(page, "data-wait=")
        self.assertContains(page, "Localisation en cours")
        script = __import__("pathlib").Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("/villes/proche/", script)
        self.assertIn("enableHighAccuracy: true", script)
        self.assertIn("timeout: 30000", script)
        self.assertIn("maximumAge: 0", script)



class V15ProfileGateTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def _switch(self, on):
        from swingapp.models import SiteSetting
        SiteSetting.objects.update_or_create(key="send_signup_email", defaults={"value": "1" if on else "0"})

    def test_unverified_login_opens_the_profile_and_discover_stays_locked(self):
        from django.conf import settings

        self.assertEqual(settings.SECURE_PROXY_SSL_HEADER, ("HTTP_X_FORWARDED_PROTO", "https"))
        self.assertIn(settings.ISWING_PUBLIC_BASE_URL.rstrip("/"), list(settings.CSRF_TRUSTED_ORIGINS))
        self._switch(True)
        self.client.post("/comptes/inscription/", {
            "email": "porte@example.com", "password": "motdepasse10", "birth_date_year": "1992", "birth_date_month": "2", "birth_date_day": "2",
            "display_name": "Porte", "kind": "single", "accept": "on",
        })
        entered = self.client.post("/comptes/connexion/", {"email": "porte@example.com", "password": "motdepasse10"})
        self.assertEqual(entered.status_code, 302)
        self.assertIn("/moi/", entered.url)
        self.assertIn("_auth_user_id", self.client.session)
        locked = self.client.get("/decouvrir/")
        self.assertEqual(locked.status_code, 302)
        self.assertIn("/moi/", locked.url)
        page = self.client.get("/moi/")
        self.assertContains(page, "Profil complété à")
        self.assertContains(page, "Ajouter une photo")
        self.assertContains(page, 'href="/moi/#photos"')
        self.assertContains(page, 'href="/comptes/verifier/"')
        user = get_user_model().objects.get(email="porte@example.com")
        profile = user.profile
        profile.city = "Lyon"
        profile.bio = "Une présentation assez longue."
        profile.save(update_fields=["city", "bio"])
        photo = Photo(profile=profile, is_primary=True, moderation_status="approved")
        photo.image.save("ok.jpg", jpeg(), save=True)
        ready = self.client.get("/decouvrir/")
        self.assertEqual(ready.status_code, 302)
        self.assertIn("/comptes/verifier/", ready.url)
        gate = self.client.get("/comptes/verifier/")
        self.assertContains(gate, "Vérifie ton courriel pour accéder à la Découverte")
        self.assertContains(gate, "Renvoyer le courriel")
        self._switch(False)
        opened = self.client.get("/decouvrir/")
        self.assertEqual(opened.status_code, 200)
        self.client.get("/moi/?lang=en")
        self.assertContains(self.client.get("/moi/?lang=en"), "Profile 80% complete")
        self.assertContains(self.client.get("/moi/?lang=en"), "Verify my email")
        self.assertContains(self.client.get("/moi/?lang=es"), "Verificar mi correo")
        done_user, _done = self.make("complet@example.com", "Complet")
        self.client.force_login(done_user)
        self.assertContains(self.client.get("/moi/"), "Profil complet — bonne visibilité !")

    def test_staff_and_demo_are_not_locked(self):
        staff, profile = self.make("staff-libre@example.com", "Staff")
        staff.is_staff = True
        staff.save(update_fields=["is_staff"])
        profile.city = ""
        profile.bio = ""
        profile.validated_at = None
        profile.save(update_fields=["city", "bio", "validated_at"])
        self.as_staff(staff)
        self.assertEqual(self.client.get("/decouvrir/").status_code, 200)
        self.client.logout()
        demo, shown = self.make("demo-libre@example.com", "Demo")
        demo.is_demo = True
        demo.save(update_fields=["is_demo"])
        shown.city = ""
        shown.validated_at = None
        shown.save(update_fields=["city", "validated_at"])
        self.client.force_login(demo)
        self.assertEqual(self.client.get("/decouvrir/").status_code, 200)

    def test_profile_reminders_follow_the_steps_and_the_switch(self):
        from django.core.management import call_command
        from swingapp.integrations import render_transactional
        from swingapp.models import SiteSetting

        user, profile = self.make("rappel@example.com", "Rappel")
        profile.validated_at = None
        profile.bio = ""
        profile.save(update_fields=["validated_at", "bio"])
        user.date_joined = timezone.now() - timedelta(days=1)
        user.save(update_fields=["date_joined"])
        call_command("send_profile_reminders")
        mail = OutboundEmail.objects.get(kind="reminder", to_email=user.email)
        self.assertIn("Écrire ta présentation", mail.body)
        self.assertIn("/moi/", mail.body)
        self.assertIn("/brand/icons/logo.png", mail.html_body)
        self.assertIn("Ouvrir mon profil", mail.html_body)
        profile.refresh_from_db()
        self.assertEqual(profile.reminder_step, 1)
        call_command("send_profile_reminders")
        self.assertEqual(OutboundEmail.objects.filter(kind="reminder", to_email=user.email).count(), 1)
        profile.validated_at = timezone.now()
        profile.save(update_fields=["validated_at"])
        user.date_joined = timezone.now() - timedelta(days=8)
        user.save(update_fields=["date_joined"])
        call_command("send_profile_reminders")
        self.assertEqual(OutboundEmail.objects.filter(kind="reminder", to_email=user.email).count(), 1)
        other, waiting = self.make("rappel-off@example.com", "Off")
        waiting.validated_at = None
        waiting.bio = ""
        waiting.save(update_fields=["validated_at", "bio"])
        other.date_joined = timezone.now() - timedelta(days=3)
        other.save(update_fields=["date_joined"])
        SiteSetting.objects.update_or_create(key="profile_reminders_enabled", defaults={"value": "0"})
        call_command("send_profile_reminders")
        self.assertFalse(OutboundEmail.objects.filter(kind="reminder", to_email=other.email).exists())
        with self.settings(ISWING_PUBLIC_BASE_URL="https://iswing.example", REPORT_INBOX="Info@iswing.live"):
            _subject, text, html = render_transactional("reminder", "en", link="https://iswing.example/moi/", missing="Add a photo")
            self.assertIn("Open my profile", html)
            self.assertIn("Add a photo", html)
            self.assertNotIn("Ouvrir mon profil", html)
            _subject, text, html = render_transactional("reminder", "es", link="https://iswing.example/moi/", missing="Añadir una foto")
            self.assertIn("Abrir mi perfil", html)
            self.assertIn("Añadir una foto", text)


class StaffVerifyEmailTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def test_staff_can_mark_the_email_verified(self):
        admin, _ = self.make("root-verify@example.com", "Root")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        user, profile = self.make("membre-verify@example.com", "Membre")
        user.email_verified_at = None
        user.save(update_fields=["email_verified_at"])
        profile.validated_at = None
        profile.save(update_fields=["validated_at"])
        self.as_staff(admin)
        page = self.client.get(f"/gestion/membres/{profile.id}/")
        self.assertContains(page, "Marquer le courriel comme vérifié")
        saved = self.client.post(f"/gestion/membres/{profile.id}/", {"action": "verify_email"})
        self.assertEqual(saved.status_code, 302)
        user.refresh_from_db()
        profile.refresh_from_db()
        self.assertIsNotNone(user.email_verified_at)
        self.assertIsNotNone(profile.validated_at)
        self.assertTrue(AuditLog.objects.filter(action="staff_member", target=str(profile.id), detail="verify_email").exists())
        self.assertNotContains(self.client.get(f"/gestion/membres/{profile.id}/"), "Marquer le courriel comme vérifié")



class V16BirthDateTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def _signup(self, **extra):
        data = {
            "email": "date-ok@example.com", "password": "motdepasse10",
            "birth_date_year": "1992", "birth_date_month": "2", "birth_date_day": "2",
            "display_name": "Date", "kind": "single", "accept": "on",
        }
        data.update(extra)
        return self.client.post("/comptes/inscription/", data)

    def test_three_selects_accept_a_real_date_and_reject_the_rest(self):
        page = self.client.get("/comptes/inscription/")
        self.assertContains(page, 'name="birth_date_day"')
        self.assertContains(page, 'name="birth_date_month"')
        self.assertContains(page, 'name="birth_date_year"')
        self.assertContains(page, ">Janvier<")
        self.assertContains(page, ">Jour")
        self.assertContains(page, ">Mois")
        self.assertContains(page, ">Année")
        latest = str(timezone.now().date().year - 18)
        self.assertContains(page, f'value="{latest}"')
        self.assertNotContains(page, 'value="2015"')
        self.assertNotContains(page, 'type="date"')
        self.client.get("/comptes/inscription/?lang=en")
        self.assertContains(self.client.get("/comptes/inscription/?lang=en"), ">January<")
        self.assertContains(self.client.get("/comptes/inscription/?lang=es"), ">Enero<")
        self.client.get("/comptes/inscription/?lang=fr")
        ok = self._signup()
        self.assertEqual(ok.status_code, 200)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(get_user_model().objects.get(email="date-ok@example.com").birth_date.isoformat(), "1992-02-02")
        self.client.logout()
        bad = self._signup(email="date-feb@example.com", birth_date_month="2", birth_date_day="30", birth_date_year="1990")
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "existe pas")
        self.assertContains(bad, 'value="30" selected')
        self.assertContains(bad, 'value="1990" selected')
        self.assertFalse(get_user_model().objects.filter(email="date-feb@example.com").exists())
        young = self._signup(email="date-young@example.com", birth_date_year="2015", birth_date_month="1", birth_date_day="1")
        self.assertContains(young, "Il faut avoir 18")
        self.assertFalse(get_user_model().objects.filter(email="date-young@example.com").exists())
        missing = self._signup(email="date-miss@example.com", birth_date_day="", birth_date_month="2", birth_date_year="1992")
        self.assertContains(missing, "incomplète")
        self.assertFalse(get_user_model().objects.filter(email="date-miss@example.com").exists())
        self.client.get("/comptes/inscription/?lang=en")
        english = self.client.post("/comptes/inscription/", {
            "email": "date-en@example.com", "password": "motdepasse10",
            "birth_date_year": "1990", "birth_date_month": "2", "birth_date_day": "30",
            "display_name": "Date", "kind": "single", "accept": "on",
        })
        self.assertContains(english, "This date does not exist.")
        self.assertNotContains(english, "existe pas.")
        self.client.get("/comptes/inscription/?lang=es")
        spanish = self.client.post("/comptes/inscription/", {
            "email": "date-es@example.com", "password": "motdepasse10",
            "birth_date_year": "1990", "birth_date_month": "2", "birth_date_day": "30",
            "display_name": "Fecha", "kind": "single", "accept": "on",
        })
        self.assertContains(spanish, "Esta fecha no existe.")

    def test_admin_member_form_uses_three_selects(self):
        admin, _ = self.make("root-birth@example.com", "Root")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        page = self.client.get("/gestion/membres/ajouter/")
        self.assertContains(page, 'name="birth_date_day"')
        self.assertContains(page, 'name="partner_birth_month"')
        self.assertNotContains(page, 'type="date"')
        bad = self.client.post("/gestion/membres/ajouter/", {
            "kind": "single", "display_name": "Date", "email": "admin-feb@example.com",
            "birth_date_year": "1990", "birth_date_month": "2", "birth_date_day": "30",
            "sub_status": "none", "country": "FR",
        })
        self.assertEqual(bad.status_code, 200)
        self.assertContains(bad, "existe pas")
        self.assertContains(bad, 'value="30" selected')
        self.assertContains(bad, ">Février<")
        self.assertFalse(get_user_model().objects.filter(email="admin-feb@example.com").exists())
        young = self.client.post("/gestion/membres/ajouter/", {
            "kind": "single", "display_name": "Jeune", "email": "admin-young@example.com",
            "birth_date_year": "2015", "birth_date_month": "1", "birth_date_day": "1",
            "sub_status": "none", "country": "FR",
        })
        self.assertContains(young, "doit avoir 18")
        self.assertFalse(get_user_model().objects.filter(email="admin-young@example.com").exists())
        missing = self.client.post("/gestion/membres/ajouter/", {
            "kind": "couple", "display_name": "Couple", "email": "admin-miss@example.com",
            "birth_date_year": "1992", "birth_date_month": "4", "birth_date_day": "4",
            "partner_name": "Deux", "partner_email": "deux@example.com",
            "partner_birth_year": "1993", "partner_birth_month": "5", "partner_birth_day": "",
            "sub_status": "none", "country": "FR",
        })
        self.assertContains(missing, "partenaire est incomplète")
        self.assertFalse(get_user_model().objects.filter(email="admin-miss@example.com").exists())


class V17LandingTests(TestCase):
    make = RulesTests.make

    def test_landing_replaces_home_in_three_languages_with_real_cities(self):
        import re
        from pathlib import Path

        from django.conf import settings

        from swingapp.landing_views import load_build

        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'aria-label="Langue"')
        self.assertNotContains(page, 'id="menu-btn"')
        self.assertNotContains(page, "data-app=")
        self.assertNotContains(page, "https://iswing.live")
        self.assertNotContains(page, "https://iswingtest.onrender.com")
        self.assertContains(page, 'href="/comptes/inscription/"')
        self.assertContains(page, 'href="/comptes/connexion/"')
        self.assertContains(page, "29 $ US")
        self.assertContains(page, '"price": "29.00"')
        self.assertContains(page, '"priceCurrency": "USD"')
        self.assertContains(page, 'hreflang="es"')
        self.assertContains(page, 'href="/rencontre-echangiste-montreal/"')
        self.assertEqual(len(re.findall(r"<h1\b", page.content.decode())), 1)
        english = self.client.get("/en/")
        self.assertContains(english, "Start your free trial")
        self.assertContains(english, "US$29")
        spanish = self.client.get("/es/")
        self.assertContains(spanish, "usted")
        self.assertContains(spanish, "celular")
        self.assertContains(spanish, "computadora")
        self.assertNotContains(spanish, "carro")
        self.assertNotContains(spanish, "estacionó")
        self.assertContains(spanish, "Inicie sesión")
        self.assertContains(self.client.get("/es/citas-swingers-montreal/"), "carro")
        city = self.client.get("/rencontre-echangiste-montreal/")
        self.assertEqual(city.status_code, 200)
        self.assertContains(city, "couple échangiste")
        self.assertEqual(len(re.findall(r"<h1\b", city.content.decode())), 1)
        self.assertEqual(self.client.get("/en/swinger-dating-cancun/").status_code, 200)
        self.assertEqual(self.client.get("/es/citas-swingers-ciudad-de-mexico/").status_code, 200)
        self.assertContains(self.client.get("/es/citas-swingers-cancun/"), "usted")
        module = load_build()
        for item in module.CITIES:
            for lang in ("fr", "en", "es"):
                self.assertGreaterEqual(module.word_count(" ".join(item[lang]["paragraphs"])), 300)
        built = Path(settings.BASE_DIR, "landing", "index.html").read_text(encoding="utf-8")
        self.assertIn("https://iswingtest.onrender.com/comptes/inscription/", built)
        self.assertNotIn("https://iswing.live", built)
        self.assertNotIn("data-app=", built)
        user, _ = self.make("landing-member@example.com", "Land")
        self.client.force_login(user)
        gone = self.client.get("/")
        self.assertEqual(gone.status_code, 302)
        self.assertEqual(gone["Location"], "/decouvrir/")
        sitemap = self.client.get("/sitemap.xml")
        self.assertContains(sitemap, "/rencontre-echangiste-montreal/")
        self.assertContains(sitemap, "/es/")
        self.assertContains(sitemap, 'hreflang="es"')
        robots = self.client.get("/robots.txt")
        self.assertContains(robots, "Disallow: /profil/")
        self.assertContains(robots, "Disallow: /photos/")


class V18LandingDynamicTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def _staff(self, email="landing-admin@example.com"):
        admin, _ = self.make(email, "Desk")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        return admin

    def test_spanish_copy_and_default_trial_phrases(self):
        es = self.client.get("/es/")
        self.assertContains(es, "¿Desea vivir sus deseos con confianza?")
        self.assertContains(es, "comparten sus deseos en su ciudad")
        self.assertContains(es, "a su ritmo")
        self.assertContains(es, "durante 7 días")
        self.assertNotContains(es, "ganas")
        self.assertNotContains(es, "al ritmo de usted")
        self.assertNotContains(es, "¿Listo")
        self.assertContains(es, "10 me gusta por día")
        self.assertContains(es, "2 mensajes por match")
        fr = self.client.get("/")
        self.assertContains(fr, "7 jours")
        self.assertContains(fr, "10 « j'aime » par jour")
        self.assertContains(fr, "2 messages par match")
        self.assertContains(fr, "data-city-carousel")
        en = self.client.get("/en/")
        self.assertContains(en, "7 days")
        self.assertContains(en, "10 likes per day")
        self.assertContains(en, "2 messages per match")

    def test_settings_update_home_faq_and_jsonld(self):
        admin = self._staff()
        res = self.client.post("/gestion/parametres/", {"action": "quotas", "days": "10", "likes": "6", "messages": "1"})
        self.assertEqual(res.status_code, 302)
        self.client.logout()
        fr = self.client.get("/")
        self.assertContains(fr, "10 jours")
        self.assertContains(fr, "6 « j'aime » par jour")
        self.assertContains(fr, "1 message par match")
        self.assertNotContains(fr, "7 jours")
        self.assertNotContains(fr, "2 messages par match")
        en = self.client.get("/en/")
        self.assertContains(en, "10 days")
        self.assertContains(en, "6 likes per day")
        self.assertContains(en, "1 message per match")
        self.assertNotContains(en, "7 days")
        es = self.client.get("/es/")
        self.assertContains(es, "10 días")
        self.assertContains(es, "6 me gusta por día")
        self.assertContains(es, "1 mensaje por match")
        self.assertNotContains(es, "7 días")
        self.as_staff(admin)
        self.client.post("/gestion/parametres/", {"action": "quotas", "days": "1", "likes": "1", "messages": "1"})
        self.client.logout()
        single = self.client.get("/")
        self.assertContains(single, "1 jour")
        self.assertNotContains(single, "1 jours")
        self.assertContains(single, "1 « j'aime » par jour")
        self.assertContains(single, "1 message par match")
        english = self.client.get("/en/")
        self.assertContains(english, "1 day")
        self.assertNotContains(english, "1 days")
        self.assertContains(english, "1 like per day")
        spanish = self.client.get("/es/")
        self.assertContains(spanish, "1 día")
        self.assertNotContains(spanish, "1 días")
        self.assertContains(spanish, "1 me gusta por día")
        self.assertContains(spanish, "1 mensaje por match")

    def test_landing_tab_hero_city_and_sitemap(self):
        import io
        import tempfile
        from pathlib import Path

        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from PIL import Image

        from swingapp.models import LandingCity, SiteSetting

        admin = self._staff("landing-desk@example.com")
        page = self.client.get("/gestion/landing/")
        self.assertContains(page, "Dimensions optimales : 960 × 720 px (ratio 4:3), JPG ou WebP, max 500 Ko.")
        self.assertContains(page, "Dimensions optimales : 800 × 480 px (ratio 5:3), JPG ou WebP, max 500 Ko.")
        self.assertContains(page, "Paramètres")
        buf = io.BytesIO()
        Image.new("RGB", (1400, 1050), (30, 10, 60)).save(buf, format="JPEG")
        upload = SimpleUploadedFile("saison.jpg", buf.getvalue(), content_type="image/jpeg")
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(MEDIA_ROOT=tmp):
                bad = SimpleUploadedFile("note.svg", b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", content_type="image/svg+xml")
                refused = self.client.post("/gestion/landing/", {"action": "hero", "image": bad})
                self.assertEqual(refused.status_code, 302)
                self.assertFalse(SiteSetting.objects.filter(key="landing_hero_image").exists())
                saved = self.client.post("/gestion/landing/", {"action": "hero", "image": upload})
                self.assertEqual(saved.status_code, 302)
                hero = Path(tmp) / "landing" / "hero.webp"
                self.assertTrue(hero.is_file())
                self.assertLessEqual(hero.stat().st_size, 500_000)
                with Image.open(hero) as picture:
                    self.assertLessEqual(picture.width, 960)
                    self.assertLessEqual(picture.height, 720)
                self.client.logout()
                home = self.client.get("/")
                self.assertContains(home, "/landing-media/hero.webp")
                self.assertContains(home, "anneaux")
                self.assertNotContains(home, "hero-rings.svg")
                media = self.client.get("/landing-media/hero.webp")
                self.assertEqual(media.status_code, 200)
                self.assertEqual(media["Cache-Control"], "no-cache")
                self.as_staff(admin)
                body = "Première phrase de Playa, assez claire pour la page.\n\nDeuxième phrase de Playa, séparée par une ligne vide."
                photo_buf = io.BytesIO()
                Image.new("RGB", (1200, 720), (12, 40, 90)).save(photo_buf, format="JPEG")
                city_photo = SimpleUploadedFile("playa.jpg", photo_buf.getvalue(), content_type="image/jpeg")
                created = self.client.post("/gestion/landing/ville/nouvelle/", {
                    "action": "save",
                    "name": "Playa",
                    "position": "9",
                    "is_active": "1",
                    "title_fr": "Playa FR",
                    "title_en": "Playa EN",
                    "title_es": "Playa ES",
                    "desc_fr": "Description française de Playa.",
                    "desc_en": "English description of Playa.",
                    "desc_es": "Descripción en español de Playa.",
                    "tagline_fr": "Accroche Playa",
                    "tagline_en": "Playa tagline",
                    "tagline_es": "Frase Playa",
                    "body_fr": body,
                    "body_en": "First Playa paragraph for visitors.\n\nSecond Playa paragraph for visitors.",
                    "body_es": "Primer párrafo de Playa para usted.\n\nSegundo párrafo de Playa para usted.",
                    "image": city_photo,
                })
                self.assertEqual(created.status_code, 302)
                self.client.logout()
                city = LandingCity.objects.get(slug="playa")
                self.assertEqual(city.slug_en, "playa")
                self.assertEqual(city.slug_es, "playa")
                self.assertTrue(city.image.name.startswith("landing/cities/"))
                stored = Path(tmp) / city.image.name
                self.assertTrue(stored.is_file())
                self.assertLessEqual(stored.stat().st_size, 500_000)
                with Image.open(stored) as picture:
                    self.assertLessEqual(picture.width, 800)
                    self.assertLessEqual(picture.height, 480)
                home = self.client.get("/")
                self.assertContains(home, "Playa")
                self.assertContains(home, 'href="/rencontre-echangiste-playa/"')
                self.assertEqual(self.client.get("/rencontre-echangiste-playa/").status_code, 200)
                self.assertContains(self.client.get("/rencontre-echangiste-playa/"), "Première phrase de Playa")
                self.assertEqual(self.client.get("/en/swinger-dating-playa/").status_code, 200)
                self.assertEqual(self.client.get("/es/citas-swingers-playa/").status_code, 200)
                self.assertContains(self.client.get("/es/citas-swingers-playa/"), "usted")
                sitemap = self.client.get("/sitemap.xml")
                self.assertContains(sitemap, "/rencontre-echangiste-playa/")
                self.assertContains(sitemap, "/en/swinger-dating-playa/")
                self.assertContains(sitemap, "/es/citas-swingers-playa/")
                self.assertContains(sitemap, "/rencontre-echangiste-montreal/")
                self.assertEqual(self.client.get("/en/swinger-dating-quebec-city/").status_code, 200)
                self.assertEqual(self.client.get("/es/citas-swingers-ciudad-de-mexico/").status_code, 200)
                self.as_staff(admin)
                off = self.client.post(f"/gestion/landing/ville/{city.id}/", {"action": "deactivate"})
                self.assertEqual(off.status_code, 302)
                city.refresh_from_db()
                self.assertFalse(city.is_active)
                self.client.logout()
                self.assertNotContains(self.client.get("/"), "rencontre-echangiste-playa")
                self.assertNotContains(self.client.get("/sitemap.xml"), "playa")
                self.assertEqual(self.client.get("/rencontre-echangiste-playa/").status_code, 404)
                self.assertEqual(self.client.get("/en/swinger-dating-montreal/").status_code, 200)


class V19GeoTests(TestCase):
    make = RulesTests.make
    as_staff = RulesTests.as_staff

    def test_city_and_radius_is_geographic_for_typed_and_posted_coords(self):
        user, _viewer = self.make("centre@example.com", "Centre")
        _sans_user, sans = self.make("sans@example.com", "SansCoord")
        _jerome_user, jerome = self.make("jerome@example.com", "Jeromien")
        sans.city, sans.lat, sans.lng = "Montréal", None, None
        sans.save(update_fields=["city", "lat", "lng"])
        jerome.city, jerome.lat, jerome.lng = "Saint-Jérôme", 45.78036, -74.00365
        jerome.save(update_fields=["city", "lat", "lng"])
        self.client.force_login(user)

        typed = self.client.get("/decouvrir/", {"city": "Montréal", "max_km": "100", "lang": "fr"})
        self.assertContains(typed, "Jeromien")
        self.assertNotContains(typed, "SansCoord")
        ascii_name = self.client.get("/decouvrir/", {"city": "Montreal", "max_km": "100", "lang": "fr"})
        self.assertContains(ascii_name, "Jeromien")
        self.assertNotContains(ascii_name, "SansCoord")
        posted = self.client.get("/decouvrir/", {
            "city": "ZZZZZZ", "max_km": "100", "city_lat": "45.50884", "city_lng": "-73.58781", "lang": "fr",
        })
        self.assertContains(posted, "Jeromien")
        self.assertNotContains(posted, "SansCoord")
        self.assertNotContains(posted, "Ville introuvable")

        text = self.client.get("/decouvrir/", {"city": "Montréal", "lang": "fr"})
        self.assertContains(text, "SansCoord")
        self.assertNotContains(text, "Jeromien")
        self.assertNotContains(text, "Ville introuvable")

    def test_villeray_radius_includes_a_nearby_profile(self):
        user, _viewer = self.make("villeray-me@example.com", "CentreV")
        _near_user, near = self.make("rosemont@example.com", "Rosemontais")
        near.city, near.lat, near.lng = "Rosemont", 45.55869, -73.60535
        near.save(update_fields=["city", "lat", "lng"])
        self.client.force_login(user)
        for city in ("Villeray", "Villeray–Saint-Michel–Parc-Extension"):
            page = self.client.get("/decouvrir/", {"city": city, "max_km": "100", "lang": "fr"})
            self.assertContains(page, "Rosemontais")
        posted = self.client.get("/decouvrir/", {
            "city": "ZZZZZZ", "max_km": "100", "city_lat": "45.55869", "city_lng": "-73.60535", "lang": "fr",
        })
        self.assertContains(posted, "Rosemontais")
        self.assertNotContains(posted, "Ville introuvable")

    def test_unknown_city_with_radius_does_not_fall_back_to_text(self):
        from swingapp.i18n import t

        user, _viewer = self.make("inconnu-me@example.com", "CentreZ")
        _ghost_user, ghost = self.make("fantome@example.com", "Fantome")
        ghost.city, ghost.lat, ghost.lng = "ZZZZZZ", 45.50884, -73.58781
        ghost.save(update_fields=["city", "lat", "lng"])
        self.client.force_login(user)
        with self.assertLogs("iswing.geo", level="WARNING") as captured:
            page = self.client.get("/decouvrir/", {"city": "ZZZZZZ", "max_km": "100", "lang": "fr"})
        self.assertContains(page, t("fr", "city_not_found"))
        self.assertNotContains(page, "Fantome")
        self.assertTrue(any("ZZZZZZ" in line for line in captured.output))
        english = self.client.get("/decouvrir/", {"city": "ZZZZZZ", "max_km": "100", "lang": "en"})
        self.assertContains(english, t("en", "city_not_found"))
        spanish = self.client.get("/decouvrir/", {"city": "ZZZZZZ", "max_km": "100", "lang": "es"})
        self.assertContains(spanish, t("es", "city_not_found"))
        textual = self.client.get("/decouvrir/", {"city": "ZZZZZZ", "lang": "fr"})
        self.assertContains(textual, "Fantome")
        self.assertNotContains(textual, t("fr", "city_not_found"))

    def test_closest_profiles_come_first_and_distance_stays_from_the_visitor(self):
        from swingapp.services import approximate_distance, haversine_km

        user, viewer = self.make("tri@example.com", "Trieur")
        viewer.city, viewer.lat, viewer.lng = "Montréal", 45.50884, -73.58781
        viewer.save(update_fields=["city", "lat", "lng"])
        _laval_user, laval = self.make("laval@example.com", "Lavalois")
        _jerome_user, jerome = self.make("jerome-tri@example.com", "Jeromien")
        _sans_user, sans = self.make("sans-tri@example.com", "SansLieu")
        now = timezone.now()
        laval.city, laval.lat, laval.lng = "Laval", 45.56995, -73.692
        laval.last_active = now - timedelta(days=5)
        laval.save(update_fields=["city", "lat", "lng", "last_active"])
        jerome.city, jerome.lat, jerome.lng = "Saint-Jérôme", 45.78036, -74.00365
        jerome.last_active = now
        jerome.save(update_fields=["city", "lat", "lng", "last_active"])
        sans.city, sans.lat, sans.lng = "Nullepart", None, None
        sans.last_active = now + timedelta(minutes=5)
        sans.save(update_fields=["city", "lat", "lng", "last_active"])
        self.client.force_login(user)
        closest = self.client.get("/decouvrir/", {"lang": "fr"})
        self.assertContains(closest, "Lavalois")
        self.assertNotContains(closest, "Jeromien")
        self.assertNotContains(closest, "SansLieu")
        visitor_distance = approximate_distance(haversine_km(45.50884, -73.58781, 45.56995, -73.692))
        other_distance = approximate_distance(haversine_km(45.75, 4.85, 45.56995, -73.692))
        self.assertNotEqual(visitor_distance, other_distance)
        self.assertContains(closest, visitor_distance)
        self.assertNotContains(closest, other_distance)

        viewer.lat, viewer.lng = 45.75, 4.85
        viewer.city = "Lyon"
        viewer.save(update_fields=["city", "lat", "lng"])
        loin_user, loin = self.make("loin-nord@example.com", "LoinNord")
        loin.city, loin.lat, loin.lng = "Nord", 46.30884, -73.58781
        loin.last_active = now + timedelta(days=1)
        loin.save(update_fields=["city", "lat", "lng", "last_active"])
        d_pres = haversine_km(45.50884, -73.58781, jerome.lat, jerome.lng)
        d_loin = haversine_km(45.50884, -73.58781, loin.lat, loin.lng)
        self.assertLess(d_pres, d_loin)
        self.assertLess(d_loin, 100)
        searched = self.client.get("/decouvrir/", {"city": "Montréal", "max_km": "100", "lang": "fr"})
        self.assertContains(searched, "Lavalois")
        self.assertNotContains(searched, "LoinNord")
        self.assertNotContains(searched, "Jeromien")
        from_visitor = approximate_distance(haversine_km(viewer.lat, viewer.lng, laval.lat, laval.lng))
        from_search = approximate_distance(haversine_km(45.50884, -73.58781, laval.lat, laval.lng))
        self.assertNotEqual(from_visitor, from_search)
        self.assertContains(searched, from_visitor)
        self.assertNotContains(searched, from_search)

        viewer.lat = None
        viewer.lng = None
        viewer.save(update_fields=["lat", "lng"])
        recent = self.client.get("/decouvrir/", {"lang": "fr"})
        self.assertContains(recent, "LoinNord")
        self.assertNotContains(recent, "Jeromien")
        missing = self.client.get("/decouvrir/", {"max_km": "40", "lang": "fr"})
        self.assertContains(missing, "indiquez votre ville")

    def test_travel_position_replaces_home_inside_a_radius(self):
        today = timezone.localdate()
        user, _viewer = self.make("voyage-geo@example.com", "CentreT")
        _home_user, home = self.make("resident@example.com", "Resident")
        _away_user, away = self.make("vacancier@example.com", "Vacancier")
        home.city, home.lat, home.lng = "Montréal", 45.50884, -73.58781
        home.save(update_fields=["city", "lat", "lng"])
        away.city, away.lat, away.lng = "Montréal", 45.50884, -73.58781
        away.travel_city = "Playa del Carmen"
        away.travel_country = "MX"
        away.travel_lat, away.travel_lng = 20.6274, -87.07987
        away.travel_start = today - timedelta(days=1)
        away.travel_end = today + timedelta(days=3)
        away.save()
        self.client.force_login(user)
        montreal = self.client.get("/decouvrir/", {"city": "Montréal", "max_km": "100", "lang": "fr"})
        self.assertContains(montreal, "Resident")
        self.assertNotContains(montreal, "Vacancier")
        playa = self.client.get("/decouvrir/", {"city": "Playa del Carmen", "max_km": "100", "lang": "fr"})
        self.assertContains(playa, "Vacancier")
        self.assertNotContains(playa, "Resident")
        away.travel_end = today - timedelta(days=1)
        away.last_active = timezone.now()
        away.save(update_fields=["travel_end", "last_active"])
        back = self.client.get("/decouvrir/", {"city": "Montréal", "max_km": "100", "lang": "fr"})
        self.assertContains(back, "Vacancier")

    def test_geocode_command_and_admin_button_never_overwrite(self):
        from io import StringIO
        from django.core.management import call_command

        _user, missing = self.make("geo-manque@example.com", "Manque")
        missing.city, missing.lat, missing.lng = "Montréal", None, None
        missing.save(update_fields=["city", "lat", "lng"])
        _kept_user, kept = self.make("geo-garde@example.com", "Garde")
        kept.city, kept.lat, kept.lng = "Montréal", 1.2345, 2.3456
        kept.save(update_fields=["city", "lat", "lng"])
        _bad_user, bad = self.make("geo-bad@example.com", "Inconnu")
        bad.city, bad.lat, bad.lng = "ZZZZZZ", None, None
        bad.save(update_fields=["city", "lat", "lng"])
        dry = StringIO()
        call_command("geocode_missing_cities", "--dry-run", stdout=dry)
        self.assertIn("dry-run", dry.getvalue())
        missing.refresh_from_db()
        kept.refresh_from_db()
        self.assertIsNone(missing.lat)
        self.assertAlmostEqual(kept.lat, 1.2345)
        self.assertFalse(AuditLog.objects.filter(action="geocode_city", target=str(missing.id)).exists())
        call_command("geocode_missing_cities", stdout=StringIO())
        missing.refresh_from_db()
        kept.refresh_from_db()
        bad.refresh_from_db()
        self.assertAlmostEqual(missing.lat, 45.50884, places=4)
        self.assertAlmostEqual(missing.lng, -73.58781, places=4)
        self.assertAlmostEqual(kept.lat, 1.2345, places=4)
        self.assertAlmostEqual(kept.lng, 2.3456, places=4)
        self.assertIsNone(bad.lat)
        self.assertTrue(AuditLog.objects.filter(action="geocode_city", target=str(missing.id)).exists())
        self.assertFalse(AuditLog.objects.filter(action="geocode_city", target=str(kept.id)).exists())

        admin, _ = self.make("root-geo@example.com", "RootGeo")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        _extra_user, extra = self.make("geo-bouton@example.com", "Bouton")
        extra.city, extra.lat, extra.lng = "Laval", None, None
        extra.save(update_fields=["city", "lat", "lng"])
        self.as_staff(admin)
        preview = self.client.post("/gestion/membres/geocoder/", {"dry_run": "1"})
        self.assertEqual(preview.status_code, 302)
        extra.refresh_from_db()
        self.assertIsNone(extra.lat)
        self.assertContains(self.client.get("/gestion/membres/"), "Prévisualisation")
        applied = self.client.post("/gestion/membres/geocoder/", {})
        self.assertEqual(applied.status_code, 302)
        extra.refresh_from_db()
        kept.refresh_from_db()
        self.assertAlmostEqual(extra.lat, 45.56995, places=4)
        self.assertAlmostEqual(kept.lat, 1.2345, places=4)
        self.assertContains(self.client.get("/gestion/membres/"), "géocodé")

    def test_typed_city_is_geocoded_on_save_without_clearing_existing_coords(self):
        user, profile = self.make("sauve-geo@example.com", "Sauve")
        self.client.force_login(user)
        saved = self.client.post("/moi/", {
            "display_name": "Sauve", "kind": "single", "city": "Saint-Jérôme", "bio": "bio", "visibility": "public",
        })
        self.assertEqual(saved.status_code, 302)
        profile.refresh_from_db()
        self.assertAlmostEqual(profile.lat, 45.78036, places=4)
        self.assertAlmostEqual(profile.lng, -74.00365, places=4)
        profile.lat, profile.lng = 1.2345, 2.3456
        profile.save(update_fields=["lat", "lng"])
        again = self.client.post("/moi/", {
            "display_name": "Sauve", "kind": "single", "city": "Saint-Jérôme", "bio": "bio", "visibility": "public",
        })
        self.assertEqual(again.status_code, 302)
        profile.refresh_from_db()
        self.assertAlmostEqual(profile.lat, 1.2345, places=4)
        self.assertAlmostEqual(profile.lng, 2.3456, places=4)
        cleared = self.client.post("/moi/", {
            "display_name": "Sauve", "kind": "single", "city": "ZZZZZZ", "bio": "bio", "visibility": "public",
        })
        self.assertEqual(cleared.status_code, 302)
        profile.refresh_from_db()
        self.assertIsNone(profile.lat)
        self.assertIsNone(profile.lng)
        today = timezone.localdate()
        travel = self.client.post("/moi/voyage/", {
            "city": "Montreal", "country": "CA",
            "start": (today - timedelta(days=1)).isoformat(),
            "end": (today + timedelta(days=2)).isoformat(),
        })
        self.assertEqual(travel.status_code, 302)
        profile.refresh_from_db()
        self.assertAlmostEqual(profile.travel_lat, 45.50884, places=4)
        self.assertAlmostEqual(profile.travel_lng, -73.58781, places=4)

        admin, _ = self.make("root-ajout@example.com", "RootAjout")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        created = self.client.post("/gestion/membres/ajouter/", {
            "kind": "single",
            "display_name": "NouveauGeo",
            "email": "nouveau-geo@example.com",
            "birth_date_year": "1991", "birth_date_month": "3", "birth_date_day": "3",
            "city": "Saint-Jérôme",
            "country": "CA",
        })
        self.assertEqual(created.status_code, 302, created.content[:400])
        added = Profile.objects.get(user__email="nouveau-geo@example.com")
        self.assertAlmostEqual(added.lat, 45.78036, places=4)
        self.assertAlmostEqual(added.lng, -74.00365, places=4)

    def test_admin_sheet_shows_effective_visibility(self):
        admin, _ = self.make("root-vis@example.com", "RootVis")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        self.as_staff(admin)
        clean = self.client.get(f"/gestion/membres/{admin.profile.id}/")
        self.assertContains(clean, "Visibilité : Public")
        self.assertNotContains(clean, "non consultable")
        user, profile = self.make("bloque-vis@example.com", "Bloque")
        user.terms_accepted_at = None
        user.adult_declared = False
        user.email_verified_at = None
        user.save(update_fields=["terms_accepted_at", "adult_declared", "email_verified_at"])
        blocked = self.client.get(f"/gestion/membres/{profile.id}/")
        self.assertContains(
            blocked,
            "Visibilité : Public (non consultable : conditions non acceptées, majorité non déclarée, courriel non vérifié)",
        )
        user.terms_accepted_at = timezone.now()
        user.adult_declared = True
        user.save(update_fields=["terms_accepted_at", "adult_declared"])
        mail = self.client.get(f"/gestion/membres/{profile.id}/")
        self.assertContains(mail, "Visibilité : Public (non consultable : courriel non vérifié)")
        user.email_verified_at = timezone.now()
        user.save(update_fields=["email_verified_at"])
        profile.suspended = True
        profile.save(update_fields=["suspended"])
        suspended = self.client.get(f"/gestion/membres/{profile.id}/")
        self.assertContains(suspended, "Visibilité : Public (non consultable : suspendu)")

    def test_gps_script_asks_for_a_fresh_precise_position(self):
        from pathlib import Path
        from swingapp.i18n import t

        user, profile = self.make("gps-precis@example.com", "GpsPrecis")
        self.client.force_login(user)
        saved = self.client.post("/moi/position/", {
            "lat": "20.62741", "lng": "-87.07987", "city": "", "from_gps": "1",
        })
        self.assertEqual(saved.status_code, 302)
        profile.refresh_from_db()
        self.assertAlmostEqual(profile.lat, round(20.62741, 4))
        self.assertAlmostEqual(profile.lng, round(-87.07987, 4))
        self.assertEqual(profile.city, "Playa del Carmen")
        page = self.client.get("/parametres/")
        self.assertContains(page, "Position détectée")
        self.assertContains(page, "Localisation refusée")
        self.assertContains(page, "Position indisponible")
        self.assertContains(page, "Délai dépassé")
        self.assertContains(page, 'id="geo-status"')
        self.assertEqual(t("en", "gps_denied"), "Location denied. Allow it in your browser settings, then try again.")
        self.assertEqual(t("es", "gps_timeout"), "Se agotó el tiempo. Vuelva a intentarlo, de preferencia al aire libre o cerca de una ventana.")
        self.assertEqual(t("fr", "gps_found"), "Position détectée : {city}")
        script = Path("static/js/app.js").read_text(encoding="utf-8")
        self.assertIn("enableHighAccuracy: true", script)
        self.assertIn("timeout: 30000", script)
        self.assertIn("maximumAge: 0", script)
        self.assertIn("toFixed(4)", script)
        self.assertIn('event.key === "Enter"', script)
        self.assertIn("ArrowDown", script)
        self.assertIn("from_gps", script)
        self.assertNotIn('mode !== "filter"', script)
        self.assertNotIn("geodenied", script)
        self.assertNotIn("timeout: 15000", script)
        self.assertNotIn("maximumAge: 120000", script)
        self.assertEqual(script.count("alert("), 2)





class InvitationResendTests(TestCase):
    def make(self, email, name):
        from datetime import date
        user = get_user_model().objects.create_user(
            email=email, password="motdepasse10", birth_date=date(1990, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        profile = Profile.objects.create(user=user, display_name=name, city="Lyon", bio="bio",
                                         validated_at=timezone.now(),
                                         trial_ends_at=timezone.now() + timedelta(days=7))
        return user, profile

    def test_resend_does_not_kill_previous_link(self):
        from django.test import RequestFactory
        from swingapp.gestion import send_member_invite
        from swingapp.models import EmailToken

        user, profile = self.make("reinvite@example.com", "ReInvite")
        rf = RequestFactory()
        req = rf.get("/")
        req.lang = "fr"
        link1 = send_member_invite(profile, req)
        link2 = send_member_invite(profile, req)
        # Les deux liens restent valides (aucun n'est tué par le renvoi)
        alive = EmailToken.objects.filter(user=user, purpose="invite", used_at__isnull=True).count()
        self.assertEqual(alive, 2)
        # Le premier lien fonctionne encore
        resp = self.client.get(link1.replace("http://testserver", ""))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "expir")

    def test_accepting_one_link_kills_the_others(self):
        from django.test import RequestFactory
        from swingapp.gestion import send_member_invite
        from swingapp.models import EmailToken

        user, profile = self.make("reinvite2@example.com", "ReInvite2")
        rf = RequestFactory()
        req = rf.get("/")
        req.lang = "fr"
        link1 = send_member_invite(profile, req)
        link2 = send_member_invite(profile, req)
        path1 = link1.replace("http://testserver", "")
        self.client.post(path1, {
            "password": "motdepasse10", "password2": "motdepasse10",
            "accept": "1",
        })
        # Après activation, plus aucun lien non utilisé
        alive = EmailToken.objects.filter(user=user, purpose="invite", used_at__isnull=True).count()
        self.assertEqual(alive, 0)
        # Le second lien est maintenant expiré
        path2 = link2.replace("http://testserver", "")
        resp = self.client.get(path2)
        self.assertContains(resp, "expir")


class InviteResendPageTests(TestCase):
    def test_expired_page_links_to_resend(self):
        resp = self.client.get("/invitation/ce-token-nexiste-pas/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "/invitation/renvoyer/")

    def test_resend_form_sends_new_link(self):
        from swingapp.models import EmailToken

        User = get_user_model()
        u = User.objects.create_user(email="attente@example.com", password="motdepasse10" * 2)
        # compte en attente d'activation (conditions non acceptées)
        u.terms_accepted_at = None
        u.save()
        Profile.objects.create(user=u, display_name="Attente", kind="single")
        resp = self.client.post("/invitation/renvoyer/", {"email": "attente@example.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["sent"])
        self.assertEqual(EmailToken.objects.filter(user=u, purpose="invite", used_at__isnull=True).count(), 1)

    def test_resend_unknown_email_shows_same_confirmation(self):
        resp = self.client.post("/invitation/renvoyer/", {"email": "inconnu@example.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["sent"])

    def test_resend_ignores_activated_accounts(self):
        from swingapp.models import EmailToken

        User = get_user_model()
        u = User.objects.create_user(email="actif@example.com", password="motdepasse10" * 2)
        u.terms_accepted_at = timezone.now()
        u.save()
        Profile.objects.create(user=u, display_name="Actif", kind="single")
        self.client.post("/invitation/renvoyer/", {"email": "actif@example.com"})
        self.assertEqual(EmailToken.objects.filter(user=u, purpose="invite").count(), 0)


class PasswordResetPageTests(TestCase):
    def test_reset_post_shows_confirmation(self):
        User = get_user_model()
        User.objects.create_user(email="r@example.com", password="motdepasse10" * 2)
        resp = self.client.post("/comptes/mot-de-passe/", {"email": "r@example.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["sent"])
        self.assertContains(resp, "réinitialisation")

    def test_reset_post_unknown_email_shows_same_confirmation(self):
        resp = self.client.post("/comptes/mot-de-passe/", {"email": "nobody@example.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.context["sent"])


class VerifyEmailAutoLoginTests(TestCase):
    def test_verify_link_logs_in_and_redirects_to_profile(self):
        from datetime import date
        from swingapp.models import EmailToken, new_token

        User = get_user_model()
        u = User.objects.create_user(email="verifyme@test.xx", password="motdepasse10",
                                     birth_date=date(1990, 1, 1))
        Profile.objects.create(user=u, display_name="VerifyMe", city="", bio="",
                               trial_ends_at=timezone.now() + timedelta(days=7))
        raw, digest = new_token()
        EmailToken.objects.create(user=u, purpose="verify", token_hash=digest,
                                  expires_at=timezone.now() + timedelta(hours=24))
        resp = self.client.get(f"/comptes/verifier/{raw}/")
        # Connecté automatiquement et redirigé vers Mon profil (profil incomplet)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/moi/")
        u.refresh_from_db()
        self.assertIsNotNone(u.email_verified_at)
        # La session est authentifiée
        self.assertIn("_auth_user_id", self.client.session)

    def test_verify_link_complete_profile_goes_to_discover(self):
        from datetime import date
        from io import BytesIO
        from django.core.files.base import ContentFile
        from PIL import Image
        from swingapp.models import EmailToken, Photo, new_token

        User = get_user_model()
        u = User.objects.create_user(email="verifyfull@test.xx", password="motdepasse10",
                                     birth_date=date(1990, 1, 1))
        p = Profile.objects.create(user=u, display_name="VerifyFull", city="Lyon", bio="bio complète",
                                   trial_ends_at=timezone.now() + timedelta(days=7))
        out = BytesIO()
        Image.new("RGB", (100, 100)).save(out, format="JPEG")
        photo = Photo(profile=p, is_primary=True, moderation_status="approved")
        photo.image.save("t.jpg", ContentFile(out.getvalue()), save=True)
        raw, digest = new_token()
        EmailToken.objects.create(user=u, purpose="verify", token_hash=digest,
                                  expires_at=timezone.now() + timedelta(hours=24))
        resp = self.client.get(f"/comptes/verifier/{raw}/")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp["Location"], "/decouvrir/")


class StripePromoCodeTests(TestCase):
    def test_checkout_allows_promotion_codes(self):
        from datetime import date
        from io import BytesIO
        from unittest.mock import patch
        from django.core.files.base import ContentFile
        from django.test import override_settings
        from PIL import Image
        from swingapp.models import Photo

        User = get_user_model()
        u = User.objects.create_user(email="promo@test.xx", password="motdepasse10",
                                     birth_date=date(1990, 1, 1),
                                     terms_accepted_at=timezone.now(), adult_declared=True,
                                     email_verified_at=timezone.now())
        p = Profile.objects.create(user=u, display_name="Promo", city="Lyon", bio="bio",
                                   trial_ends_at=timezone.now() + timedelta(days=7))
        out = BytesIO()
        Image.new("RGB", (100, 100)).save(out, format="JPEG")
        photo = Photo(profile=p, is_primary=True, moderation_status="approved")
        photo.image.save("t.jpg", ContentFile(out.getvalue()), save=True)
        self.client.force_login(u)
        captured = {}

        class FakeSession:
            url = "https://checkout.stripe.com/pay/cs_test_123"

        def fake_create(**kwargs):
            captured.update(kwargs)
            return FakeSession()

        with override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_PRICE_ID="price_x"):
            with patch("stripe.checkout.Session.create", side_effect=fake_create):
                resp = self.client.post("/abonnement/stripe/")
        self.assertTrue(captured.get("allow_promotion_codes"))
        self.assertEqual(captured.get("mode"), "subscription")


class SmtpTimeoutTests(TestCase):
    def test_mail_connection_has_timeout(self):
        from swingapp.integrations import get_integration, mail_connection

        row = get_integration("smtp")
        row.public_data = {
            "host": "10.255.255.1", "port": "587", "username": "x",
            "tls": "starttls", "from_email": "x@x.xx",
        }
        row.secret_data = ""
        row.enabled = True
        row.save()
        conn = mail_connection("smtp")
        self.assertIsNotNone(conn)
        self.assertGreaterEqual(conn.timeout, 5)
        self.assertLessEqual(conn.timeout, 60)


class SuperLikeTests(TestCase):
    def make(self, email, name):
        from datetime import date
        from io import BytesIO
        from django.core.files.base import ContentFile
        from PIL import Image
        user = get_user_model().objects.create_user(
            email=email, password="motdepasse10", birth_date=date(1990, 1, 1),
            terms_accepted_at=timezone.now(), adult_declared=True, email_verified_at=timezone.now(),
        )
        profile = Profile.objects.create(user=user, display_name=name, city="Lyon", bio="bio",
                                         validated_at=timezone.now(),
                                         trial_ends_at=timezone.now() + timedelta(days=7))
        out = BytesIO()
        Image.new("RGB", (100, 100)).save(out, format="JPEG")
        photo = Photo(profile=profile, is_primary=True, moderation_status="approved")
        photo.image.save("t.jpg", ContentFile(out.getvalue()), save=True)
        return user, profile

    def test_superlike_notifies_target(self):
        from swingapp.models import Notice, SuperLike
        u1, p1 = self.make("sl1@example.com", "SL1")
        u2, p2 = self.make("sl2@example.com", "SL2")
        self.client.force_login(u1)
        resp = self.client.post(f"/actions/superlike/{p2.id}/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        # SuperLike créé
        self.assertTrue(SuperLike.objects.filter(actor=p1, target=p2).exists())
        # Like sous-jacent créé (pour les matchs)
        from swingapp.models import Like
        self.assertTrue(Like.objects.filter(actor=p1, target=p2).exists())
        # Notification envoyée
        self.assertTrue(Notice.objects.filter(profile=p2, kind="superlike").exists())

    def test_superlike_quota_3_per_month(self):
        from swingapp.models import SuperLike
        u1, p1 = self.make("slq1@example.com", "SLQ1")
        self.client.force_login(u1)
        # 3 super likes OK
        for i in range(3):
            _, px = self.make(f"slq-t{i}@example.com", f"SLQT{i}")
            resp = self.client.post(f"/actions/superlike/{px.id}/")
            self.assertEqual(resp.status_code, 200, f"superlike {i+1} devrait passer")
        # 4ème refusé
        _, px = self.make("slq-t9@example.com", "SLQT9")
        resp = self.client.post(f"/actions/superlike/{px.id}/")
        self.assertEqual(resp.status_code, 403)
        self.assertIn("super", resp.json()["error"].lower())

    def test_superlike_credits_extend_quota(self):
        u1, p1 = self.make("slc1@example.com", "SLC1")
        p1.superlike_credits = 5
        p1.save(update_fields=["superlike_credits"])
        self.client.force_login(u1)
        # 3 gratuits + 5 crédits = 8 possibles
        for i in range(8):
            _, px = self.make(f"slc-t{i}@example.com", f"SLCT{i}")
            resp = self.client.post(f"/actions/superlike/{px.id}/")
            self.assertEqual(resp.status_code, 200, f"superlike {i+1} devrait passer")
        p1.refresh_from_db()
        self.assertEqual(p1.superlike_credits, 0)
        # 9ème refusé
        _, px = self.make("slc-t9@example.com", "SLCT9")
        resp = self.client.post(f"/actions/superlike/{px.id}/")
        self.assertEqual(resp.status_code, 403)

    def test_normal_like_is_silent(self):
        from swingapp.models import Notice
        u1, p1 = self.make("nl1@example.com", "NL1")
        u2, p2 = self.make("nl2@example.com", "NL2")
        self.client.force_login(u1)
        resp = self.client.post(f"/actions/like/{p2.id}/")
        self.assertEqual(resp.status_code, 200)
        # Aucune notification de like normal
        self.assertFalse(Notice.objects.filter(profile=p2, kind="like").exists())

    def test_superlike_can_create_match(self):
        u1, p1 = self.make("sm1@example.com", "SM1")
        u2, p2 = self.make("sm2@example.com", "SM2")
        # p2 like p1 d'abord
        self.client.force_login(u2)
        self.client.post(f"/actions/like/{p1.id}/")
        # p1 super like p2 -> match
        self.client.force_login(u1)
        resp = self.client.post(f"/actions/superlike/{p2.id}/")
        data = resp.json()
        self.assertTrue(data["match"])
