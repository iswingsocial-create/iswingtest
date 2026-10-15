import io
import json
import zipfile
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image

from swingapp.models import PhotoGrant, Profile, TestBatch
from swingapp.services import ensure_profile
from swingapp.testlots.generate import allocate, build_profiles
from swingapp.testlots.package import LotError, delete_lot, import_lot, verify_lot, write_zip


def _jpeg():
    img = Image.new("RGB", (640, 800), (40, 50, 90))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=80)
    return out.getvalue()


def _lot(tmp, batch_id="lottest", per_city=4):
    cities = ["Lyon|FR|45.74906|4.84789"]
    profiles = build_profiles(batch_id, "seed-1", date(2026, 10, 4), cities, {"per_city": per_city, "photos": 3, "private_photos": 1})
    raw = _jpeg()
    for row in profiles:
        for photo in row["photos"]:
            photo["_bytes"] = raw
    path = Path(tmp) / f"{batch_id}.zip"
    write_zip(path, batch_id, "seed-1", date(2026, 10, 4), cities, profiles, {"provider": "fixture"}, {"status": "fixture"})
    return path


@override_settings(ISWING_ENV="development")
class TestLotTests(TestCase):
    def test_allocate_keeps_total(self):
        counts = allocate(100, {"couple": 0.4, "single": 0.6})
        self.assertEqual(sum(counts.values()), 100)

    def test_exactly_requested_profiles_and_city(self):
        rows = build_profiles("lot", "s", date(2026, 10, 4), ["Paris|FR|48.85341|2.34880"], {"per_city": 100})
        self.assertEqual(len(rows), 100)
        self.assertTrue(all(row["city"] and row["country"] == "FR" for row in rows))
        self.assertTrue(all(len(row["people"]) == (2 if row["kind"] == "couple" else 1) for row in rows))
        self.assertTrue(all(len(row["photos"]) == 3 and sum(1 for photo in row["photos"] if photo["is_primary"]) == 1 for row in rows))

    def test_import_is_idempotent_and_private(self):
        path = _lot(self._tmp())
        first = import_lot(path)
        second = import_lot(path)
        self.assertEqual(len(first["created"]), 4)
        self.assertEqual(len(second["skipped"]), 4)
        self.assertEqual(Profile.objects.filter(is_demo=True, external_key__startswith="lottest-").count(), 4)
        profile = Profile.objects.filter(external_key__startswith="lottest-").first()
        self.assertTrue(profile.lifetime_member)
        self.assertTrue(profile.user.password.startswith("!"))
        private = profile.photos.get(is_private=True)
        other = get_user_model().objects.create_user(
            "reader@example.com", "Motdepasse-1!", birth_date=date(1990, 1, 1), terms_accepted_at=timezone.now(), adult_declared=True
        )
        ensure_profile(other)
        self.client.force_login(other)
        self.assertEqual(self.client.get(f"/photos/{private.id}/").status_code, 403)
        PhotoGrant.objects.create(photo=private, grantee=other.profile)
        self.assertEqual(self.client.get(f"/photos/{private.id}/").status_code, 200)
        PhotoGrant.objects.filter(photo=private, grantee=other.profile).update(revoked_at=profile.user.terms_accepted_at)
        self.assertEqual(self.client.get(f"/photos/{private.id}/").status_code, 403)

    def test_corrupt_zip_refused(self):
        path = self._tmp() / "bad.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../secret.txt", "x")
        with self.assertRaises(LotError):
            verify_lot(path)

    def test_delete_keeps_other_accounts(self):
        path = _lot(self._tmp())
        import_lot(path)
        real = get_user_model().objects.create_user(
            "reel@example.com", "Motdepasse-1!", birth_date=date(1991, 2, 2), terms_accepted_at=timezone.now(), adult_declared=True
        )
        delete_lot("lottest")
        self.assertFalse(Profile.objects.filter(external_key__startswith="lottest-").exists())
        self.assertTrue(get_user_model().objects.filter(pk=real.pk).exists())
        self.assertEqual(TestBatch.objects.get(batch_id="lottest").status, "deleted")

    def test_manual_upload_is_packed_per_account(self):
        import shutil
        from swingapp.testlots.runner import batch_dir, package_uploaded, save_manual_jpeg

        batch_id = "manualup"
        cities = ["Lyon|FR|45.74906|4.84789"]
        rows = build_profiles(batch_id, "seed-m", date(2026, 10, 4), cities, {"per_city": 2, "photos": 3, "private_photos": 1})
        root = batch_dir(batch_id)
        (root / "profiles.json").write_text(json.dumps(rows), encoding="utf-8")
        TestBatch.objects.create(batch_id=batch_id, name="Manuel", seed="seed-m", reference_date=date(2026, 10, 4), params={"cities": cities})
        raw = _jpeg()
        try:
            for row in rows:
                for photo in row["photos"]:
                    save_manual_jpeg(batch_id, row["external_key"], photo["slot"], raw)
            report = verify_lot(package_uploaded(batch_id))
            self.assertTrue(report["ok"])
            self.assertEqual(report["profiles"], 2)
            self.assertEqual(report["images"], 6)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_production_refuses_import(self):
        path = _lot(self._tmp(), "lotprod")
        with override_settings(ISWING_ENV="production"):
            with self.assertRaises(Exception):
                import_lot(path)

    def _tmp(self):
        root = Path(self._tmp_dir()) if False else Path("/tmp/iswing-lots")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _tmp_dir(self):
        return "/tmp/iswing-lots"
