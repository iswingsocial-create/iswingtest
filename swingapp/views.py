import hashlib
import json
import sqlite3
import unicodedata
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.sessions.models import Session
from django.db import transaction
from django.db.models import Q
from django.core.files.base import ContentFile
from django.http import FileResponse, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST

from .choices import ACTIVITIES, AVAILABILITY, CATEGORY_CODES, CITIES, GENDERS, LANGUAGES, ORIENTATIONS, REPORT_REASONS, SEEKING, TASTES
from .forms import PartnerForm, ProfileForm, RegisterForm
from .i18n import t
from .legal_seed import ensure_legal_pages
from .models import (
    AuditLog,
    Block,
    EmailToken,
    Favorite,
    LegalPage,
    Like,
    Match,
    Message,
    Notice,
    Partner,
    Pass,
    PaymentEvent,
    Photo,
    PhotoGrant,
    PrivateAccess,
    Profile,
    Report,
    SiteSetting,
    Subscription,
    User,
    new_token,
    new_totp_secret,
    totp_now,
    totp_valid,
)
from .services import (
    AccessError,
    QuotaError,
    approximate_distance,
    billing_state,
    blocked_ids,
    can_interact_with,
    can_view_media,
    can_view_profile,
    consume_message,
    create_like,
    haversine_km,
    has_staff_perm,
    is_last_superuser,
    maybe_validate,
    notify,
    notify_report_inbox,
    period_from_stamp,
    poster_for_video,
    prepare_image,
    prepare_video,
    quota_snapshot,
    separate_members,
    sync_trial,
    touch_activity,
    visible_queryset,
    webhook_signature_ok,
)


