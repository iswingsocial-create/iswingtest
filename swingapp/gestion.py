import hashlib
import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .choices import CATEGORY_CODES, GENDERS, LANGUAGES, LIMIT_CODES, REPORT_REASONS, SEEKING, TASTES
from .i18n import t
from .legal_seed import ensure_legal_pages
from .models import (
    AuditLog,
    Campaign,
    CampaignDelivery,
    EmailToken,
    InactivityRun,
    LegalPage,
    MessageTemplate,
    OutboundEmail,
    Partner,
    Photo,
    Profile,
    Report,
    ReportNote,
    SiteSetting,
    Subscription,
    User,
    new_token,
)
from .services import (
    can_moderate,
    ensure_message_templates,
    flush_emails,
    has_staff_perm,
    inactive_members,
    is_last_superuser,
    notify,
    prepare_image,
    prepare_video,
    poster_for_video,
    queue_email,
    send_campaign,
)

REPORT_STATUS = (
    ("open", "Nouveau"),
    ("progress", "En cours"),
    ("done", "Traité"),
    ("dismissed", "Classé sans suite"),
)
SCOPES = (
    ("one", "Un membre"),
    ("all", "Membres actifs"),
    ("real", "Comptes réels seulement"),
    ("demo", "Profils TEST seulement"),
    ("incomplete", "Profils incomplets"),
    ("trial", "Abonnements en essai"),
    ("active", "Abonnements actifs"),
)


def _boot():
    ensure_legal_pages()
    ensure_message_templates()


def _forbid(request, code):
    if has_staff_perm(request.user, code):
        return None
    return HttpResponseForbidden("permission")


