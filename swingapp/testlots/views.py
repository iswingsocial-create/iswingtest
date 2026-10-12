import subprocess
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from swingapp.models import AuditLog, TestBatch
from swingapp.testlots.cities import CityError, resolve_city, search_cities
from swingapp.testlots.generate import defaults
from swingapp.testlots.package import LotError, delete_lot, import_lot, verify_lot
from swingapp.testlots.runner import account_rows, coverage, estimate, save_image_archive, save_manual_jpeg, package_uploaded


def _staff(request):
    if not request.user.is_authenticated or not request.user.is_staff:
        return False
    return True


@login_required
@require_http_methods(["GET", "POST"])
def test_batches(request):
    if not _staff(request):
        return HttpResponseForbidden("staff")
    opts = defaults()
    message = ""
    preview = None
    selected = []
    if request.method == "POST" and request.POST.get("action") == "search":
        selected = search_cities(request.POST.get("q", ""))
    elif request.method == "POST":
        cities = [item.strip() for item in request.POST.get("cities", "").splitlines() if item.strip()]
        try:
            opts["per_city"] = int(request.POST.get("per_city") or 100)
            opts["couple_ratio"] = float(request.POST.get("couple_ratio") or 0.4)
            opts["age_min"] = int(request.POST.get("age_min") or 25)
            opts["age_max"] = int(request.POST.get("age_max") or 65)
            opts["photos"] = int(request.POST.get("photos") or 3)
            opts["private_photos"] = int(request.POST.get("private_photos") or 1)
            for code in ("HH", "HF", "FF", "NBH", "NBF"):
                opts["compositions"][code] = float(request.POST.get(f"comp_{code}") or opts["compositions"][code])
            opts["face_mix"] = {
                "visible": float(request.POST.get("face_visible") or 0.6),
                "blurred": float(request.POST.get("face_blurred") or 0.25),
                "emoji": float(request.POST.get("face_emoji") or 0.15),
            }
            opts["languages"] = [item.strip() for item in request.POST.get("languages", "fr,en,es").split(",") if item.strip()]
            resolved = [resolve_city(item)["ref"] for item in cities]
        except (CityError, ValueError) as exc:
            message = str(exc)
            resolved = []
        else:
            preview = estimate(resolved, opts["per_city"], opts["photos"])
            preview["cities"] = resolved
            if request.POST.get("action") == "start" and settings.ISWING_ENV != "production":
                batch_id = (request.POST.get("batch_id") or "lot").strip().lower().replace(" ", "-")[:40]
                batch, created = TestBatch.objects.get_or_create(
                    batch_id=batch_id,
                    defaults={
                        "name": request.POST.get("name") or batch_id,
                        "seed": request.POST.get("seed") or "iswing",
                        "reference_date": date.today(),
                        "params": {**opts, "cities": resolved},
                    },
                )
                if not created and batch.status == "imported":
                    message = "Lot déjà importé. Choisissez un autre nom."
                else:
                    batch.params = {**opts, "cities": resolved}
                    batch.seed = request.POST.get("seed") or batch.seed
                    batch.status = "queued"
                    batch.save()
                    subprocess.Popen(
                        [sys.executable, str(Path(settings.BASE_DIR) / "manage.py"), "generate_test_batch", "--batch-id", batch.batch_id],
                        cwd=str(settings.BASE_DIR),
                    )
                    AuditLog.objects.create(actor=request.user, action="test_batch_generate", target=batch.batch_id)
                    return redirect("test_batch_detail", batch_id=batch.batch_id)
            elif request.POST.get("action") == "start":
                message = "Génération refusée en production."
    return render(request, "test_batches.html", {
        "opts": opts,
        "preview": preview,
        "message": message,
        "results": selected,
        "batches": TestBatch.objects.order_by("-id")[:20],
        "production": settings.ISWING_ENV == "production",
    })