def _send_token(user, purpose):
    raw, digest = new_token()
    EmailToken.objects.create(
        user=user,
        purpose=purpose,
        token_hash=digest,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    return raw


def home(request):
    if request.user.is_authenticated:
        return redirect("discover")
    return render(request, "home.html")


def register(request):
    form = RegisterForm(request.POST or None)
    error = ""
    if request.method == "POST" and form.is_valid():
        if User.objects.filter(email__iexact=form.cleaned_data["email"]).exists():
            error = "email"
        else:
            user = User.objects.create_user(
                email=form.cleaned_data["email"],
                password=form.cleaned_data["password"],
                birth_date=form.cleaned_data["birth_date"],
                terms_accepted_at=timezone.now(),
                adult_declared=True,
                intimate_consent=True,
                prefs_consent=bool(form.cleaned_data.get("prefs")),
                reco_consent=bool(form.cleaned_data.get("reco")),
                promo_consent=bool(form.cleaned_data.get("promo")),
            )
            Profile.objects.create(
                user=user,
                display_name=form.cleaned_data["display_name"],
                kind=form.cleaned_data["kind"],
            )
            raw = _send_token(user, "verify")
            login(request, user)
            return render(request, "verify_sent.html", {"dev_link": f"/comptes/verifier/{raw}/" if settings.DEBUG else ""})
    return render(request, "register.html", {"form": form, "error": error})


def login_view(request):
    error = ""
    if request.method == "POST":
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        user = User.objects.filter(email__iexact=email).first()
        if user and user.locked_until and user.locked_until > timezone.now():
            error = "locked"
        else:
            auth = authenticate(request, email=email, password=password)
            if auth is None:
                if user:
                    user.failed_logins += 1
                    if user.failed_logins >= 8:
                        user.locked_until = timezone.now() + timedelta(minutes=15)
                        user.failed_logins = 0
                    user.save(update_fields=["failed_logins", "locked_until"])
                error = "bad"
            else:
                auth.failed_logins = 0
                auth.locked_until = None
                auth.save(update_fields=["failed_logins", "locked_until"])
                if auth.is_staff and auth.admin_totp_secret:
                    request.session["pre_2fa"] = auth.id
                    return redirect("admin_2fa")
                previous = request.session.get("push_user")
                endpoint = request.session.get("push_endpoint")
                login(request, auth)
                if previous and previous != auth.id and endpoint:
                    from .integrations import disable_endpoint
                    from .models import User as Account

                    old = Account.objects.filter(pk=previous).first()
                    if old:
                        disable_endpoint(old, endpoint)
                touch_activity(getattr(auth, "profile", None))
                return redirect("discover")
    return render(request, "login.html", {"error": error})


@require_POST
def logout_view(request):
    endpoint = request.session.get("push_endpoint")
    if request.user.is_authenticated and endpoint:
        from .integrations import disable_endpoint

        disable_endpoint(request.user, endpoint)
    logout(request)
    return redirect("home")


def verify_email(request, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = EmailToken.objects.filter(token_hash=digest, purpose="verify", used_at__isnull=True).first()
    if not row or row.expires_at < timezone.now():
        lang = getattr(request, "lang", "fr")
        return render(request, "simple.html", {"title": t(lang, "link_expired"), "body": t(lang, "link_expired_body")})
    row.used_at = timezone.now()
    row.save(update_fields=["used_at"])
    row.user.email_verified_at = timezone.now()
    row.user.save(update_fields=["email_verified_at"])
    maybe_validate(row.user.profile)
    lang = getattr(request, "lang", "fr")
    return render(request, "simple.html", {"title": t(lang, "email_verified"), "body": t(lang, "email_verified_body")})


def password_reset_request(request):
    dev_link = ""
    if request.method == "POST":
        user = User.objects.filter(email__iexact=request.POST.get("email", "").strip()).first()
        if user:
            raw = _send_token(user, "reset")
            if settings.DEBUG:
                dev_link = f"/comptes/mot-de-passe/{raw}/"
    return render(request, "password_reset.html", {"dev_link": dev_link})


def password_reset_confirm(request, token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    row = EmailToken.objects.filter(token_hash=digest, purpose="reset", used_at__isnull=True).first()
    if not row or row.expires_at < timezone.now():
        lang = getattr(request, "lang", "fr")
        return render(request, "simple.html", {"title": t(lang, "link_expired"), "body": t(lang, "link_expired_body")})
    if request.method == "POST":
        password = request.POST.get("password", "")
        if len(password) >= 10:
            row.user.set_password(password)
            row.user.save()
            row.used_at = timezone.now()
            row.save(update_fields=["used_at"])
            return redirect("login")
    return render(request, "password_reset_confirm.html")


def admin_2fa(request):
    user = None
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        user = request.user
    else:
        uid = request.session.get("pre_2fa")
        user = User.objects.filter(id=uid, is_staff=True).first()
    if not user:
        return redirect("login")
    error = ""
    pending = user.admin_totp_secret or request.session.get("totp_pending") or ""
    if not user.admin_totp_secret and not pending:
        pending = new_totp_secret()
        request.session["totp_pending"] = pending
    if request.method == "POST":
        if totp_valid(pending, request.POST.get("code", "").strip()):
            if not user.admin_totp_secret:
                user.admin_totp_secret = pending
                user.save(update_fields=["admin_totp_secret"])
            if not request.user.is_authenticated:
                login(request, user)
            request.session.pop("pre_2fa", None)
            request.session.pop("totp_pending", None)
            request.session["staff_2fa"] = True
            user.staff_2fa_ok = True
            return redirect("staff")
        error = "code"
    show_code = (not user.admin_totp_secret) or settings.DEBUG
    return render(request, "admin_2fa.html", {
        "error": error,
        "pending_secret": "" if user.admin_totp_secret else pending,
        "needs_setup": not user.admin_totp_secret,
        "current_code": totp_now(pending) if show_code and pending else "",
        "otp_email": user.email,
    })


def _codes(raw):
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _mapped(raw, pairs, lang):
    table = {code: key for code, key in pairs}
    return [t(lang, table[code]) for code in _codes(raw) if code in table]


def _quota_message(request, exc):
    lang = getattr(request, "lang", "fr")
    key = {
        "subscription_required": "quota_need_sub",
        "likes_exhausted": "quota_likes_done",
        "messages_exhausted": "quota_msgs_done",
    }.get(str(exc), "blocked_action")
    return t(lang, key)


@login_required
@ensure_csrf_cookie
def discover(request):
    me = request.user.profile
    sync_trial(me)
    lang = getattr(request, "lang", "fr")
    note = ""
    if me.suspended:
        note = "suspended"
    qs = visible_queryset(me)
    kind = request.GET.get("kind")
    if kind in ("single", "couple"):
        qs = qs.filter(kind=kind)
    city = request.GET.get("city", "").strip()
    if city:
        qs = qs.filter(city__icontains=city)
    activity = request.GET.get("activity", "").strip()
    if activity:
        qs = qs.filter(activities__icontains=activity)
    taste = request.GET.get("taste", "").strip()
    if taste:
        qs = qs.filter(tastes__icontains=taste)
    seeking = request.GET.get("seeking", "").strip()
    if seeking:
        qs = qs.filter(seeking__icontains=seeking)
    gender = request.GET.get("gender", "").strip()
    if gender:
        qs = qs.filter(gender=gender)
    language = request.GET.get("language", "").strip()
    if language:
        qs = qs.filter(languages__icontains=language)
    desire = request.GET.get("desire", "").strip()
    if desire:
        qs = qs.filter(desires__icontains=desire)
    if request.GET.get("recent") == "1":
        qs = qs.filter(last_active__gte=timezone.now() - timedelta(days=7))
    fav = request.GET.get("fav") == "1"
    if fav:
        qs = qs.filter(id__in=Favorite.objects.filter(owner=me).values_list("target_id", flat=True))
    already = set(Like.objects.filter(actor=me).values_list("target_id", flat=True))
    already |= set(Pass.objects.filter(actor=me).values_list("target_id", flat=True))
    try:
        min_age = int(request.GET.get("min_age") or 18)
        max_age = int(request.GET.get("max_age") or 99)
    except ValueError:
        min_age, max_age = 18, 99
    min_age = min(99, max(18, min_age))
    max_age = min(99, max(min_age, max_age))
    today = timezone.now().date()

    def _cutoff(years):
        try:
            return today.replace(year=today.year - years)
        except ValueError:
            return today.replace(year=today.year - years, day=28)

    qs = qs.filter(user__birth_date__lte=_cutoff(min_age), user__birth_date__gt=_cutoff(max_age + 1))
    max_km = (request.GET.get("max_km") or "").strip()
    distance_note = ""
    if max_km and me.lat is None:
        distance_note = "missing"
        max_km = ""
    elif max_km:
        qs = qs.exclude(lat__isnull=True)
    photos = {}
    for row in Photo.objects.filter(profile__in=qs, is_private=False, moderation_status="approved").order_by("-is_primary", "position", "id"):
        photos.setdefault(row.profile_id, row)
    cards = []
    limit = 100 if fav else 1
    scanned = 0
    for profile in qs.order_by("-last_active", "-id"):
        scanned += 1
        if scanned > 2000:
            break
        if profile.id in already and not fav:
            continue
        dist = None
        if me.lat is not None and profile.lat is not None:
            dist = haversine_km(me.lat, me.lng, profile.lat, profile.lng)
            if max_km:
                try:
                    if dist is not None and dist > float(max_km):
                        continue
                except ValueError:
                    distance_note = "invalid"
                    max_km = ""
        photo = photos.get(profile.id)
        cards.append({
            "profile": profile,
            "photo": photo,
            "km": dist,
            "distance": approximate_distance(dist) if profile.show_distance and dist is not None else None,
            "age": profile.public_age,
            "affinity": [t(lang, "cat_" + code) for code in _codes(profile.desires)],
            "kind_label": t(lang, profile.kind),
            "faved": Favorite.objects.filter(owner=me, target=profile).exists() if fav else False,
        })
        if len(cards) >= limit:
            break
    if desire:
        cards.sort(key=lambda card: (card["km"] is None, card["km"] if card["km"] is not None else 0))
    return render(request, "discover.html", {
        "cards": cards,
        "list_mode": fav,
        "distance_note": distance_note,
        "access_note": note,
        "quota": quota_snapshot(request.user),
        "activities": [(code, t(lang, key)) for code, key in ACTIVITIES],
        "tastes": [(code, t(lang, key)) for code, key in TASTES],
        "seeking_choices": [(code, t(lang, key)) for code, key in SEEKING],
        "genders": [(code, t(lang, key)) for code, key in GENDERS],
        "languages_choices": [(code, t(lang, key)) for code, key in LANGUAGES],
        "desires": [(code, t(lang, "cat_" + code)) for code in CATEGORY_CODES],
        "active_desire": desire,
    })


@login_required
def profile_detail(request, pk):
    me = request.user.profile
    profile = get_object_or_404(Profile, pk=pk)
    if not can_view_profile(me, profile):
        return render(request, "denied.html", {"reason": "profile"}, status=403)
    photos = []
    own = profile.id == me.id
    access = None if own else PrivateAccess.objects.filter(owner=profile, grantee=me).first()
    has_access = bool(access and access.status == "accepted")
    for photo in profile.photos.all():
        if not own and photo.moderation_status != "approved":
            continue
        if photo.media_type == "video" and photo.processing_status not in ("", "ready") and not own:
            continue
        if photo.is_private:
            photos.append({"photo": photo, "locked": (not own) and not has_access})
            continue
        photos.append({"photo": photo, "locked": False})
    dist = None
    if profile.show_distance and me.lat is not None and profile.lat is not None and profile.id != me.id:
        dist = approximate_distance(haversine_km(me.lat, me.lng, profile.lat, profile.lng))
    lang = getattr(request, "lang", "fr")
    own = profile.id == me.id
    show_intimate = bool(profile.user.prefs_consent) and not profile.hide_desires
    liked = Like.objects.filter(actor=me, target=profile).exists()
    faved = Favorite.objects.filter(owner=me, target=profile).exists()
    return render(request, "profile_detail.html", {
        "profile": profile,
        "photos": photos,
        "distance": dist,
        "quota": quota_snapshot(request.user),
        "own": own,
        "show_intimate": show_intimate,
        "liked": liked,
        "faved": faved,
        "access": access,
        "has_access": has_access,
        "private_count": profile.photos.filter(is_private=True).exclude(moderation_status="rejected").count(),
        "kind_label": t(lang, profile.kind),
        "gender_label": t(lang, profile.gender) if profile.gender else "",
        "orientation_label": t(lang, profile.orientation) if profile.orientation and not profile.hide_orientation else "",
        "seeking_labels": _mapped(profile.seeking, SEEKING, lang),
        "taste_labels": _mapped(profile.tastes, TASTES, lang),
        "activity_labels": _mapped(profile.activities, ACTIVITIES, lang),
        "availability_labels": _mapped(profile.availability, AVAILABILITY, lang),
        "desire_labels": [t(lang, "cat_" + code) for code in _codes(profile.desires)] if show_intimate else [],
        "limit_labels": [t(lang, "lim_" + code) for code in _codes(profile.limits)] if show_intimate else [],
        "language_labels": [profile.language_other if code == "autre" and profile.language_other else t(lang, "lang_" + code) for code in _codes(profile.languages)],
    })


@login_required
@require_POST
def like_view(request, pk):
    target = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    lang = getattr(request, "lang", "fr")
    already = Like.objects.filter(actor=me, target=target).exists()
    try:
        match = create_like(me, target)
    except QuotaError as exc:
        return JsonResponse({"ok": False, "error": _quota_message(request, exc)}, status=403)
    except AccessError:
        return JsonResponse({"ok": False, "error": t(lang, "blocked_members")}, status=403)
    if not already:
        notify(target, "like", me.display_name, f"/profil/{me.id}/")
        touch_activity(me)
    return JsonResponse({"ok": True, "match": bool(match), "already": already, "liked": True})


@login_required
@require_POST
def pass_view(request, pk):
    target = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    lang = getattr(request, "lang", "fr")
    if not can_interact_with(me, target):
        return JsonResponse({"ok": False, "error": t(lang, "blocked_members")}, status=403)
    Pass.objects.get_or_create(actor=me, target=target)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def favorite_view(request, pk):
    target = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    lang = getattr(request, "lang", "fr")
    if not can_interact_with(me, target):
        return JsonResponse({"ok": False, "error": t(lang, "blocked_members")}, status=403)
    fav = Favorite.objects.filter(owner=me, target=target).first()
    if fav:
        fav.delete()
        return JsonResponse({"ok": True, "on": False})
    Favorite.objects.create(owner=me, target=target)
    return JsonResponse({"ok": True, "on": True})


def _open_matches(profile):
    return Match.objects.filter(closed_at__isnull=True).filter(profile_a=profile) | Match.objects.filter(closed_at__isnull=True).filter(profile_b=profile)


@login_required
def matches(request):
    me = request.user.profile
    items = [{"match": match, "other": match.other(me)} for match in _open_matches(me).select_related("profile_a", "profile_b")]
    return render(request, "matches.html", {"items": items})


@login_required
def inbox(request):
    me = request.user.profile
    items = []
    for match in _open_matches(me).select_related("profile_a", "profile_b"):
        last = match.messages.order_by("-id").first()
        items.append({"match": match, "other": match.other(me), "last": last})
    return render(request, "inbox.html", {"items": items})


def _match_for(profile, pk):
    match = get_object_or_404(Match, pk=pk, closed_at__isnull=True)
    if not match.involves(profile):
        return None
    return match


@login_required
def thread(request, pk):
    me = request.user.profile
    match = _match_for(me, pk)
    if not match:
        return HttpResponseForbidden("match")
    other = match.other(me)
    if other.id in blocked_ids(me) or not can_interact_with(me, other):
        if request.method == "POST" or other.id in blocked_ids(me):
            return render(request, "denied.html", {"reason": "thread"}, status=403)
    error = ""
    locked = me.suspended or other.suspended or other.id in blocked_ids(me)
    if request.method == "POST" and not locked:
        body = request.POST.get("body", "").strip()
        photo_id = request.POST.get("photo") or None
        photo = Photo.objects.filter(pk=photo_id, profile=me).first() if photo_id else None
        client_key = request.POST.get("client_key", "")[:64]
        if not body and not photo:
            error = t(getattr(request, "lang", "fr"), "message_label")
        elif client_key and Message.objects.filter(match=match, sender=me, client_key=client_key).exists():
            return redirect("thread", pk=match.id)
        elif me.is_demo and not other.is_demo:
            error = "Un profil fictif ne peut pas écrire à un membre réel."
        else:
            try:
                with transaction.atomic():
                    consume_message(request.user, match)
                    Message.objects.create(match=match, sender=me, body=body[:2000], photo=photo, client_key=client_key)
            except QuotaError as exc:
                error = _quota_message(request, exc)
            else:
                touch_activity(me)
                return redirect("thread", pk=match.id)
    if other.read_receipts and not locked:
        match.messages.exclude(sender=me).filter(read_at__isnull=True).update(read_at=timezone.now())
    return render(request, "thread.html", {
        "match": match,
        "other": other,
        "messages": match.messages.select_related("sender", "photo"),
        "quota": quota_snapshot(request.user, match),
        "error": error,
        "locked": locked,
        "my_photos": me.photos.filter(moderation_status="approved"),
    })


@login_required
def thread_poll(request, pk):
    me = request.user.profile
    match = _match_for(me, pk)
    if not match or other_blocked(me, match):
        return JsonResponse({"messages": []}, status=403)
    try:
        after = int(request.GET.get("after") or 0)
    except ValueError:
        return JsonResponse({"messages": []}, status=400)
    rows = []
    for msg in match.messages.filter(id__gt=after).select_related("photo"):
        photo_url = ""
        video_url = ""
        if msg.photo_id and can_view_media(request.user, msg.photo):
            photo_url = f"/photos/{msg.photo_id}/"
            if msg.photo.media_type == "video" and msg.photo.video:
                video_url = f"/photos/{msg.photo_id}/fichier/"
        rows.append({
            "id": msg.id,
            "mine": msg.sender_id == me.id,
            "body": msg.body,
            "photo": photo_url,
            "video": video_url,
        })
    return JsonResponse({"messages": rows})


def other_blocked(me, match):
    other = match.other(me)
    return other.id in blocked_ids(me) or me.suspended or other.suspended


@login_required
def edit_profile(request):
    profile = request.user.profile
    lang = getattr(request, "lang", "fr")
    form = ProfileForm(request.POST or None, instance=profile, lang=lang)
    partner = getattr(profile, "partner", None)
    pform = PartnerForm(request.POST or None, prefix="p", lang=lang, initial={
        "display_name": partner.display_name if partner else "",
        "birth_date": partner.birth_date if partner else None,
        "gender": partner.gender if partner else "",
        "consent_email": partner.consent_email if partner else "",
    })
    if request.method == "POST" and form.is_valid():
        form.save()
        touch_activity(profile)
        if profile.kind == "couple" and pform.is_valid() and pform.cleaned_data.get("birth_date"):
            data = pform.cleaned_data
            partner, _ = Partner.objects.get_or_create(
                profile=profile,
                defaults={"display_name": data["display_name"] or "Partenaire", "birth_date": data["birth_date"]},
            )
            partner.display_name = data["display_name"] or partner.display_name
            partner.birth_date = data["birth_date"]
            partner.gender = data["gender"]
            partner.consent_email = data["consent_email"]
            if data.get("consent"):
                partner.consent_at = timezone.now()
            partner.save()
        maybe_validate(profile)
        return redirect("edit_profile")
    return render(request, "edit_profile.html", {
        "form": form,
        "pform": pform,
        "profile": profile,
        "quota": quota_snapshot(request.user),
        "pending_access": PrivateAccess.objects.filter(owner=profile, status="pending").select_related("grantee"),
        "granted_access": PrivateAccess.objects.filter(owner=profile, status="accepted").select_related("grantee"),
        "likers": [row.actor for row in Like.objects.filter(target=profile).select_related("actor")[:40]],
    })


def _media_redirect():
    return redirect("/moi/?onglet=medias")


@login_required
@require_POST
def upload_photo(request):
    import json

    from .media_pipeline import MediaError, assert_member_room, prepare_image, queue_video, save_photo_files, store_source

    profile = request.user.profile
    lang = getattr(request, "lang", "fr")
    if profile.photos.count() >= settings.MAX_PHOTOS:
        messages.error(request, t(lang, "upload_limit"))
        return _media_redirect()
    kind = "video" if request.POST.get("kind") == "video" else "photo"
    upload = request.FILES.get("file") or request.FILES.get("image")
    if not upload:
        messages.error(request, t(lang, "upload_missing"))
        return _media_redirect()
    if request.POST.get("media_rights") != "1" or request.POST.get("media_minor") != "1" or request.POST.get("media_host") != "1":
        messages.error(request, t(lang, "upload_rights"))
        return _media_redirect()
    private = request.POST.get("visibility") == "private"
    masks = []
    if request.POST.get("masks"):
        try:
            masks = json.loads(request.POST.get("masks") or "[]")
        except json.JSONDecodeError:
            masks = []
    try:
        assert_member_room(profile, getattr(upload, "size", 0) or 0)
        if kind == "video":
            path = store_source(upload, ".bin")
            queue_video(profile, path, private, upload.name or "")
            messages.success(request, t(lang, "upload_queued"))
            touch_activity(profile)
            return _media_redirect()
        crop = None
        if request.POST.get("crop_w"):
            crop = (request.POST.get("crop_x"), request.POST.get("crop_y"), request.POST.get("crop_w"), request.POST.get("crop_h"))
        prepared = prepare_image(upload, crop=crop, masks=masks, confirm_gif=request.POST.get("confirm_gif") == "1")
        replace_id = request.POST.get("replace")
        if replace_id and str(replace_id).isdigit():
            photo = get_object_or_404(Photo, pk=int(replace_id), profile=profile, media_type="photo")
            if photo.image:
                photo.image.delete(save=False)
            if photo.thumb:
                photo.thumb.delete(save=False)
        else:
            photo = Photo(profile=profile, position=profile.photos.count())
        save_photo_files(photo, prepared, private, settings.AUTO_APPROVE_PHOTOS)
    except MediaError as exc:
        messages.error(request, str(exc))
        return _media_redirect()
    except Exception:
        messages.error(request, t(lang, "upload_failed"))
        return _media_redirect()
    maybe_validate(profile)
    touch_activity(profile)
    messages.success(request, t(lang, "upload_ok"))
    return _media_redirect()


@login_required
@require_POST
def delete_photo(request, pk):
    from .media_pipeline import _discard

    photo = get_object_or_404(Photo, pk=pk, profile=request.user.profile)
    _discard(photo.source_path)
    photo.image.delete(save=False)
    if photo.thumb:
        photo.thumb.delete(save=False)
    if photo.video:
        photo.video.delete(save=False)
    photo.delete()
    return _media_redirect()


@login_required
@require_POST
def primary_photo(request, pk):
    profile = request.user.profile
    photo = get_object_or_404(Photo, pk=pk, profile=profile, is_private=False, media_type="photo")
    profile.photos.update(is_primary=False)
    photo.is_primary = True
    photo.save(update_fields=["is_primary"])
    return _media_redirect()


@login_required
@require_POST
def photo_visibility(request, pk):
    photo = get_object_or_404(Photo, pk=pk, profile=request.user.profile)
    photo.is_private = request.POST.get("visibility") == "private"
    if photo.is_private:
        photo.is_primary = False
    photo.save(update_fields=["is_private", "is_primary"])
    return _media_redirect()


@login_required
@require_POST
def set_location(request):
    profile = request.user.profile
    city = request.POST.get("city", "").strip()
    lat_raw = (request.POST.get("lat") or "").strip()
    lng_raw = (request.POST.get("lng") or "").strip()
    if lat_raw and lng_raw:
        try:
            lat = round(float(lat_raw), 2)
            lng = round(float(lng_raw), 2)
        except ValueError:
            return redirect("settings")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return redirect("settings")
        profile.lat = lat
        profile.lng = lng
        profile.location_updated_at = timezone.now()
    if city:
        profile.city = city[:80]
    profile.save()
    return redirect("settings")


@login_required
@require_POST
def clear_location(request):
    profile = request.user.profile
    profile.lat = None
    profile.lng = None
    profile.location_updated_at = None
    profile.save(update_fields=["lat", "lng", "location_updated_at"])
    return redirect("settings")


def _stripe_ready():
    from .integrations import stripe_ready

    return stripe_ready()


def _grant_premium(user, external_id, period_end=None, customer_id="", provider="stripe"):
    if user.is_demo:
        return None
    sub = sync_trial(user.profile)
    sub.status = "active"
    sub.provider = provider or sub.provider
    sub.source = "provider"
    if external_id:
        sub.external_id = str(external_id)[:80]
    if customer_id:
        sub.customer_id = str(customer_id)[:80]
    if period_end:
        sub.current_period_end = period_end
    elif not sub.current_period_end or sub.current_period_end < timezone.now():
        sub.current_period_end = timezone.now() + timedelta(days=31)
    sub.cancel_at_period_end = False
    sub.save()
    return sub


def _claim_payment_event(provider, event_id, digest):
    row, created = PaymentEvent.objects.get_or_create(
        provider=provider,
        event_id=event_id,
        defaults={"payload_hash": digest, "status": "received"},
    )
    if not created and row.status not in ("received", "failed"):
        return row, False
    if row.status != "received":
        row.status = "received"
        row.save(update_fields=["status"])
    return row, True


def _finish_payment_event(row, ok):
    row.status = "processed" if ok else "failed"
    row.save(update_fields=["status"])


@login_required
def billing(request):
    sub = sync_trial(request.user.profile)
    code, _fallback = billing_state(sub)
    lang = getattr(request, "lang", "fr")
    return render(request, "billing.html", {
        "quota": quota_snapshot(request.user),
        "state": code,
        "bill_label": t(lang, "bill_" + code),
        "billing_source": sub.source,
        "price": settings.MONTHLY_PRICE_USD,
        "stripe_ready": _stripe_ready(),
        "paid": request.GET.get("paid"),
        "cancelled": request.GET.get("cancel"),
        "journey": False,
    })


@login_required
def subscribe(request):
    if request.method == "POST" and _stripe_ready():
        return stripe_checkout(request)
    sub = sync_trial(request.user.profile)
    code, _fallback = billing_state(sub)
    lang = getattr(request, "lang", "fr")
    return render(request, "billing.html", {
        "quota": quota_snapshot(request.user),
        "state": code,
        "bill_label": t(lang, "bill_" + code),
        "billing_source": sub.source,
        "price": settings.MONTHLY_PRICE_USD,
        "stripe_ready": _stripe_ready(),
        "paid": None,
        "cancelled": None,
        "journey": True,
    })


@login_required
@require_POST
def stripe_checkout(request):
    if request.user.is_demo:
        messages.error(request, "Un profil TEST ne peut pas lancer un paiement réel.")
        return redirect("billing")
    if not settings.STRIPE_SECRET_KEY or not settings.STRIPE_PRICE_ID:
        from .integrations import stripe_values

        values = stripe_values()
        if not values["secret"] or not values["price"]:
            return redirect("billing")
        settings_secret = values["secret"]
        settings_price = values["price"]
    else:
        settings_secret = settings.STRIPE_SECRET_KEY
        settings_price = settings.STRIPE_PRICE_ID
    sub = sync_trial(request.user.profile)
    if sub.provider == "stripe" and sub.external_id and sub.status == "active" and sub.current_period_end and sub.current_period_end > timezone.now():
        messages.error(request, "Un abonnement facturé est déjà actif. Aucune seconde souscription n'a été créée.")
        return redirect("billing")
    import stripe
    stripe.api_key = settings_secret
    payload = {
        "mode": "subscription",
        "client_reference_id": str(request.user.id),
        "line_items": [{"price": settings_price, "quantity": 1}],
        "success_url": settings.ISWING_PUBLIC_BASE_URL + "/abonnement/?paid=1",
        "cancel_url": settings.ISWING_PUBLIC_BASE_URL + "/abonnement/?cancel=1",
        "metadata": {"user_id": str(request.user.id)},
    }
    if sub.customer_id:
        payload["customer"] = sub.customer_id
    else:
        payload["customer_email"] = request.user.email
    session = stripe.checkout.Session.create(**payload)
    return redirect(session.url, permanent=False)


@login_required
@require_POST
def cancel_subscription(request):
    sub = sync_trial(request.user.profile)
    if sub.provider == "stripe" and sub.external_id:
        from .integrations import stripe_values

        secret = settings.STRIPE_SECRET_KEY or stripe_values()["secret"]
        if not secret:
            messages.error(request, "L'annulation n'a pas été transmise : le prestataire n'est pas joignable. L'abonnement local n'a pas été modifié.")
            return redirect("billing")
        try:
            import stripe

            stripe.api_key = secret
            remote = stripe.Subscription.modify(sub.external_id, cancel_at_period_end=True)
        except Exception:
            messages.error(request, "Le prestataire a refusé l'annulation. L'abonnement reste inchangé.")
            return redirect("billing")
        stamp = remote.get("current_period_end") if isinstance(remote, dict) else getattr(remote, "current_period_end", None)
        period_end = period_from_stamp(stamp)
        sub.cancel_at_period_end = True
        sub.status = "canceled"
        if period_end:
            sub.current_period_end = period_end
        sub.save(update_fields=["cancel_at_period_end", "status", "current_period_end", "updated_at"])
        AuditLog.objects.create(actor=request.user, action="subscription_cancel", target=str(request.user.id), reason="stripe")
        messages.success(request, "Annulation programmée chez le prestataire. L'accès reste ouvert jusqu'à la fin de la période.")
        return redirect("billing")
    if sub.status in ("active", "trial"):
        sub.cancel_at_period_end = True
        sub.status = "canceled"
        sub.save(update_fields=["cancel_at_period_end", "status", "updated_at"])
        AuditLog.objects.create(actor=request.user, action="subscription_cancel", target=str(request.user.id), reason="local")
        messages.success(request, "Avantage local interrompu. Aucune facturation externe n'a été modifiée.")
    return redirect("billing")


@csrf_exempt
@require_POST
def payment_webhook(request):
    if request.headers.get("Stripe-Signature"):
        return _stripe_webhook(request)
    if not settings.PAYMENT_PROVIDER or not settings.PAYMENT_WEBHOOK_SECRET:
        return JsonResponse({"ok": False, "error": "provider_not_configured"}, status=503)
    signature = request.headers.get("X-Iswing-Signature", "")
    if not webhook_signature_ok(request.body, signature):
        return JsonResponse({"ok": False}, status=403)
    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False}, status=400)
    event_id = str(payload.get("id") or "")
    if not event_id:
        return JsonResponse({"ok": False}, status=400)
    digest = hashlib.sha256(request.body).hexdigest()
    row, fresh = _claim_payment_event(settings.PAYMENT_PROVIDER, event_id, digest)
    if not fresh:
        return JsonResponse({"ok": True, "duplicate": True})
    try:
        user = None
        if payload.get("customer_id"):
            user = User.objects.filter(subscription__customer_id=str(payload.get("customer_id"))).first()
        if user is None and payload.get("subscription_id"):
            user = User.objects.filter(subscription__external_id=str(payload.get("subscription_id"))).first()
        if user is None:
            user = User.objects.filter(email__iexact=payload.get("email") or "").first()
        if user and user.is_demo:
            _finish_payment_event(row, True)
            return JsonResponse({"ok": True, "ignored": "demo"})
        kind = payload.get("type")
        if user and kind in ("payment.succeeded", "subscription.renewed"):
            _grant_premium(
                user,
                str(payload.get("subscription_id") or ""),
                period_from_stamp(payload.get("current_period_end")),
                customer_id=str(payload.get("customer_id") or ""),
                provider=settings.PAYMENT_PROVIDER,
            )
        if user and kind == "payment.failed":
            sub = sync_trial(user.profile)
            sub.status = "past_due"
            sub.save(update_fields=["status", "updated_at"])
        if user and kind == "subscription.canceled":
            sub = sync_trial(user.profile)
            sub.status = "canceled"
            sub.cancel_at_period_end = True
            end = period_from_stamp(payload.get("current_period_end"))
            if end:
                sub.current_period_end = end
            sub.save(update_fields=["status", "cancel_at_period_end", "current_period_end", "updated_at"])
        if user and kind == "charge.refunded":
            sub = sync_trial(user.profile)
            sub.status = "expired"
            sub.current_period_end = timezone.now()
            sub.save()
    except Exception:
        _finish_payment_event(row, False)
        return JsonResponse({"ok": False}, status=500)
    _finish_payment_event(row, True)
    return JsonResponse({"ok": True})


def _stripe_webhook(request):
    from .integrations import stripe_values

    secret = settings.STRIPE_WEBHOOK_SECRET or stripe_values()["webhook"]
    if not secret:
        return JsonResponse({"ok": False, "error": "stripe_not_configured"}, status=503)
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY or None
    try:
        event = stripe.Webhook.construct_event(request.body, request.headers.get("Stripe-Signature", ""), secret)
    except Exception:
        return JsonResponse({"ok": False}, status=403)
    digest = hashlib.sha256(request.body).hexdigest()
    row, fresh = _claim_payment_event("stripe", event["id"], digest)
    if not fresh:
        return JsonResponse({"ok": True, "duplicate": True})
    try:
        data = event["data"]["object"]
        user = None
        ref = data.get("client_reference_id") or (data.get("metadata") or {}).get("user_id")
        if ref:
            user = User.objects.filter(pk=ref).first()
        customer = str(data.get("customer") or "")
        if user is None and customer:
            user = User.objects.filter(subscription__customer_id=customer).first()
        subscription_id = str(data.get("subscription") or (data.get("id") if str(data.get("object")) == "subscription" else "") or "")
        if user is None and subscription_id:
            user = User.objects.filter(subscription__external_id=subscription_id).first()
        email = data.get("customer_email") or (data.get("customer_details") or {}).get("email")
        if not user and email:
            user = User.objects.filter(email__iexact=email).first()
        if user and user.is_demo:
            _finish_payment_event(row, True)
            return JsonResponse({"ok": True, "ignored": "demo"})
        kind = event["type"]
        if user and kind in ("checkout.session.completed", "invoice.paid", "customer.subscription.updated"):
            _grant_premium(
                user,
                subscription_id or str(data.get("id") or ""),
                period_from_stamp(data.get("current_period_end")),
                customer_id=customer,
                provider="stripe",
            )
        if user and kind == "invoice.payment_failed":
            sub = sync_trial(user.profile)
            sub.status = "past_due"
            sub.provider = "stripe"
            sub.source = "provider"
            sub.save(update_fields=["status", "provider", "source", "updated_at"])
        if user and kind == "customer.subscription.deleted":
            sub = sync_trial(user.profile)
            sub.status = "canceled"
            sub.cancel_at_period_end = True
            end = period_from_stamp(data.get("current_period_end"))
            if end:
                sub.current_period_end = end
            sub.save(update_fields=["status", "cancel_at_period_end", "current_period_end", "updated_at"])
        if user and kind == "charge.refunded":
            sub = sync_trial(user.profile)
            sub.status = "expired"
            sub.current_period_end = timezone.now()
            sub.save()
    except Exception:
        _finish_payment_event(row, False)
        return JsonResponse({"ok": False}, status=500)
    _finish_payment_event(row, True)
    return JsonResponse({"ok": True})


@login_required
def settings_view(request):
    profile = request.user.profile
    lang = getattr(request, "lang", "fr")
    keys = {"public": "vis_public", "discrete": "vis_discrete", "paused": "vis_paused"}
    return render(request, "settings.html", {
        "profile": profile,
        "quota": quota_snapshot(request.user),
        "visibility_label": t(lang, keys.get(profile.visibility, "vis_public")),
    })


@login_required
def export_data(request):
    user = request.user
    profile = user.profile
    return JsonResponse({
        "email": user.email,
        "birth_year": user.birth_date.year,
        "age_proof_status": user.age_proof_status,
        "profile": {
            "display_name": profile.display_name,
            "kind": profile.kind,
            "city": profile.city,
            "bio": profile.bio,
            "visibility": profile.visibility,
        },
    })


@login_required
@require_POST
def delete_account(request):
    if request.POST.get("confirm") != "SUPPRIMER":
        return redirect("settings")
    user = request.user
    logout(request)
    user.delete()
    return redirect("home")


@login_required
@require_POST
def logout_others(request):
    keys = []
    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        data = session.get_decoded()
        if data.get("_auth_user_id") == str(request.user.id) and session.session_key != request.session.session_key:
            keys.append(session.session_key)
    Session.objects.filter(session_key__in=keys).delete()
    return redirect("settings")


@login_required
@require_POST
def report_view(request, pk):
    target = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    lang = getattr(request, "lang", "fr")
    allowed = {code: key for code, key in REPORT_REASONS}
    code = request.POST.get("reason_code", "").strip()
    if target.id == me.id or code not in allowed:
        if request.headers.get("X-Requested-With") == "fetch":
            return JsonResponse({"ok": False, "error": t(lang, "report_pick")}, status=400)
        messages.error(request, t(lang, "report_pick"))
        return redirect("profile_detail", pk=pk)
    report = Report.objects.create(
        reporter=me,
        target=target,
        reason=t(lang, allowed[code])[:240],
        reason_code=code,
        comment=request.POST.get("comment", "").strip()[:1000],
        related_ref=request.POST.get("related", "").strip()[:200],
    )
    separate_members(me, target)
    try:
        notify_report_inbox(report, request.build_absolute_uri(f"/gestion/signalements/{report.id}/"))
    except Exception:
        pass
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": True, "id": report.id})
    messages.success(request, t(lang, "report_sent"))
    return redirect("discover")


@login_required
@require_POST
def block_view(request, pk):
    target = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    blocked = False
    if target.id != me.id:
        separate_members(me, target)
        blocked = True
    if request.headers.get("X-Requested-With") == "fetch":
        return JsonResponse({"ok": blocked})
    if blocked:
        return redirect("block_followup", pk=target.id)
    return redirect("discover")


@login_required
def block_followup(request, pk):
    target = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    if not Block.objects.filter(blocker=me, blocked=target).exists():
        return redirect("discover")
    return render(request, "block_follow.html", {"target": target})


@login_required
@require_POST
def unmatch(request, pk):
    match = _match_for(request.user.profile, pk)
    if match:
        match.closed_at = timezone.now()
        match.save(update_fields=["closed_at"])
    return redirect("matches")


@login_required
def photo_file(request, pk):
    return _serve_media(request, pk, force_image=True)


@login_required
def media_file(request, pk):
    return _serve_media(request, pk, force_image=False)


def _serve_media(request, pk, force_image):
    from .media_pipeline import ranged_response

    photo = get_object_or_404(Photo, pk=pk)
    if not can_view_media(request.user, photo):
        return HttpResponseForbidden("photo")
    if not force_image and photo.media_type == "video" and photo.video and photo.processing_status in ("", "ready"):
        path = photo.video.path
        return ranged_response(request, path, "video/mp4")
    field = photo.thumb if force_image and request.GET.get("thumb") == "1" and photo.thumb else photo.image
    if not field:
        return HttpResponseForbidden("photo")
    name = str(field.name).lower()
    ctype = "image/webp" if name.endswith(".webp") else "image/jpeg"
    response = ranged_response(request, field.path, ctype)
    response["Content-Disposition"] = "inline"
    return response


@login_required
@require_POST
def grant_photo(request, pk, profile_id):
    photo = get_object_or_404(Photo, pk=pk, profile=request.user.profile, is_private=True)
    grantee = get_object_or_404(Profile, pk=profile_id)
    grant, _ = PhotoGrant.objects.get_or_create(photo=photo, grantee=grantee)
    grant.revoked_at = None
    grant.save(update_fields=["revoked_at"])
    return redirect("thread", pk=request.POST.get("match") or request.user.profile.id)


@login_required
@require_POST
def revoke_photo(request, pk, profile_id):
    photo = get_object_or_404(Photo, pk=pk, profile=request.user.profile)
    PhotoGrant.objects.filter(photo=photo, grantee_id=profile_id).update(revoked_at=timezone.now())
    return redirect("edit_profile")


def install_help(request):
    return render(request, "install.html")


def manifest(request):
    data = {
        "name": "iSwing",
        "short_name": "iSwing",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#5030e0",
        "icons": [
            {"src": "/brand/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/brand/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    }
    return JsonResponse(data)


def service_worker(request):
    js = """
const SHELL = ['/brand/css/app.css', '/brand/js/app.js', '/brand/icons/icon-192.png'];
const CACHE = 'iswing-shell-v4';
self.addEventListener('install', (event) => { self.skipWaiting(); event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))); });
self.addEventListener('activate', (event) => { event.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)))).then(() => self.clients.claim())); });
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;
  if (url.pathname.startsWith('/photos/') || url.pathname.startsWith('/messages') || url.pathname.startsWith('/parametres') || url.pathname.startsWith('/admin') || url.pathname.startsWith('/gestion')) return;
  if (SHELL.some((p) => url.pathname === p)) {
    event.respondWith(caches.match(event.request).then((hit) => hit || fetch(event.request)));
  }
});
self.addEventListener('push', (event) => {
  let data = {title: 'iSwing', body: 'Nouvelle activité', url: '/notifications/'};
  try { data = Object.assign(data, event.data.json()); } catch (error) {}
  event.waitUntil(self.registration.showNotification(data.title, {body: data.body, data: {url: data.url}}));
});
self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/notifications/';
  event.waitUntil(clients.openWindow(target));
});
"""
    return HttpResponse(js, content_type="application/javascript")


def health(request):
    return JsonResponse({"ok": True, "env": settings.ISWING_ENV})


@login_required
@require_POST
def upload_chunk(request):
    from .media_pipeline import MediaError, append_chunk, begin_upload, finish_upload
    from .models import MediaUpload

    profile = request.user.profile
    cancel = request.POST.get("cancel") == "1"
    if not cancel and request.POST.get("media_rights") != "1":
        return JsonResponse({"ok": False, "error": "Droits manquants."}, status=400)
    token = (request.POST.get("upload_id") or "").strip()
    try:
        index = int(request.POST.get("index") or 0)
        total_size = int(request.POST.get("total_size") or 0)
    except ValueError:
        return JsonResponse({"ok": False, "error": "Paramètres illisibles."}, status=400)
    chunk = request.FILES.get("chunk")
    try:
        if token:
            upload = MediaUpload.objects.get(token=token, profile=profile)
        elif request.POST.get("cancel") == "1":
            return JsonResponse({"ok": True, "canceled": True})
        else:
            if chunk is None:
                return JsonResponse({"ok": False, "error": "Morceau manquant."}, status=400)
            upload = begin_upload(
                profile,
                "video" if request.POST.get("kind") != "photo" else "photo",
                request.POST.get("filename") or "",
                total_size,
                request.POST.get("visibility") == "private",
            )
        if request.POST.get("cancel") == "1":
            from .media_pipeline import _discard

            _discard(upload.temp_path)
            upload.status = "canceled"
            upload.temp_path = ""
            upload.save(update_fields=["status", "temp_path"])
            return JsonResponse({"ok": True, "canceled": True, "upload_id": upload.token})
        if chunk is None:
            return JsonResponse({"ok": False, "error": "Morceau manquant."}, status=400)
        if chunk.size > 2_000_000:
            return JsonResponse({"ok": False, "error": "Morceau trop grand."}, status=400)
        append_chunk(upload, index, chunk.read())
        done = None
        if upload.status == "checking" and not upload.photo_id:
            done = finish_upload(upload, approve=settings.AUTO_APPROVE_PHOTOS)
        photo = done or upload.photo
        return JsonResponse({
            "ok": True,
            "upload_id": upload.token,
            "received": upload.received,
            "next_index": upload.next_index,
            "status": photo.processing_status if photo else upload.status,
            "photo_id": photo.id if photo else None,
            "label": "",
        })
    except MediaUpload.DoesNotExist:
        return JsonResponse({"ok": False, "error": "Importation inconnue."}, status=404)
    except MediaError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)


@login_required
def upload_status(request, token):
    from .media_pipeline import state_label
    from .models import MediaUpload

    upload = get_object_or_404(MediaUpload, token=token, profile=request.user.profile)
    photo = upload.photo
    return JsonResponse({
        "ok": True,
        "received": upload.received,
        "total": upload.total_size,
        "next_index": upload.next_index,
        "status": state_label(photo) if photo else upload.status,
        "error": (photo.processing_error if photo else upload.error),
    })


@login_required
@require_POST
def retry_video(request, pk):
    from .media_pipeline import _release_lock, enqueue_video

    photo = get_object_or_404(Photo, pk=pk, profile=request.user.profile, media_type="video")
    if not photo.source_path:
        messages.error(request, "Le fichier source n'est plus là. Importez la vidéo à nouveau.")
        return _media_redirect()
    _release_lock(photo.id)
    photo.processing_status = "checking"
    photo.processing_error = ""
    photo.save(update_fields=["processing_status", "processing_error"])
    enqueue_video(photo.id)
    messages.success(request, "Nouvelle tentative lancée.")
    return _media_redirect()


def push_key(request):
    from .integrations import vapid_public

    return JsonResponse({"publicKey": vapid_public()})


@login_required
@require_POST
def push_register(request):
    import json

    from .integrations import remember_device

    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False}, status=400)
    endpoint = payload.get("endpoint") or ""
    keys = payload.get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return JsonResponse({"ok": False, "error": "Abonnement incomplet."}, status=400)
    remember_device(request.user, endpoint, keys["p256dh"], keys["auth"], request.META.get("HTTP_USER_AGENT", ""), payload.get("kinds"))
    request.session["push_endpoint"] = endpoint
    request.session["push_user"] = request.user.id
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_disable(request):
    from .integrations import disable_endpoint

    endpoint = request.POST.get("endpoint") or request.session.get("push_endpoint")
    disable_endpoint(request.user, endpoint)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def push_prefs(request):
    import hashlib
    import json

    from .integrations import PUSH_KINDS
    from .models import PushDevice

    try:
        payload = json.loads(request.body.decode() or "{}")
    except json.JSONDecodeError:
        return JsonResponse({"ok": False}, status=400)
    endpoint = request.session.get("push_endpoint") or ""
    if not endpoint:
        return JsonResponse({"ok": False, "error": "Aucun appareil pour cette session."}, status=400)
    digest = hashlib.sha256(endpoint.encode()).hexdigest()
    device = PushDevice.objects.filter(user=request.user, endpoint_hash=digest).first()
    if device is None:
        return JsonResponse({"ok": False, "error": "Appareil introuvable."}, status=404)
    posted = payload.get("kinds") if isinstance(payload.get("kinds"), dict) else {}
    device.kinds = {key: bool(posted.get(key)) for key in PUSH_KINDS}
    device.save(update_fields=["kinds", "updated_at"])
    return JsonResponse({"ok": True})


def unsubscribe(request, token):
    from .integrations import read_unsub

    try:
        user_id = read_unsub(token)
    except Exception:
        return render(request, "simple.html", {"title": "Lien expiré", "body": "Ce lien de désabonnement n'est plus valable."})
    user = User.objects.filter(pk=user_id).first()
    if user:
        user.promo_consent = False
        user.save(update_fields=["promo_consent"])
    return render(request, "simple.html", {"title": "Désabonnement", "body": "Vous ne recevrez plus les messages promotionnels. Les messages de service peuvent continuer."})


def robots_txt(request):
    base = settings.ISWING_PUBLIC_BASE_URL.rstrip("/")
    body = (
        "User-agent: *\n"
        "Disallow: /profil/\n"
        "Disallow: /photos/\n"
        "Disallow: /messages\n"
        "Disallow: /gestion\n"
        "Disallow: /admin\n"
        "Disallow: /moi\n"
        "Disallow: /decouvrir\n"
        "Disallow: /matchs\n"
        "Disallow: /parametres\n"
        "Disallow: /notifications\n"
        "Allow: /legal/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return HttpResponse(body, content_type="text/plain")


def sitemap_xml(request):
    base = settings.ISWING_PUBLIC_BASE_URL.rstrip("/")
    from .models import LegalPage

    urls = [base + "/"]
    for page in LegalPage.objects.all():
        urls.append(f"{base}/legal/{page.slug}/")
    body = ["<?xml version=\"1.0\" encoding=\"UTF-8\"?>", "<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"]
    body.extend(f"<url><loc>{url}</loc></url>" for url in urls)
    body.append("</urlset>")
    return HttpResponse("\n".join(body), content_type="application/xml")


def page_not_found(request, exception):
    return render(request, "error.html", {"code": 404, "title": "Page introuvable", "body": "Ce lien ne mène nulle part."}, status=404)


def permission_denied(request, exception):
    return render(request, "error.html", {"code": 403, "title": "Accès refusé", "body": "Vous n'avez pas l'autorisation d'ouvrir cette page."}, status=403)


def server_error(request):
    return render(request, "error.html", {"code": 500, "title": "Problème inattendu", "body": "L'action n'a pas abouti. Vous pouvez continuer vers la découverte."}, status=500)


def cities(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2 or len(q) > 40:
        return JsonResponse({"results": []})
    folded = "".join(ch for ch in unicodedata.normalize("NFKD", q) if not unicodedata.combining(ch))
    path = settings.BASE_DIR / "swingapp" / "cities.sqlite"
    rows = []
    if path.is_file():
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                """SELECT name, country, lat, lng FROM cities
                   WHERE name LIKE ? OR ascii LIKE ? OR name LIKE ? OR ascii LIKE ?
                   ORDER BY CASE WHEN name LIKE ? OR ascii LIKE ? THEN 0 ELSE 1 END, pop DESC LIMIT 12""",
                (q + "%", folded + "%", "%" + q + "%", "%" + folded + "%", q + "%", folded + "%"),
            ).fetchall()
        finally:
            con.close()
    if not rows:
        needle = folded.lower()
        for name, coords in CITIES.items():
            if needle in name.lower():
                rows.append((name, "", coords[0], coords[1]))
    return JsonResponse({"results": [
        {"label": f"{name}, {country}".strip().strip(","), "name": name, "country": country, "lat": lat, "lng": lng,
         "ref": f"{name}|{country}|{lat:.5f}|{lng:.5f}" if country else ""}
        for name, country, lat, lng in rows
    ]})


def legal_page(request, slug):
    ensure_legal_pages()
    page = get_object_or_404(LegalPage, slug=slug)
    lang = getattr(request, "lang", "fr")
    if lang not in ("fr", "en", "es"):
        lang = "fr"
    return render(request, "legal.html", {"title": page.title(lang), "body": page.body(lang), "slug": page.slug})


@login_required
@require_POST
def legal_save(request, slug):
    if not has_staff_perm(request.user, "can_configure"):
        return HttpResponseForbidden("configuration")
    ensure_legal_pages()
    page = get_object_or_404(LegalPage, slug=slug)
    for lang in ("fr", "en", "es"):
        title = request.POST.get(f"title_{lang}", "").strip()
        if title:
            setattr(page, f"title_{lang}", title[:180])
        if f"body_{lang}" in request.POST:
            setattr(page, f"body_{lang}", request.POST.get(f"body_{lang}", ""))
    page.save()
    AuditLog.objects.create(actor=request.user, action="legal_update", target=slug)
    return redirect("gestion_settings")


@login_required
def staff_dashboard(request):
    if not request.user.is_staff:
        return HttpResponseForbidden("staff")
    return redirect("staff")


@login_required
@require_POST
def moderate_photo(request, pk):
    from .services import can_moderate

    if not can_moderate(request.user):
        return HttpResponseForbidden("moderation")
    photo = get_object_or_404(Photo, pk=pk)
    status = request.POST.get("status", "rejected")
    if status not in ("approved", "rejected", "removed"):
        status = "rejected"
    reason = request.POST.get("reason", "").strip()[:240]
    if status in ("rejected", "removed") and not reason:
        return redirect("gestion_media")
    photo.moderation_status = status
    photo.moderation_note = reason
    if status == "removed":
        photo.is_primary = False
    photo.save(update_fields=["moderation_status", "moderation_note", "is_primary"])
    if status in ("rejected", "removed"):
        label = "retiré" if status == "removed" else "refusé"
        notify(photo.profile, "team", f"Équipe iSwing.live — un média a été {label}. {reason}", "/moi/?onglet=medias")
    AuditLog.objects.create(actor=request.user, action="photo_moderation", target=str(photo.id), detail=status)
    maybe_validate(photo.profile)
    nxt = request.POST.get("next") or ""
    if nxt.startswith("/gestion/"):
        return redirect(nxt)
    return redirect("gestion_media")


@login_required
@require_POST
def staff_profile(request, pk):
    if not has_staff_perm(request.user, "can_manage_members"):
        return HttpResponseForbidden("members")
    profile = get_object_or_404(Profile, pk=pk)
    action = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()[:240]
    if action == "delete":
        if is_last_superuser(profile.user):
            messages.error(request, "Le dernier superadministrateur ne peut pas être supprimé.")
            return redirect("gestion_members")
        if not reason:
            messages.error(request, "Indiquez un motif avant de supprimer.")
            return redirect("gestion_member", pk=pk)
        AuditLog.objects.create(actor=request.user, action="staff_profile", target=str(pk), detail="delete", reason=reason)
        profile.user.delete()
        return redirect("gestion_members")
    if action == "suspend":
        profile.suspended = True
        profile.save(update_fields=["suspended"])
    elif action == "restore":
        profile.suspended = False
        profile.save(update_fields=["suspended"])
    elif action == "verify_age":
        profile.user.age_proof_status = "verified"
        profile.user.save(update_fields=["age_proof_status"])
    elif action == "reject_age":
        profile.user.age_proof_status = "rejected"
        profile.user.save(update_fields=["age_proof_status"])
    AuditLog.objects.create(actor=request.user, action="staff_profile", target=str(pk), detail=action or "", reason=reason)
    return redirect("gestion_member", pk=pk)


@login_required
@require_POST
def request_access(request, pk):
    owner = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    if not can_view_profile(me, owner):
        return redirect("discover")
    access, _ = PrivateAccess.objects.get_or_create(owner=owner, grantee=me)
    if access.status != "accepted":
        access.status = "pending"
        access.decided_at = None
        access.save(update_fields=["status", "decided_at"])
        notify(owner, "access_request", me.display_name, "/moi/?onglet=medias")
    return redirect("profile_detail", pk=pk)


@login_required
@require_POST
def decide_access(request, pk):
    access = get_object_or_404(PrivateAccess, pk=pk, owner=request.user.profile)
    choice = request.POST.get("choice")
    if choice == "accept":
        access.status = "accepted"
        notify(access.grantee, "access_ok", access.owner.display_name, f"/profil/{access.owner_id}/")
    elif choice == "refuse":
        access.status = "refused"
        notify(access.grantee, "access_no", access.owner.display_name, "")
    elif choice == "revoke":
        access.status = "revoked"
    else:
        return _media_redirect()
    access.decided_at = timezone.now()
    access.save(update_fields=["status", "decided_at"])
    return _media_redirect()


@login_required
@require_POST
def grant_profile_access(request, pk):
    grantee = get_object_or_404(Profile, pk=pk)
    me = request.user.profile
    if grantee.id == me.id or grantee.id in blocked_ids(me):
        return _media_redirect()
    access, _ = PrivateAccess.objects.get_or_create(owner=me, grantee=grantee)
    access.status = "accepted"
    access.decided_at = timezone.now()
    access.save(update_fields=["status", "decided_at"])
    notify(grantee, "access_ok", me.display_name, f"/profil/{me.id}/")
    return _media_redirect()


@login_required
def notices(request):
    profile = request.user.profile
    rows = list(profile.notices.all()[:40])
    Notice.objects.filter(id__in=[row.id for row in rows], read_at__isnull=True).update(read_at=timezone.now())
    return render(request, "notices.html", {"notices": rows})