def staff_only(view):
    @login_required
    def wrap(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("staff")
        _boot()
        return view(request, *args, **kwargs)

    return wrap


def _page(request, qs, per=24):
    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        page = 1
    page = max(1, page)
    total = qs.count()
    pages = max(1, (total + per - 1) // per)
    page = min(page, pages)
    start = (page - 1) * per

    def link(number):
        query = request.GET.copy()
        query["page"] = str(number)
        return "?" + query.urlencode()

    return {
        "rows": list(qs[start : start + per]),
        "page": page,
        "pages": pages,
        "total": total,
        "prev": link(page - 1) if page > 1 else "",
        "next": link(page + 1) if page < pages else "",
    }


def _years(value):
    today = timezone.now().date()
    return today.year - value.year - ((today.month, today.day) < (value.month, value.day))


def _parse_date(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def _labels(pairs, lang):
    return [(code, t(lang, key)) for code, key in pairs]


def _choice_context(lang):
    return {
        "genders": _labels(GENDERS, lang),
        "languages": _labels(LANGUAGES, lang),
        "seeking": _labels(SEEKING, lang),
        "tastes": _labels(TASTES, lang),
        "desires": [(code, t(lang, "cat_" + code)) for code in CATEGORY_CODES],
        "limits": [(code, t(lang, "lim_" + code)) for code in LIMIT_CODES],
        "sub_choices": Subscription.STATUS,
    }


def _checked(request, name, allowed):
    return [value for value in request.POST.getlist(name) if value in allowed]


@staff_only
def dashboard(request):
    stats = {
        "members": Profile.objects.count(),
        "real": Profile.objects.filter(is_demo=False).count(),
        "demos": Profile.objects.filter(is_demo=True).count(),
        "trials": Subscription.objects.filter(status="trial").count(),
        "active": Subscription.objects.filter(status="active").count(),
        "reports": Report.objects.filter(status="open").count(),
        "pending_photos": Photo.objects.filter(moderation_status="pending").count(),
        "failed_mail": OutboundEmail.objects.filter(status="failed").count(),
        "failed_campaigns": Campaign.objects.filter(status__in=("failed", "partial")).count(),
        "invites": User.objects.filter(terms_accepted_at__isnull=True, is_staff=False, is_demo=False).count(),
    }
    return render(request, "gestion/dashboard.html", {
        "section": "dash",
        "stats": stats,
        "reports": Report.objects.select_related("target", "reporter").order_by("-id")[:6],
        "status_labels": dict(REPORT_STATUS),
    })


@staff_only
def members(request):
    qs = Profile.objects.select_related("user")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(display_name__icontains=q) | Q(user__email__icontains=q) | Q(city__icontains=q))
    kind = request.GET.get("kind", "")
    if kind in ("single", "couple"):
        qs = qs.filter(kind=kind)
    demo = request.GET.get("demo", "")
    if demo == "test":
        qs = qs.filter(is_demo=True)
    elif demo == "real":
        qs = qs.filter(is_demo=False)
    if request.GET.get("suspended") == "1":
        qs = qs.filter(suspended=True)
    order = request.GET.get("order", "recent")
    if order == "name":
        qs = qs.order_by("display_name", "id")
    elif order == "city":
        qs = qs.order_by("city", "id")
    else:
        qs = qs.order_by("-id")
    return render(request, "gestion/members.html", {"section": "members", "pager": _page(request, qs), "q": q})


@staff_only
def member_add(request):
    lang = getattr(request, "lang", "fr")
    errors = []
    if request.method == "POST":
        denied = _forbid(request, "can_manage_members")
        if denied:
            return denied
        errors = _create_member(request)
        if not errors:
            return redirect("gestion_member", pk=request.created_profile_id)
    return render(request, "gestion/member_form.html", {
        "section": "members",
        "errors": errors,
        "posted": request.POST if request.method == "POST" else {},
        **_choice_context(lang),
    })


def _coord(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _create_member(request):
    errors = []
    kind = request.POST.get("kind", "single")
    if kind not in ("single", "couple"):
        errors.append("Type de profil invalide.")
    name = request.POST.get("display_name", "").strip()
    email = request.POST.get("email", "").strip().lower()
    if len(name) < 2 or len(name) > 40:
        errors.append("Le pseudonyme doit contenir de 2 à 40 caractères.")
    if "@" not in email or len(email) > 254:
        errors.append("Courriel invalide.")
    elif User.objects.filter(email__iexact=email).exists():
        errors.append("Ce courriel est déjà utilisé.")
    born = _parse_date(request.POST.get("birth_date"))
    if born is None or _years(born) < 18 or born.year < 1920:
        errors.append("La personne doit avoir 18 ans ou plus.")
    is_demo = request.POST.get("is_demo") == "1"
    if is_demo and request.POST.get("confirm_test") != "TEST":
        errors.append("Pour un profil fictif, écrivez TEST dans la case de confirmation.")
    password = request.POST.get("password", "")
    if is_demo and len(password) < 10:
        errors.append("Un profil TEST a besoin d'un mot de passe d'au moins 10 caractères.")
    gender = request.POST.get("gender", "")
    allowed_gender = {code for code, _key in GENDERS}
    if gender and gender not in allowed_gender:
        errors.append("Genre invalide.")
    partner = None
    if kind == "couple":
        partner = {
            "name": request.POST.get("partner_name", "").strip(),
            "born": _parse_date(request.POST.get("partner_birth")),
            "gender": request.POST.get("partner_gender", ""),
            "email": request.POST.get("partner_email", "").strip().lower(),
        }
        if len(partner["name"]) < 2:
            errors.append("Le pseudonyme du second partenaire est requis.")
        if partner["born"] is None or _years(partner["born"]) < 18:
            errors.append("Le second partenaire doit avoir 18 ans ou plus.")
        if partner["gender"] and partner["gender"] not in allowed_gender:
            errors.append("Genre du partenaire invalide.")
        if not is_demo and (not partner["email"] or "@" not in partner["email"]):
            errors.append("Le second partenaire réel a besoin de son propre courriel pour accepter lui-même.")
        if partner["email"] and partner["email"] == email:
            errors.append("Le courriel du partenaire doit être différent de celui du compte.")
    if errors:
        return errors
    try:
        with transaction.atomic():
            user = User(email=email, birth_date=born, is_demo=is_demo, age_proof_status="unconfirmed")
            if is_demo:
                user.adult_declared = True
                user.terms_accepted_at = timezone.now()
                user.intimate_consent = True
                user.email_verified_at = timezone.now()
                user.age_proof_status = "declared"
                user.set_password(password)
            else:
                user.adult_declared = False
                user.terms_accepted_at = None
                user.intimate_consent = False
                user.email_verified_at = None
                user.prefs_consent = False
                user.promo_consent = False
                user.set_unusable_password()
            user.save()
            lat = _coord(request.POST.get("city_lat"))
            lng = _coord(request.POST.get("city_lng"))
            profile = Profile.objects.create(
                user=user,
                kind=kind,
                display_name=name[:40],
                gender=gender,
                city=request.POST.get("city", "").strip()[:80],
                country=(request.POST.get("country", "FR").strip()[:2] or "FR").upper(),
                city_ref=(request.POST.get("city_ref") or "")[:180],
                lat=lat,
                lng=lng,
                location_updated_at=timezone.now() if lat is not None and lng is not None else None,
                languages=", ".join(_checked(request, "languages", {c for c, _k in LANGUAGES}))[:300],
                language_other=request.POST.get("language_other", "").strip()[:40],
                seeking=", ".join(_checked(request, "seeking", {c for c, _k in SEEKING})),
                tastes=", ".join(_checked(request, "tastes", {c for c, _k in TASTES})),
                desires=", ".join(_checked(request, "desires", set(CATEGORY_CODES))),
                limits=", ".join(_checked(request, "limits", set(LIMIT_CODES))),
                bio=request.POST.get("bio", "").strip()[:4000],
                is_demo=is_demo,
                visibility="public" if is_demo else "paused",
                suspended=request.POST.get("account_status") == "suspended",
                lifetime_member=request.POST.get("lifetime") == "1",
            )
            if kind == "couple":
                Partner.objects.create(
                    profile=profile,
                    display_name=partner["name"][:40],
                    birth_date=partner["born"],
                    gender=partner["gender"],
                    consent_email=partner["email"],
                    consent_at=timezone.now() if is_demo else None,
                    age_proof_status="declared",
                )
            _apply_subscription(profile, request.POST.get("sub_status", "none"))
            _save_uploads(request, profile, approve=is_demo or bool(settings.AUTO_APPROVE_PHOTOS and can_moderate(request.user)))
            if not is_demo and request.POST.get("send_invite") == "1":
                send_member_invite(profile, request)
                if kind == "couple" and partner["email"]:
                    send_partner_invite(profile, request)
            AuditLog.objects.create(
                actor=request.user,
                action="staff_add_member",
                target=str(profile.id),
                detail="TEST" if is_demo else "reel",
                reason="creation administrative",
            )
            request.created_profile_id = profile.id
    except ValueError as exc:
        return [line for line in str(exc).split("\n") if line]
    return []


def _apply_subscription(profile, status):
    allowed = {code for code, _label in Subscription.STATUS}
    if status not in allowed:
        status = "none"
    sub, _ = Subscription.objects.get_or_create(user=profile.user)
    billed = sub.source == "provider" or (sub.provider == "stripe" and bool(sub.external_id))
    if billed:
        return sub
    sub.status = status
    sub.source = "manual"
    sub.provider = "manual" if status in ("active", "trial", "canceled", "past_due") else ""
    if status == "active":
        sub.current_period_end = timezone.now() + timedelta(days=31)
        sub.cancel_at_period_end = False
    elif status == "trial":
        profile.trial_ends_at = timezone.now() + timedelta(days=7)
        profile.save(update_fields=["trial_ends_at"])
        sub.current_period_end = profile.trial_ends_at
        sub.cancel_at_period_end = False
    elif status in ("expired", "none"):
        sub.cancel_at_period_end = False
    sub.save()
    return sub


def _save_uploads(request, profile, approve):
    notes = []
    for index in range(1, 4):
        upload = request.FILES.get(f"file{index}")
        if not upload:
            continue
        try:
            _store_upload(profile, upload, request.POST.get(f"vis{index}") == "private", approve, label=f"Fichier {index}")
        except ValueError as exc:
            notes.append(str(exc))
    if notes:
        raise ValueError("\n".join(notes))


def _store_upload(profile, upload, private, approve, label="Fichier"):
    from .media_pipeline import MediaError, prepare_image, queue_video, save_photo_files, store_source

    if profile.photos.count() >= settings.MAX_PHOTOS:
        raise ValueError(f"{label} : nombre maximum de médias atteint.")
    name = (upload.name or "").lower()
    kind = "video" if name.endswith((".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpeg", ".mpg", ".wmv", ".3gp", ".mts", ".m2ts")) or (upload.content_type or "").startswith("video") else "photo"
    try:
        if kind == "video":
            path = store_source(upload, ".bin")
            queue_video(profile, path, private, upload.name or "")
            return
        cleaned = prepare_image(upload)
        photo = Photo(profile=profile, position=profile.photos.count())
        save_photo_files(photo, cleaned, private, approve)
    except MediaError as exc:
        raise ValueError(f"{label} : {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"{label} : importation impossible ({exc}).") from exc
    except Exception as exc:
        raise ValueError(f"{label} : importation impossible.") from exc


def send_member_invite(profile, request):
    EmailToken.objects.filter(user=profile.user, purpose="invite", used_at__isnull=True).update(used_at=timezone.now())
    raw, digest = new_token()
    EmailToken.objects.create(
        user=profile.user,
        purpose="invite",
        token_hash=digest,
        expires_at=timezone.now() + timedelta(days=7),
    )
    link = request.build_absolute_uri(f"/invitation/{raw}/")
    queue_email(
        profile.user.email,
        "iSwing.live — activez votre compte",
        "Bonjour,\n\n"
        "L'équipe iSwing.live a préparé un compte à votre nom. "
        "Ce message n'accepte aucune condition à votre place.\n\n"
        f"Choisissez votre mot de passe et cochez vous-même les consentements :\n{link}\n\n"
        "Le lien expire dans 7 jours.\n\n— L'équipe iSwing.live\n",
        kind="invite",
        ref=str(profile.user_id),
    )
    return link


def send_partner_invite(profile, request):
    partner = getattr(profile, "partner", None)
    if partner is None or not partner.consent_email:
        return ""
    EmailToken.objects.filter(user=profile.user, purpose="partner", used_at__isnull=True).update(used_at=timezone.now())
    raw, digest = new_token()
    EmailToken.objects.create(
        user=profile.user,
        purpose="partner",
        token_hash=digest,
        expires_at=timezone.now() + timedelta(days=7),
    )
    link = request.build_absolute_uri(f"/invitation/partenaire/{raw}/")
    queue_email(
        partner.consent_email,
        "iSwing.live — confirmation d'un profil de couple",
        f"Bonjour {partner.display_name},\n\n"
        "Un profil de couple iSwing.live cite votre pseudonyme. "
        "Votre accord n'est pas encore enregistré. Ouvrez ce lien pour accepter ou ignorer ce message :\n"
        f"{link}\n\n— L'équipe iSwing.live\n",
        kind="partner",
        ref=str(profile.id),
    )
    return link


def _invite_label(user, purpose):
    row = EmailToken.objects.filter(user=user, purpose=purpose).order_by("-id").first()
    if row is None:
        return "aucune"
    if row.used_at:
        return "acceptée"
    if row.expires_at < timezone.now():
        return "expirée"
    return "envoyée"


@staff_only
def member_detail(request, pk):
    profile = get_object_or_404(Profile.objects.select_related("user"), pk=pk)
    invite_link = ""
    partner_link = ""
    upload_error = ""
    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "subscription":
            denied = _forbid(request, "can_manage_billing")
        else:
            denied = _forbid(request, "can_manage_members")
        if denied:
            return denied
        reason = request.POST.get("reason", "").strip()[:240]
        if action == "suspend":
            profile.suspended = True
            profile.save(update_fields=["suspended"])
        elif action == "restore":
            profile.suspended = False
            profile.save(update_fields=["suspended"])
        elif action == "invite":
            invite_link = send_member_invite(profile, request)
        elif action == "partner_invite":
            partner_link = send_partner_invite(profile, request)
        elif action == "subscription":
            before = Subscription.objects.filter(user=profile.user).first()
            billed = bool(before and (before.source == "provider" or (before.provider == "stripe" and before.external_id)))
            _apply_subscription(profile, request.POST.get("sub_status", "none"))
            profile.lifetime_member = request.POST.get("lifetime") == "1"
            profile.save(update_fields=["lifetime_member"])
            if billed:
                messages.warning(request, "Abonnement facturé inchangé. Seul le membre à vie local a été enregistré. Aucune facturation externe n'a été modifiée.")
            else:
                messages.success(request, "Avantage local enregistré. Aucune facturation externe n'a été modifiée.")
        elif action == "profile":
            name = request.POST.get("display_name", "").strip()
            if 2 <= len(name) <= 40:
                profile.display_name = name
            city = request.POST.get("city", "").strip()[:80]
            profile.city = city
            profile.country = (request.POST.get("country", profile.country).strip()[:2] or profile.country).upper()
            lat = _coord(request.POST.get("city_lat"))
            lng = _coord(request.POST.get("city_lng"))
            if lat is not None and lng is not None:
                profile.lat = lat
                profile.lng = lng
                profile.location_updated_at = timezone.now()
            ref = (request.POST.get("city_ref") or "").strip()
            if ref:
                profile.city_ref = ref[:180]
            profile.bio = request.POST.get("bio", "")[:4000]
            visibility = request.POST.get("visibility", profile.visibility)
            if visibility in ("public", "discrete", "paused"):
                profile.visibility = visibility
            profile.save()
        elif action == "upload" and request.FILES.get("file"):
            try:
                _store_upload(
                    profile,
                    request.FILES["file"],
                    request.POST.get("visibility") == "private",
                    approve=profile.is_demo or (settings.AUTO_APPROVE_PHOTOS and can_moderate(request.user)),
                    label=request.FILES["file"].name or "Fichier",
                )
                messages.success(request, "Média enregistré.")
            except ValueError as exc:
                upload_error = str(exc)
        elif action == "delete" and request.POST.get("confirm") == "SUPPRIMER":
            if is_last_superuser(profile.user):
                messages.error(request, "Le dernier superadministrateur ne peut pas être supprimé.")
                return redirect("gestion_member", pk=pk)
            if not reason:
                messages.error(request, "Indiquez un motif avant de supprimer.")
                return redirect("gestion_member", pk=pk)
            AuditLog.objects.create(actor=request.user, action="staff_member", target=str(pk), detail="delete", reason=reason)
            profile.user.delete()
            return redirect("gestion_members")
        AuditLog.objects.create(actor=request.user, action="staff_member", target=str(pk), detail=action[:80], reason=reason)
        if action not in ("invite", "partner_invite") and not upload_error:
            return redirect("gestion_member", pk=pk)
    sub = Subscription.objects.filter(user=profile.user).first()
    photos = list(profile.photos.all())
    return render(request, "gestion/member.html", {
        "section": "members",
        "profile": profile,
        "partner": getattr(profile, "partner", None),
        "sub": sub,
        "photos": photos,
        "can_moderate": can_moderate(request.user),
        "sub_choices": Subscription.STATUS,
        "invite_link": invite_link if settings.DEBUG else "",
        "partner_link": partner_link if settings.DEBUG else "",
        "invite_state": _invite_label(profile.user, "invite"),
        "partner_invite_state": _invite_label(profile.user, "partner"),
        "reports": Report.objects.filter(Q(target=profile) | Q(reporter=profile)).order_by("-id")[:12],
        "status_labels": dict(REPORT_STATUS),
        "history": AuditLog.objects.filter(target=str(profile.id)).order_by("-id")[:20],
        "upload_error": upload_error,
        "billed": bool(sub and (sub.source == "provider" or (sub.provider == "stripe" and sub.external_id))),
    })


@staff_only
def media_library(request):
    moderator = can_moderate(request.user)
    qs = Photo.objects.select_related("profile", "profile__user")
    if not moderator:
        qs = qs.filter(is_private=False)
    kind = request.GET.get("type", "")
    if kind in ("photo", "video"):
        qs = qs.filter(media_type=kind)
    vis = request.GET.get("vis", "")
    if vis == "private" and moderator:
        qs = qs.filter(is_private=True)
    elif vis == "public":
        qs = qs.filter(is_private=False)
    status = request.GET.get("status", "")
    if status in ("pending", "approved", "rejected", "removed"):
        qs = qs.filter(moderation_status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(profile__display_name__icontains=q)
    day = _parse_date(request.GET.get("day"))
    if day:
        qs = qs.filter(created_at__date=day)
    if request.GET.get("audit") == "1" and moderator:
        import random

        ids = list(qs.values_list("id", flat=True))
        if ids:
            picked = random.sample(ids, k=min(12, len(ids)))
            qs = qs.filter(id__in=picked)
    qs = qs.order_by("-id")
    return render(request, "gestion/media.html", {
        "section": "media",
        "pager": _page(request, qs, per=24),
        "can_moderate": moderator,
        "audit": request.GET.get("audit") == "1",
    })


@staff_only
def reports(request):
    qs = Report.objects.select_related("target", "target__user", "reporter", "reporter__user")
    status = request.GET.get("status", "")
    if status in dict(REPORT_STATUS):
        qs = qs.filter(status=status)
    reason = request.GET.get("reason", "")
    if reason in {code for code, _key in REPORT_REASONS}:
        qs = qs.filter(reason_code=reason)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(target__display_name__icontains=q)
            | Q(reporter__display_name__icontains=q)
            | Q(target__user__email__icontains=q)
            | Q(reporter__user__email__icontains=q)
        )
    start = _parse_date(request.GET.get("start"))
    end = _parse_date(request.GET.get("end"))
    if start:
        qs = qs.filter(created_at__date__gte=start)
    if end:
        qs = qs.filter(created_at__date__lte=end)
    return render(request, "gestion/reports.html", {
        "section": "reports",
        "pager": _page(request, qs.order_by("-id")),
        "status_labels": dict(REPORT_STATUS),
        "statuses": REPORT_STATUS,
        "reasons": REPORT_REASONS,
    })


@staff_only
def report_detail(request, pk):
    report = get_object_or_404(Report.objects.select_related("target", "target__user", "reporter", "reporter__user"), pk=pk)
    if request.method == "POST":
        denied = _forbid(request, "can_manage_members")
        if denied:
            return denied
        action = request.POST.get("action", "")
        note = request.POST.get("note", "").strip()[:2000]
        if action == "status" and request.POST.get("status") in dict(REPORT_STATUS):
            report.status = request.POST.get("status")
            report.save(update_fields=["status"])
            ReportNote.objects.create(report=report, author=request.user, action=report.status, body=note or dict(REPORT_STATUS)[report.status])
        elif action == "note" and note:
            ReportNote.objects.create(report=report, author=request.user, action="note", body=note)
        elif action == "warn" and note:
            camp = Campaign.objects.create(
                sender=request.user,
                subject="Avertissement de l'équipe iSwing.live",
                body="Bonjour {display_name},\n\n" + note + "\n\n— L'équipe iSwing.live",
                channel=request.POST.get("channel") if request.POST.get("channel") in ("notice", "email", "both") else "both",
                is_promo=False,
                criteria=f"Avertissement lié au signalement #{report.id}",
                status="draft",
            )
            CampaignDelivery.objects.get_or_create(campaign=camp, user=report.target.user)
            send_campaign(camp)
            ReportNote.objects.create(report=report, author=request.user, action="warn", body=note)
        elif action == "suspend":
            report.target.suspended = True
            report.target.save(update_fields=["suspended"])
            ReportNote.objects.create(report=report, author=request.user, action="suspend", body=note or "Compte suspendu")
        elif action == "restore":
            report.target.suspended = False
            report.target.save(update_fields=["suspended"])
            ReportNote.objects.create(report=report, author=request.user, action="restore", body=note or "Compte réactivé")
        AuditLog.objects.create(actor=request.user, action="report_action", target=str(report.id), detail=action[:80])
        return redirect("gestion_report", pk=report.id)
    return render(request, "gestion/report.html", {
        "section": "reports",
        "report": report,
        "notes": report.notes.select_related("author"),
        "statuses": REPORT_STATUS,
        "status_labels": dict(REPORT_STATUS),
        "photos": list(report.target.photos.all()),
        "can_moderate": can_moderate(request.user),
    })


@staff_only
def subscriptions(request):
    qs = Subscription.objects.select_related("user", "user__profile")
    status = request.GET.get("status", "")
    if status in dict(Subscription.STATUS):
        qs = qs.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(user__email__icontains=q) | Q(user__profile__display_name__icontains=q))
    return render(request, "gestion/billing.html", {
        "section": "billing",
        "pager": _page(request, qs.order_by("-updated_at")),
        "statuses": Subscription.STATUS,
    })


def _recipients(data):
    scope = data.get("scope") or "one"
    if scope not in dict(SCOPES):
        scope = "one"
    qs = User.objects.filter(is_active=True).exclude(profile__isnull=True)
    if scope != "one":
        qs = qs.exclude(profile__suspended=True)
    if scope != "demo" and data.get("include_test") != "1":
        qs = qs.exclude(is_demo=True)
    label = dict(SCOPES)[scope]
    ambiguous = False
    if scope == "one":
        raw = (data.get("one") or "").strip()
        label = f"Un membre : {raw}"
        filt = Q(email__iexact=raw)
        if raw.isdigit():
            filt = filt | Q(profile__id=int(raw))
        else:
            filt = filt | Q(profile__display_name__iexact=raw)
        qs = qs.filter(filt)
    elif scope == "real":
        qs = qs.filter(is_demo=False)
    elif scope == "demo":
        qs = qs.filter(is_demo=True)
    elif scope == "incomplete":
        qs = qs.filter(profile__validated_at__isnull=True)
    elif scope == "trial":
        qs = qs.filter(subscription__status="trial")
    elif scope == "active":
        qs = qs.filter(subscription__status="active")
    promo = data.get("is_promo") == "1"
    excluded = 0
    if promo:
        excluded = qs.exclude(promo_consent=True).count()
        qs = qs.filter(promo_consent=True)
        label += " — promotionnel, consentement requis"
    else:
        label += " — message de service"
    total = qs.distinct().count()
    if scope == "one" and total > 1 and "@" not in (data.get("one") or "") and not (data.get("one") or "").strip().isdigit():
        ambiguous = True
        label += " — plusieurs membres, précisez le courriel ou le numéro"
        return [], label[:300], excluded, False, True
    if total > 5000:
        label += " — trop de destinataires, affinez les critères"
        return [], label[:300], excluded, True, False
    users = list(qs.distinct().select_related("profile"))
    return users, label[:300], excluded, False, ambiguous


@staff_only
def communications(request):
    camps = Campaign.objects.select_related("sender").order_by("-id")
    return render(request, "gestion/comms.html", {
        "section": "messages",
        "pager": _page(request, camps),
        "templates": MessageTemplate.objects.order_by("name"),
    })


@staff_only
def communication_new(request):
    denied = _forbid(request, "can_manage_comms") if request.method == "POST" else None
    if denied:
        return denied
    chosen = None
    preset = ""
    if request.method != "POST":
        chosen = MessageTemplate.objects.filter(code=request.GET.get("template", "")).first()
        preset = request.GET.get("user", "").strip()
        if preset.isdigit() and not Profile.objects.filter(pk=int(preset)).exists():
            preset = ""
    preview = None
    if request.method == "POST":
        users, criteria, excluded, too_many, ambiguous = _recipients(request.POST)
        channel = request.POST.get("channel") if request.POST.get("channel") in ("notice", "email", "both") else "notice"
        subject = request.POST.get("subject", "").strip()[:180]
        body = request.POST.get("body", "").strip()
        sample = ""
        if users:
            sample = "iSwing.live — " + (subject or "message") + "\n\n" + body.replace("{display_name}", users[0].profile.display_name)
        raw_when = (request.POST.get("scheduled_at") or "").strip()
        scheduled = _parse_when(raw_when, request.POST.get("timezone") or "UTC") if raw_when else None
        date_error = bool(raw_when) and scheduled is None
        ids = [str(user.id) for user in users]
        posted_ids = request.POST.getlist("recipient_ids")
        mismatch = request.POST.get("confirm") == "1" and (
            request.POST.get("expected_count") != str(len(users)) or set(posted_ids) != set(ids)
        )
        if date_error or too_many or ambiguous:
            mismatch = True
        if request.POST.get("confirm") == "1" and not mismatch and subject and body and users and not date_error:
            key = (request.POST.get("client_key") or "").strip()[:64] or None
            existing = Campaign.objects.filter(client_key=key).first() if key else None
            if existing:
                return redirect("gestion_comm", pk=existing.id)
            future = bool(scheduled and scheduled > timezone.now())
            camp = Campaign.objects.create(
                sender=request.user,
                subject=subject,
                body=body,
                channel=channel,
                is_promo=request.POST.get("is_promo") == "1",
                criteria=criteria,
                client_key=key,
                scheduled_at=scheduled,
                status="scheduled" if future else "sending",
            )
            for user in users:
                CampaignDelivery.objects.get_or_create(campaign=camp, user=user)
            if camp.status == "sending":
                send_campaign(camp)
            AuditLog.objects.create(actor=request.user, action="campaign", target=str(camp.id), detail=criteria[:120], reason="envoi" if not future else "programme")
            return redirect("gestion_comm", pk=camp.id)
        preview = {
            "count": len(users),
            "ids": ids,
            "excluded": excluded,
            "criteria": criteria,
            "sample": sample,
            "mismatch": mismatch,
            "scheduled": scheduled,
            "date_error": date_error,
            "too_many": too_many,
            "ambiguous": ambiguous,
        }
    return render(request, "gestion/comm_form.html", {
        "section": "messages",
        "scopes": SCOPES,
        "templates": MessageTemplate.objects.order_by("name"),
        "chosen": chosen,
        "preview": preview,
        "preset": preset,
        "client_key": (request.POST.get("client_key") if request.method == "POST" else "") or uuid.uuid4().hex,
        "posted": request.POST if request.method == "POST" else {},
    })


def _parse_when(raw, zone="UTC"):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return None
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(zone or "UTC")
    except Exception:
        return None
    if timezone.is_naive(when):
        when = timezone.make_aware(when, tz)
    from datetime import timezone as dt_timezone

    return when.astimezone(dt_timezone.utc)


@staff_only
def communication_detail(request, pk):
    camp = get_object_or_404(Campaign.objects.select_related("sender"), pk=pk)
    if request.method == "POST":
        denied = _forbid(request, "can_manage_comms")
        if denied:
            return denied
        action = request.POST.get("action")
        if action == "retry":
            for delivery in camp.deliveries.filter(status="failed").select_related("user", "user__profile", "email"):
                from .services import deliver_campaign_row

                deliver_campaign_row(camp, delivery)
        elif action == "pause" and camp.status in ("scheduled", "sending", "partial"):
            camp.status = "paused"
            camp.save(update_fields=["status"])
            AuditLog.objects.create(actor=request.user, action="campaign_pause", target=str(camp.id), reason="pause")
        elif action == "cancel" and camp.status in ("scheduled", "paused", "sending", "partial"):
            camp.status = "canceled"
            camp.save(update_fields=["status"])
            camp.deliveries.filter(status="pending").update(status="skipped", detail="canceled")
            AuditLog.objects.create(actor=request.user, action="campaign_cancel", target=str(camp.id), reason="annulation des envois restants")
        return redirect("gestion_comm", pk=pk)
    rows = camp.deliveries.select_related("user", "user__profile", "notice", "email").order_by("id")
    return render(request, "gestion/comm_detail.html", {"section": "messages", "camp": camp, "pager": _page(request, rows, per=50)})


@staff_only
@require_POST
def template_save(request, pk):
    denied = _forbid(request, "can_manage_comms")
    if denied:
        return denied
    row = get_object_or_404(MessageTemplate, pk=pk)
    row.name = request.POST.get("name", row.name).strip()[:80] or row.name
    row.subject = request.POST.get("subject", "").strip()[:180]
    row.body = request.POST.get("body", "")
    if request.POST.get("channel") in ("notice", "email", "both"):
        row.channel = request.POST.get("channel")
    row.is_promo = request.POST.get("is_promo") == "1"
    row.save()
    return redirect("gestion_comms")


@staff_only
def settings_page(request):
    if request.method == "POST":
        denied = _forbid(request, "can_configure")
        if denied:
            return denied
        action = request.POST.get("action", "")
        if action == "quotas":
            likes = _bounded(request.POST.get("likes"), 1, 100)
            messages_cap = _bounded(request.POST.get("messages"), 0, 30)
            if likes is None or messages_cap is None:
                messages.error(request, "Quotas refusés. J'aime : nombre de 1 à 100. Messages : nombre de 0 à 30.")
            else:
                SiteSetting.objects.update_or_create(key="trial_daily_likes", defaults={"value": str(likes)})
                SiteSetting.objects.update_or_create(key="trial_messages_per_match", defaults={"value": str(messages_cap)})
                AuditLog.objects.create(actor=request.user, action="settings_update", detail="quotas")
                messages.success(request, "Quotas enregistrés.")
        elif action == "retry_mail":
            flush_emails(limit=50, force=True)
        elif action == "moderate" and request.user.is_superuser:
            flags = ("can_moderate", "can_manage_members", "can_manage_billing", "can_manage_comms", "can_configure")
            chosen = {name: set(request.POST.getlist(name)) for name in flags}
            for user in User.objects.filter(is_staff=True, is_superuser=False):
                for name in flags:
                    setattr(user, name, str(user.id) in chosen[name])
                user.save(update_fields=list(flags))
            AuditLog.objects.create(actor=request.user, action="moderate_grants", detail="updated")
        return redirect("gestion_settings")
    return render(request, "gestion/settings.html", {
        "section": "settings",
        "likes": SiteSetting.get("trial_daily_likes", "10"),
        "messages_cap": SiteSetting.get("trial_messages_per_match", "2"),
        "legal_pages": LegalPage.objects.order_by("slug"),
        "staff_users": User.objects.filter(is_staff=True).order_by("email"),
        "failed_mail": OutboundEmail.objects.filter(status="failed").order_by("-id")[:20],
        "is_super": request.user.is_superuser,
    })


def _bounded(raw, low, high):
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    if value < low or value > high:
        return None
    return value


def _email_token(raw, purpose):
    digest = hashlib.sha256(raw.encode()).hexdigest()
    row = EmailToken.objects.select_related("user").filter(token_hash=digest, purpose=purpose, used_at__isnull=True).first()
    if row is None or row.expires_at < timezone.now():
        return None
    return row


def invite_accept(request, token):
    row = _email_token(token, "invite")
    lang = getattr(request, "lang", "fr")
    if row is None:
        return render(request, "simple.html", {"title": t(lang, "link_expired"), "body": t(lang, "link_expired_body")})
    error = ""
    if request.method == "POST":
        password = request.POST.get("password", "")
        if len(password) < 10 or password != request.POST.get("password2", ""):
            error = "password"
        elif request.POST.get("age_confirm") != "1" or request.POST.get("accept") != "1" or request.POST.get("intimate") != "1":
            error = "consent"
        else:
            user = row.user
            user.set_password(password)
            user.adult_declared = True
            user.terms_accepted_at = timezone.now()
            user.intimate_consent = True
            user.email_verified_at = timezone.now()
            if user.age_proof_status == "unconfirmed":
                user.age_proof_status = "declared"
            user.save()
            profile = user.profile
            if profile.visibility == "paused" and not profile.suspended:
                profile.visibility = "public"
                profile.save(update_fields=["visibility"])
            row.used_at = timezone.now()
            row.save(update_fields=["used_at"])
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("edit_profile")
    return render(request, "invitation.html", {"mode": "account", "error": error, "email": row.user.email})


def partner_accept(request, token):
    row = _email_token(token, "partner")
    lang = getattr(request, "lang", "fr")
    if row is None:
        return render(request, "simple.html", {"title": t(lang, "link_expired"), "body": t(lang, "link_expired_body")})
    partner = getattr(row.user.profile, "partner", None)
    error = ""
    if request.method == "POST":
        if request.POST.get("accept") != "1" or partner is None:
            error = "consent"
        else:
            partner.consent_at = timezone.now()
            if partner.age_proof_status == "unconfirmed":
                partner.age_proof_status = "declared"
            partner.save(update_fields=["consent_at", "age_proof_status"])
            row.used_at = timezone.now()
            row.save(update_fields=["used_at"])
            return render(request, "simple.html", {"title": t(lang, "partner_invite_done"), "body": t(lang, "partner_invite_done_body")})
    return render(request, "invitation.html", {"mode": "partner", "error": error, "partner": partner})


def invite_hold(request):
    lang = getattr(request, "lang", "fr")
    return render(request, "simple.html", {"title": t(lang, "invite_hold_title"), "body": t(lang, "invite_hold_body")})


@staff_only
def member_preview(request, pk):
    profile = get_object_or_404(Profile.objects.select_related("user"), pk=pk)
    return render(request, "gestion/preview.html", {
        "section": "members",
        "profile": profile,
        "partner": getattr(profile, "partner", None),
        "photos": list(profile.photos.all()),
        "can_moderate": can_moderate(request.user) and bool(request.session.get("staff_2fa")),
    })


@staff_only
def audit_log(request):
    qs = AuditLog.objects.select_related("actor").order_by("-id")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(action__icontains=q) | Q(target__icontains=q) | Q(actor__email__icontains=q) | Q(reason__icontains=q))
    return render(request, "gestion/audit.html", {"section": "audit", "pager": _page(request, qs, per=40), "q": q})


@staff_only
def inactivity(request):
    if request.method == "POST":
        denied = _forbid(request, "can_manage_members")
        if denied:
            return denied
        if request.POST.get("confirm") != "SUPPRIMER":
            messages.error(request, "Suppression annulée : tapez SUPPRIMER pour confirmer.")
            return redirect("gestion_inactivity")
        qs = inactive_members()
        matched = qs.count()
        deleted = 0
        photos = 0
        for user in list(qs.select_related("profile")):
            profile = getattr(user, "profile", None)
            if profile is not None:
                photos += profile.photos.count()
            user.delete()
            deleted += 1
        InactivityRun.objects.create(
            mode="apply",
            matched=matched,
            deleted=deleted,
            detail=f"Comptes supprimés : {deleted}. Médias emportés avec les comptes : {photos}. Signalements liés aux fiches supprimées disparaissent avec elles.",
        )
        AuditLog.objects.create(actor=request.user, action="inactivity_purge", detail=str(deleted), reason="12 mois sans activité")
        messages.success(request, f"{deleted} compte(s) inactif(s) supprimé(s).")
        return redirect("gestion_inactivity")
    people = inactive_members().select_related("profile")
    return render(request, "gestion/inactivity.html", {
        "section": "inactive",
        "count": people.count(),
        "rows": list(people[:100]),
        "runs": InactivityRun.objects.all()[:15],
    })
