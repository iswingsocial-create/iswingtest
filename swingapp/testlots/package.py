"""Paquet ZIP et importation idempotente des lots fictifs."""

import hashlib
import io
import json
import zipfile
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image

from swingapp.choices import CATEGORY_CODES, LIMIT_CODES, LANGUAGES
from swingapp.models import Partner, Photo, Profile, Subscription, TestBatch, TestPersona, User
from swingapp.testlots.cities import CityError, resolve_city
from swingapp.testlots.generate import FORMAT_VERSION

MAX_ZIP = 200 * 1024 * 1024
MAX_FILES = 8000
MAX_IMAGE = 8 * 1024 * 1024
LANG_OK = {code for code, _label in LANGUAGES}


class LotError(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_zip(dest, batch_id, seed, reference, cities, profiles, provenance, report):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": FORMAT_VERSION,
        "batch_id": batch_id,
        "seed": seed,
        "reference_date": reference.isoformat() if hasattr(reference, "isoformat") else str(reference),
        "cities": cities,
        "profiles": len(profiles),
        "images": sum(len(row["photos"]) for row in profiles),
    }
    readme = (
        "Lot fictif iSwing. is_demo=True. Domaine members.inv.\n"
        "Importer depuis Gestion > Profils de test, ou : python manage.py import_test_batch lot.zip\n"
        "Refusé en production. Ne contient aucune personne réelle ni clé API.\n"
    )
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("generation-report.json", json.dumps(report, ensure_ascii=False, indent=2))
        archive.writestr("image-provenance.json", json.dumps(provenance, ensure_ascii=False, indent=2))
        archive.writestr("README.txt", readme)
        for row in profiles:
            for photo in row["photos"]:
                raw = photo.pop("_bytes")
                photo["sha256"] = _sha(raw)
                archive.writestr(photo["file"], raw)
        archive.writestr("profiles.json", json.dumps(profiles, ensure_ascii=False, indent=2))
    return dest


def _safe_members(archive):
    total = 0
    names = archive.namelist()
    if len(names) > MAX_FILES:
        raise LotError("archive trop volumineuse")
    for info in archive.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts or info.is_dir() is False and name.endswith("/"):
            raise LotError("chemin refusé")
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise LotError("chemin refusé")
        total += info.file_size
        if total > MAX_ZIP:
            raise LotError("archive trop volumineuse")
    return names


