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

from swingapp.models import AuditLog, Block, Campaign, CampaignDelivery, DailyUsage, Like, Match, MatchUsage, Message, Notice, OutboundEmail, Partner, Photo, PhotoGrant, PrivateAccess, Profile, Report, Subscription
from swingapp.services import QuotaError, consume_like, create_like, find_contact_info, in_trial


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
            "email": "jeune@example.com", "password": "motdepasse10", "birth_date": "2015-01-01",
            "display_name": "X", "kind": "single", "accept": "on",
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(email="jeune@example.com").exists())

    def test_signup_starts_trial(self):
        res = self.client.post("/comptes/inscription/", {
            "email": "nouveau@example.com", "password": "motdepasse10", "birth_date": "1990-05-05",
            "display_name": "Nouveau", "kind": "single",
            "age_confirm": "on", "accept": "on", "intimate": "on",
        })
        user = get_user_model().objects.get(email="nouveau@example.com")
        self.assertTrue(in_trial(user))
        self.assertGreater(user.profile.trial_ends_at, timezone.now())
        _, b = self.make("b2@example.com", "B2")
        create_like(user.profile, b)

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
        self.assertEqual(find_contact_info("suis-moi @lea_dupont"), "handle")
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
        res = self.client.post(f"/messages/{match.id}/", {"body": "appelle-moi au 06 12 34 56 78", "client_key": "ct-1"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "premium")
        self.assertFalse(Message.objects.filter(match=match, sender=a).exists())

    def test_premium_can_share_contact_info_with_notice(self):
        user_a, a, user_b, b, match = self._match_pair()
        Subscription.objects.update_or_create(user=user_a, defaults={"status": "active", "current_period_end": timezone.now() + timedelta(days=10)})
        self.client.force_login(user_a)
        res = self.client.post(f"/messages/{match.id}/", {"body": "mon mail: a@example.com", "client_key": "ct-2"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(Message.objects.filter(match=match, sender=a).exists())
        page = self.client.get(f"/messages/{match.id}/")
        self.assertContains(page, "responsabilit")

    def test_shared_private_photo_grants_access(self):
        user_a, a, user_b, b, match = self._match_pair()
        photo = Photo(profile=a, is_primary=False, is_private=True, moderation_status="approved")
        photo.image.save("priv.jpg", jpeg(), save=True)
        self.client.force_login(user_a)
        res = self.client.post(f"/messages/{match.id}/", {"photo": str(photo.id), "client_key": "ct-3"})
        self.assertEqual(res.status_code, 302)
        self.assertTrue(PhotoGrant.objects.filter(photo=photo, grantee=b, revoked_at__isnull=True).exists())
        self.client.force_login(user_b)
        got = self.client.get(f"/photos/{photo.id}/")
        self.assertEqual(got.status_code, 200)

    def test_thread_renders_avatars_not_message_objects(self):
        user_a, a, user_b, b, match = self._match_pair()
        self.client.force_login(user_a)
        self.client.post(f"/messages/{match.id}/", {"body": "bonjour", "client_key": "ct-4"})
        page = self.client.get(f"/messages/{match.id}/")
        self.assertNotContains(page, "Message object")
        self.assertContains(page, 'class="avatar"')
        self.assertContains(page, "bonjour")

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
            "birth_date": "1992-04-04",
            "partner_name": "Partenaire",
            "partner_birth": "1993-05-05",
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
        path = urlparse(invite.body.split("consentements :\n", 1)[1].split()[0]).path
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

    def test_favorites_are_a_list(self):
        user, me = self.make("fav@example.com", "Fav")
        _, one = self.make("f1@example.com", "F1")
        _, two = self.make("f2@example.com", "F2")
        from swingapp.models import Favorite

        Favorite.objects.create(owner=me, target=one)
        Favorite.objects.create(owner=me, target=two)
        self.client.force_login(user)
        page = self.client.get("/decouvrir/?fav=1")
        self.assertContains(page, "F1")
        self.assertContains(page, "F2")
        self.assertEqual(page.content.count(b"tinder-card"), 0)

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