@login_required
def test_batch_detail(request, batch_id):
    if not _staff(request):
        return HttpResponseForbidden("staff")
    batch = get_object_or_404(TestBatch, batch_id=batch_id)
    query = request.GET.get("q", "")
    return render(request, "test_batch_detail.html", {
        "batch": batch,
        "coverage": coverage(batch_id),
        "accounts": account_rows(batch_id, query),
        "query": query,
        "message": request.GET.get("message", ""),
        "production": settings.ISWING_ENV == "production",
    })


@login_required
@require_http_methods(["POST"])
def test_batch_photo(request, batch_id):
    if not _staff(request):
        return HttpResponseForbidden("staff")
    get_object_or_404(TestBatch, batch_id=batch_id)
    message = ""
    try:
        archive = request.FILES.get("archive")
        image = request.FILES.get("image")
        if archive:
            count = save_image_archive(batch_id, archive.read())
            message = f"{count} image(s) rangée(s) par compte."
        elif image:
            save_manual_jpeg(
                batch_id,
                request.POST.get("external_key", ""),
                request.POST.get("slot", ""),
                image.read(),
                mask=request.POST.get("mask") == "1",
            )
            message = "Image enregistrée pour ce compte."
        else:
            message = "Aucun fichier."
        AuditLog.objects.create(actor=request.user, action="test_batch_photo", target=batch_id)
    except (LotError, ValueError) as exc:
        message = str(exc)
    return redirect(f"/gestion/profils-test/{batch_id}/?{urlencode({'message': message})}")


@login_required
@require_http_methods(["POST"])
def test_batch_pack(request, batch_id):
    if not _staff(request):
        return HttpResponseForbidden("staff")
    if settings.ISWING_ENV == "production":
        return HttpResponseForbidden("production")
    get_object_or_404(TestBatch, batch_id=batch_id)
    try:
        package_uploaded(batch_id)
        message = "Paquet assemblé. Vous pouvez l'importer."
        AuditLog.objects.create(actor=request.user, action="test_batch_pack", target=batch_id)
    except LotError as exc:
        message = str(exc)
    return redirect(f"/gestion/profils-test/{batch_id}/?{urlencode({'message': message})}")


@login_required
@require_http_methods(["POST"])
def test_batch_import(request):
    if not _staff(request):
        return HttpResponseForbidden("staff")
    if settings.ISWING_ENV == "production":
        return HttpResponseForbidden("production")
    upload = request.FILES.get("zip")
    message = ""
    result = None
    if not upload:
        message = "ZIP manquant."
    else:
        inbox = Path(settings.BASE_DIR) / "data" / "test_batches" / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / Path(upload.name).name
        if target.suffix.lower() != ".zip":
            message = "Fichier refusé."
        else:
            target.write_bytes(upload.read())
            try:
                checked = verify_lot(target)
                if not checked["ok"]:
                    message = " ; ".join(checked["errors"][:6])
                elif request.POST.get("confirm") == "1":
                    result = import_lot(target, update=request.POST.get("update") == "1")
                    AuditLog.objects.create(actor=request.user, action="test_batch_import", target=result["batch_id"])
                else:
                    result = {"verified": checked}
            except LotError as exc:
                message = str(exc)
    return render(request, "test_batches.html", {
        "opts": defaults(),
        "preview": None,
        "message": message,
        "result": result,
        "results": [],
        "batches": TestBatch.objects.order_by("-id")[:20],
        "production": settings.ISWING_ENV == "production",
    })


@login_required
@require_http_methods(["POST"])
def test_batch_delete(request, batch_id):
    if not _staff(request):
        return HttpResponseForbidden("staff")
    try:
        count = delete_lot(batch_id)
    except LotError as exc:
        return HttpResponseForbidden(str(exc))
    AuditLog.objects.create(actor=request.user, action="test_batch_delete", target=batch_id, detail=str(count))
    return redirect("test_batches")