def load_zip(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_ZIP:
        raise LotError("fichier ZIP refusé")
    with zipfile.ZipFile(path) as archive:
        names = _safe_members(archive)
        required = ["manifest.json", "profiles.json", "generation-report.json", "image-provenance.json", "README.txt"]
        missing = [name for name in required if name not in names]
        if missing:
            raise LotError("paquet incomplet : " + ", ".join(missing))
        manifest = json.loads(archive.read("manifest.json"))
        profiles = json.loads(archive.read("profiles.json"))
        report = json.loads(archive.read("generation-report.json"))
        provenance = json.loads(archive.read("image-provenance.json"))
        blobs = {}
        for row in profiles:
            for photo in row.get("photos") or []:
                rel = photo.get("file") or ""
                if rel not in names:
                    raise LotError(f"média manquant : {rel}")
                raw = archive.read(rel)
                if len(raw) > MAX_IMAGE or not raw.startswith(b"\xff\xd8"):
                    raise LotError(f"image refusée : {rel}")
                try:
                    img = Image.open(io.BytesIO(raw))
                    img.verify()
                except Exception as exc:
                    raise LotError(f"image illisible : {rel}") from exc
                digest = _sha(raw)
                if photo.get("sha256") and photo["sha256"] != digest:
                    raise LotError(f"empreinte différente : {rel}")
                photo["sha256"] = digest
                blobs[rel] = raw
    return manifest, profiles, report, provenance, blobs


def verify_lot(path):
    manifest, profiles, report, provenance, blobs = load_zip(path)
    errors = []
    if manifest.get("format") != FORMAT_VERSION:
        errors.append("version de manifeste refusée")
    keys = [row.get("external_key") for row in profiles]
    if len(keys) != len(set(keys)):
        errors.append("identifiants en double")
    expected = manifest.get("profiles")
    if expected is not None and expected != len(profiles):
        errors.append("compteur de profils incohérent")
    cities = {}
    for row in profiles:
        try:
            _check_profile(row)
            cities.setdefault(row["city_ref"], 0)
            cities[row["city_ref"]] += 1
        except (LotError, CityError) as exc:
            errors.append(f"{row.get('external_key')}: {exc}")
    return {"ok": not errors, "errors": errors, "profiles": len(profiles), "images": len(blobs), "cities": cities, "manifest": manifest, "report": report, "provenance": provenance}


def _check_profile(row):
    if row.get("kind") not in ("single", "couple"):
        raise LotError("type de profil")
    if not row.get("display_name") or len(row["display_name"]) > 40:
        raise LotError("pseudonyme")
    if not str(row.get("email", "")).endswith("@members.inv"):
        raise LotError("courriel")
    city = resolve_city(row.get("city_ref"))
    if city["name"] != row.get("city") or city["country"] != row.get("country"):
        raise LotError("ville incohérente")
    people = row.get("people") or []
    if row["kind"] == "single" and len(people) != 1:
        raise LotError("célibataire")
    if row["kind"] == "couple" and len(people) != 2:
        raise LotError("couple")
    for person in people:
        born = date.fromisoformat(person["birth_date"])
        if person.get("gender") not in ("femme", "homme", "non-binaire"):
            raise LotError("genre")
        if born.year < 1940:
            raise LotError("date de naissance")
    langs = row.get("languages") or []
    if not langs or any(code not in LANG_OK for code in langs):
        raise LotError("langue")
    for code in row.get("desires") or []:
        if code not in CATEGORY_CODES:
            raise LotError("catégorie")
    for code in row.get("limits") or []:
        if code not in LIMIT_CODES:
            raise LotError("limite")
    photos = row.get("photos") or []
    if not photos or len(photos) > 10:
        raise LotError("photos")
    primaries = [photo for photo in photos if photo.get("is_primary")]
    if len(primaries) != 1 or primaries[0].get("is_private"):
        raise LotError("photo principale")
    if any(not photo.get("file") for photo in photos):
        raise LotError("fichier photo")


def import_lot(path, update=False):
    if settings.ISWING_ENV == "production":
        raise LotError("import de lot refusé en production")
    checked = verify_lot(path)
    if not checked["ok"]:
        raise LotError("; ".join(checked["errors"][:8]))
    manifest, profiles, report, provenance, blobs = load_zip(path)
    batch_id = manifest["batch_id"]
    created, skipped, refused = [], [], []
    written = []
    try:
        with transaction.atomic():
            batch, _ = TestBatch.objects.get_or_create(
                batch_id=batch_id,
                defaults={
                    "name": batch_id,
                    "seed": str(manifest.get("seed") or ""),
                    "reference_date": date.fromisoformat(manifest["reference_date"]),
                    "status": "imported",
                    "params": {"cities": manifest.get("cities") or []},
                    "report": report,
                },
            )
            if not update and Profile.objects.filter(external_key__startswith=f"{batch_id}-", is_demo=False).exists():
                raise LotError("clé déjà utilisée par un compte réel")
            for row in profiles:
                existing = User.objects.filter(email=row["email"]).first()
                if existing and not existing.is_demo:
                    refused.append(row["external_key"])
                    continue
                if existing and not update:
                    skipped.append(row["external_key"])
                    continue
                user = _write_profile(batch, row, blobs, written, existing if update else None)
                created.append(user.email)
            batch.status = "imported"
            batch.zip_path = str(path)
            batch.finished_at = timezone.now()
            batch.report = {"created": len(created), "skipped": len(skipped), "refused": len(refused), "provenance": provenance}
            batch.save()
    except Exception:
        for path_written in written:
            Path(path_written).unlink(missing_ok=True)
        raise
    return {"created": created, "skipped": skipped, "refused": refused, "batch_id": batch_id}


def _write_profile(batch, row, blobs, written, existing):
    born = date.fromisoformat(row["people"][0]["birth_date"])
    if existing:
        user = existing
        user.is_demo = True
        user.birth_date = born
        user.save(update_fields=["is_demo", "birth_date"])
    else:
        user = User(email=row["email"], birth_date=born, terms_accepted_at=timezone.now(), adult_declared=True, is_demo=True)
        user.email_verified_at = None
        user.age_proof_status = "declared"
        user.set_unusable_password()
        user.save()
    profile, _ = Profile.objects.get_or_create(user=user, defaults={"display_name": row["display_name"], "kind": row["kind"]})
    profile.display_name = row["display_name"]
    profile.kind = row["kind"]
    profile.gender = row["gender"]
    profile.orientation = row.get("orientation") or ""
    profile.city = row["city"]
    profile.country = row["country"]
    profile.city_ref = row["city_ref"]
    profile.lat = row["lat"]
    profile.lng = row["lng"]
    profile.languages = ", ".join(row["languages"])[:300]
    profile.origins = ", ".join(row.get("origins") or [])[:160]
    profile.seeking = ", ".join(row.get("seeking") or [])
    profile.tastes = ", ".join(row.get("tastes") or [])
    profile.activities = ", ".join(row.get("activities") or [])
    profile.desires = ", ".join(row.get("desires") or [])
    profile.availability = ", ".join(row.get("availability") or [])
    profile.limits = ", ".join(row.get("limits") or [])
    profile.bio = row.get("bio") or ""
    profile.visibility = row.get("visibility") or "public"
    profile.show_distance = bool(row.get("show_distance", True))
    profile.is_demo = True
    profile.lifetime_member = True
    profile.external_key = row["external_key"]
    profile.validated_at = profile.validated_at or timezone.now()
    profile.last_active = timezone.now()
    profile.location_updated_at = timezone.now()
    profile.save()
    if row["kind"] == "couple":
        partner = row["people"][1]
        Partner.objects.update_or_create(
            profile=profile,
            defaults={
                "display_name": partner["display_name"][:40],
                "birth_date": date.fromisoformat(partner["birth_date"]),
                "gender": partner["gender"],
                "consent_at": None,
                "age_proof_status": "declared",
            },
        )
    elif hasattr(profile, "partner"):
        profile.partner.delete()
    profile.photos.all().delete()
    for photo in sorted(row["photos"], key=lambda item: item["slot"]):
        obj = Photo(
            profile=profile,
            is_primary=bool(photo["is_primary"]),
            is_private=bool(photo["is_private"]),
            position=int(photo["slot"]),
            moderation_status="approved",
        )
        obj.image.save(f"{row['external_key']}-{photo['slot']}.jpg", ContentFile(blobs[photo["file"]]), save=True)
        written.append(obj.image.path)
    Subscription.objects.update_or_create(
        user=user,
        defaults={
            "status": "active",
            "provider": "test-simulated",
            "external_id": f"test:{row['external_key']}"[:80],
            "current_period_end": timezone.now() + timedelta(days=3650),
        },
    )
    TestPersona.objects.update_or_create(
        external_key=row["external_key"],
        defaults={
            "batch": batch,
            "profile": profile,
            "visual": {"people": [person.get("visual") for person in row["people"]], "face": row.get("face")},
            "sheet": {"people": row["people"], "composition": row.get("composition")},
            "simulated": row.get("simulated") or {},
        },
    )
    return user


def delete_lot(batch_id):
    if settings.ISWING_ENV == "production":
        raise LotError("suppression de lot refusée en production")
    batch = TestBatch.objects.filter(batch_id=batch_id).first()
    keys = list(TestPersona.objects.filter(batch__batch_id=batch_id).values_list("external_key", flat=True))
    users = User.objects.filter(is_demo=True, profile__external_key__in=keys)
    real = User.objects.filter(is_demo=False, profile__external_key__in=keys)
    if real.exists():
        raise LotError("compte réel rencontré, suppression arrêtée")
    files = []
    for profile in Profile.objects.filter(external_key__in=keys, is_demo=True):
        for photo in profile.photos.all():
            if photo.image:
                files.append(photo.image.path)
    count = users.count()
    users.delete()
    for file_path in files:
        Path(file_path).unlink(missing_ok=True)
    if batch:
        batch.status = "deleted"
        batch.save(update_fields=["status"])
    return count
