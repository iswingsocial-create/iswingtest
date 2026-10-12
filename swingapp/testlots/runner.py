"""Orchestration : fiches, images, paquet. Reprise par empreinte de fichier déjà produit."""

import json
from datetime import date
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from swingapp.models import TestBatch
from swingapp.testlots.generate import build_profiles, prompt_for
from swingapp.testlots.images import apply_face, prepare_jpeg, provider_from_settings
from swingapp.testlots.package import write_zip


def batch_dir(batch_id):
    root = Path(settings.BASE_DIR) / "data" / "test_batches" / batch_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def run_batch(batch_id, image_dir=""):
    batch = TestBatch.objects.get(batch_id=batch_id)
    batch.status = "generating"
    batch.save(update_fields=["status"])
    params = batch.params or {}
    profiles = build_profiles(
        batch.batch_id,
        batch.seed,
        batch.reference_date,
        params.get("cities") or [],
        params,
    )
    provider = provider_from_settings(image_dir or params.get("image_dir") or "")
    ready, detail = provider.available()
    root = batch_dir(batch_id)
    checkpoint_path = root / "checkpoint.json"
    done = {}
    if checkpoint_path.is_file():
        done = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    errors = []
    provenance = {
        "provider": provider.name,
        "detail": detail,
        "generated_at": timezone.now().isoformat(),
        "terms": "Images fictives. Pas d'exclusivité juridique garantie. Pas de personne réelle visée.",
        "files": [],
    }
    if not ready:
        report = {
            "status": "images_blocked",
            "reason": detail,
            "profiles": len(profiles),
            "images_expected": sum(len(row["photos"]) for row in profiles),
            "images_ready": 0,
        }
        (root / "profiles.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "generation-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        batch.status = "images_blocked"
        batch.report = report
        batch.error = detail[:300]
        batch.finished_at = timezone.now()
        batch.save()
        return report
    for row in profiles:
        for photo in row["photos"]:
            key = photo["file"]
            target = root / key
            target.parent.mkdir(parents=True, exist_ok=True)
            if key in done and target.is_file():
                raw = target.read_bytes()
            else:
                try:
                    raw = provider.generate(row["external_key"], photo["slot"], prompt_for(row, photo["slot"]), row)
                    raw = apply_face(prepare_jpeg(raw), row["face"]) if provider.name == "openai" else raw
                    target.write_bytes(raw)
                    done[key] = True
                    checkpoint_path.write_text(json.dumps(done), encoding="utf-8")
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    continue
            photo["_bytes"] = raw
            provenance["files"].append({"file": key, "provider": provider.name, "prompt_slot": photo["slot"]})
    if errors or any("_bytes" not in photo for row in profiles for photo in row["photos"]):
        report = {"status": "images_blocked", "errors": errors[:30], "profiles": len(profiles)}
        batch.status = "images_blocked"
        batch.report = report
        batch.error = (errors[0] if errors else "images incomplètes")[:300]
        batch.finished_at = timezone.now()
        batch.save()
        return report
    report = {"status": "packaged", "profiles": len(profiles), "errors": [], "seed": batch.seed}
    dest = root / f"{batch_id}.zip"
    write_zip(dest, batch_id, batch.seed, batch.reference_date, params.get("cities") or [], profiles, provenance, report)
    batch.status = "packaged"
    batch.zip_path = str(dest)
    batch.report = report
    batch.error = ""
    batch.finished_at = timezone.now()
    batch.save()
    return report


def estimate(cities, per_city, photos):
    count = len(cities) * int(per_city)
    images = count * int(photos)
    return {"profiles": count, "images": images, "note": "Le coût dépend du fournisseur. Aucun appel payant n'est lancé sans fournisseur configuré."}


def load_sheet(batch_id):
    path = batch_dir(batch_id) / "profiles.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _inside(root, target):
    root = root.resolve()
    resolved = target.resolve()
    return resolved == root or root in resolved.parents


def coverage(batch_id):
    root = batch_dir(batch_id)
    rows = load_sheet(batch_id)
    expected = ready = 0
    for row in rows:
        for photo in row.get("photos") or []:
            expected += 1
            if (root / photo["file"]).is_file():
                ready += 1
    return {"profiles": len(rows), "expected": expected, "ready": ready}


def account_rows(batch_id, query="", limit=40):
    needle = (query or "").strip().lower()
    root = batch_dir(batch_id)
    shown = []
    matched = 0
    for row in load_sheet(batch_id):
        blob = " ".join([
            row.get("external_key") or "",
            row.get("display_name") or "",
            row.get("city") or "",
            row.get("email") or "",
        ]).lower()
        if needle and needle not in blob:
            continue
        matched += 1
        if len(shown) >= limit:
            continue
        photos = []
        for photo in row.get("photos") or []:
            photos.append({
                "slot": photo["slot"],
                "is_primary": photo.get("is_primary"),
                "is_private": photo.get("is_private"),
                "ready": (root / photo["file"]).is_file(),
            })
        shown.append({
            "external_key": row["external_key"],
            "display_name": row.get("display_name"),
            "kind": row.get("kind"),
            "city": row.get("city"),
            "face": row.get("face"),
            "email": row.get("email"),
            "photos": photos,
        })
    return {"rows": shown, "matched": matched}


def save_manual_jpeg(batch_id, external_key, slot, raw, mask=False):
    from swingapp.testlots.images import apply_face, prepare_jpeg
    from swingapp.testlots.package import LotError

    row = next((item for item in load_sheet(batch_id) if item.get("external_key") == external_key), None)
    if not row:
        raise LotError("compte inconnu dans ce lot")
    photo = next((item for item in row.get("photos") or [] if int(item["slot"]) == int(slot)), None)
    if not photo:
        raise LotError("emplacement photo inconnu")
    if not raw or len(raw) > 8 * 1024 * 1024:
        raise LotError("fichier refusé")
    try:
        processed = apply_face(raw, row.get("face") or "visible") if mask else prepare_jpeg(raw)
    except Exception as exc:
        raise LotError("image illisible") from exc
    root = batch_dir(batch_id)
    target = root / photo["file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    if not _inside(root, target):
        raise LotError("chemin refusé")
    target.write_bytes(processed)
    return photo["file"]


def save_image_archive(batch_id, payload):
    import io
    import zipfile
    from swingapp.testlots.package import LotError

    if len(payload) > 200 * 1024 * 1024:
        raise LotError("archive trop volumineuse")
    known = {row["external_key"]: row for row in load_sheet(batch_id)}
    if not known:
        raise LotError("fiches absentes")
    saved = 0
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        for info in archive.infolist():
            if info.is_dir() or info.file_size > 8 * 1024 * 1024:
                continue
            parts = Path(info.filename).parts
            if not parts or ".." in parts or Path(info.filename).is_absolute():
                raise LotError("chemin refusé")
            key, slot = _image_name(parts, known)
            if key is None:
                continue
            save_manual_jpeg(batch_id, key, slot, archive.read(info), mask=known[key].get("face") != "visible")
            saved += 1
    return saved


def _image_name(parts, known):
    name = parts[-1]
    if not name.lower().endswith(".jpg"):
        return None, None
    slot = None
    key = None
    if len(parts) >= 2 and parts[-2] in known and name[:-4].isdigit():
        key, slot = parts[-2], int(name[:-4])
    elif "_" in name:
        left, right = name[:-4].rsplit("_", 1)
        if left in known and right.isdigit():
            key, slot = left, int(right)
    return key, slot


def package_uploaded(batch_id):
    from swingapp.testlots.package import LotError, write_zip

    batch = TestBatch.objects.get(batch_id=batch_id)
    rows = load_sheet(batch_id)
    if not rows:
        raise LotError("fiches absentes : générez d'abord le lot")
    root = batch_dir(batch_id)
    missing = []
    files = []
    for row in rows:
        for photo in row["photos"]:
            path = root / photo["file"]
            if not path.is_file() or not _inside(root, path):
                missing.append(photo["file"])
                continue
            photo["_bytes"] = path.read_bytes()
            files.append({"file": photo["file"], "provider": "manual-upload", "face": row.get("face")})
    if missing:
        raise LotError(f"{len(missing)} image(s) manquante(s). Exemple : {missing[0]}")
    dest = root / f"{batch_id}.zip"
    provenance = {
        "provider": "manual-upload",
        "generated_at": timezone.now().isoformat(),
        "terms": "Images déposées par l'exploitant. Pas d'exclusivité juridique garantie. Pas de personne réelle visée.",
        "files": files,
    }
    report = {"status": "packaged", "profiles": len(rows), "source": "manual-upload", "seed": batch.seed}
    write_zip(dest, batch_id, batch.seed, batch.reference_date, (batch.params or {}).get("cities") or [], rows, provenance, report)
    batch.status = "packaged"
    batch.zip_path = str(dest)
    batch.report = report
    batch.error = ""
    batch.finished_at = timezone.now()
    batch.save()
    return dest
