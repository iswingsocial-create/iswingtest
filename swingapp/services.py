import hashlib
import hmac
import math
import os
import random
import re
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timedelta, timezone as dt_timezone
from io import BytesIO

from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.db.models import Q
from django.utils import timezone
from PIL import Image, ImageDraw

from .models import (
    AuditLog,
    Block,
    DailyUsage,
    Like,
    Match,
    MatchUsage,
    Notice,
    Pass,
    Photo,
    PhotoGrant,
    PrivateAccess,
    Profile,
    SiteSetting,
    Subscription,
    User,
)


class QuotaError(Exception):
    pass


class AccessError(Exception):
    pass


def haversine_km(lat1, lng1, lat2, lng2):
    if None in (lat1, lng1, lat2, lng2):
        return None
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def approximate_distance(km):
    if km is None:
        return None
    if km < 10:
        return "< 10 km"
    bucket = int(math.ceil(km / 5.0) * 5)
    return f"~ {bucket} km"


def ensure_profile(user):
    from .models import Partner, Profile

    seat = Partner.objects.select_related("profile__user").filter(user=user).first()
    if seat is not None:
        Profile._meta.get_field("user").remote_field.set_cached_value(user, seat.profile)
        return seat.profile
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={"display_name": (user.email or "membre").split("@")[0][:40]},
    )
    return profile


def acting_user(user):
    """Titulaire du profil : le partenaire connecté partage le même compte."""
    profile = getattr(user, "profile", None)
    if profile is not None and profile.user_id and profile.user_id != user.id:
        return profile.user
    return user


def author_label_for(profile, user):
    from .models import Partner

    seat = Partner.objects.filter(user_id=getattr(user, "id", None), profile=profile).first()
    if seat:
        return f"{profile.display_name} ({seat.display_name})"[:90]
    return (profile.display_name or "")[:90]


def ensure_subscription(user):
    ensure_profile(user)
    sub, _ = Subscription.objects.get_or_create(user=user)
    return sub


def sync_trial(profile):
    sub = ensure_subscription(profile.user)
    if profile.validated_at and not profile.trial_ends_at:
        days = int(SiteSetting.get("trial_days", settings.TRIAL_DAYS))
        profile.trial_ends_at = profile.validated_at + timedelta(days=days)
        profile.save(update_fields=["trial_ends_at"])
    if sub.status == "active" and sub.current_period_end and sub.current_period_end < timezone.now():
        sub.status = "expired"
        sub.save(update_fields=["status", "updated_at"])
    if profile.trial_ends_at and profile.trial_ends_at > timezone.now() and sub.status in ("none", "expired"):
        sub.status = "trial"
        sub.current_period_end = profile.trial_ends_at
        sub.save(update_fields=["status", "current_period_end", "updated_at"])
    if sub.status == "trial" and profile.trial_ends_at and profile.trial_ends_at <= timezone.now():
        sub.status = "expired"
        sub.save(update_fields=["status", "updated_at"])
    return sub


def is_premium(user):
    if user.is_staff or user.is_superuser:
        return True
    profile = getattr(user, "profile", None)
    if profile is not None and profile.lifetime_member:
        return True
    sub = sync_trial(profile)
    if sub.status == "active" and sub.current_period_end and sub.current_period_end > timezone.now():
        return True
    if sub.status == "canceled" and sub.current_period_end and sub.current_period_end > timezone.now():
        return True
    return False


def in_trial(user):
    sub = sync_trial(user.profile)
    return sub.status == "trial" and user.profile.trial_ends_at and user.profile.trial_ends_at > timezone.now()


def start_trial_at_signup(profile):
    """Démarre l'essai gratuit dès l'inscription (7 jours par défaut)."""
    if not profile:
        return None
    if profile.trial_ends_at and profile.trial_ends_at > timezone.now():
        return profile.subscription
    days = int(SiteSetting.get("trial_days", settings.TRIAL_DAYS))
    profile.trial_ends_at = timezone.now() + timedelta(days=days)
    profile.save(update_fields=["trial_ends_at"])
    return sync_trial(profile)


def can_interact(user):
    return is_premium(user) or in_trial(user)


def quota_snapshot(user, match=None):
    user = acting_user(user)
    sub = sync_trial(user.profile)
    premium = is_premium(user)
    likes_left = None
    msgs_left = None
    if not premium:
        limit = setting_int("trial_daily_likes", settings.TRIAL_DAILY_LIKES, 1, 100)
        usage = DailyUsage.objects.filter(user=user, day=timezone.now().date()).first()
        used = usage.likes if usage else 0
        likes_left = max(0, limit - used)
        if match:
            cap = setting_int("trial_messages_per_match", settings.TRIAL_MESSAGES_PER_MATCH, 0, 30)
            mu = MatchUsage.objects.filter(user=user, match=match).first()
            msgs_left = max(0, cap - (mu.messages_sent if mu else 0))
    return {
        "premium": premium,
        "status": sub.status,
        "period_end": sub.current_period_end,
        "likes_left": likes_left,
        "messages_left": msgs_left,
        "can_interact": can_interact(user),
    }


def setting_int(key, default, low, high):
    raw = SiteSetting.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(default)
    if value < low or value > high:
        return int(default)
    return value


def consume_like(user):
    user = acting_user(user)
    if is_premium(user):
        return
    if not in_trial(user):
        raise QuotaError("subscription_required")
    limit = setting_int("trial_daily_likes", settings.TRIAL_DAILY_LIKES, 1, 100)
    day = timezone.now().date()
    with transaction.atomic():
        usage, _ = DailyUsage.objects.select_for_update().get_or_create(user=user, day=day)
        if usage.likes >= limit:
            raise QuotaError("likes_exhausted")
        usage.likes += 1
        usage.save(update_fields=["likes"])


def consume_message(user, match):
    user = acting_user(user)
    if is_premium(user):
        return
    if not in_trial(user):
        raise QuotaError("subscription_required")
    cap = setting_int("trial_messages_per_match", settings.TRIAL_MESSAGES_PER_MATCH, 0, 30)
    with transaction.atomic():
        usage, _ = MatchUsage.objects.select_for_update().get_or_create(user=user, match=match)
        if usage.messages_sent >= cap:
            raise QuotaError("messages_exhausted")
        usage.messages_sent += 1
        usage.save(update_fields=["messages_sent"])


def blocked_ids(profile):
    a = set(Block.objects.filter(blocker=profile).values_list("blocked_id", flat=True))
    b = set(Block.objects.filter(blocked=profile).values_list("blocker_id", flat=True))
    return a | b


def open_match_between(a, b):
    return Match.objects.filter(closed_at__isnull=True).filter(
        Q(profile_a=a, profile_b=b) | Q(profile_a=b, profile_b=a)
    ).first()


def notify(profile, kind, body, url=""):
    Notice.objects.create(profile=profile, kind=kind, body=(body or "")[:4000], url=(url or "")[:200])
    if kind in ("message", "match", "access_request", "access_ok", "access_no", "team", "reminder"):
        try:
            from .integrations import send_push

            send_push(profile.user, kind, url or "/notifications/")
        except Exception:
            pass


def separate_members(a, b):
    if not a or not b or a.id == b.id:
        return
    Block.objects.get_or_create(blocker=a, blocked=b)
    Block.objects.get_or_create(blocker=b, blocked=a)
    now = timezone.now()
    Match.objects.filter(closed_at__isnull=True).filter(
        Q(profile_a=a, profile_b=b) | Q(profile_a=b, profile_b=a)
    ).update(closed_at=now)
    PrivateAccess.objects.filter(Q(owner=a, grantee=b) | Q(owner=b, grantee=a)).exclude(status="revoked").update(
        status="revoked", decided_at=now
    )
    PhotoGrant.objects.filter(
        Q(photo__profile=a, grantee=b) | Q(photo__profile=b, grantee=a),
        revoked_at__isnull=True,
    ).update(revoked_at=now)


def profile_pending(profile):
    user = profile.user
    return not user.terms_accepted_at or not user.adult_declared


def can_view_profile(viewer, profile):
    if viewer is None or profile is None:
        return False
    if viewer.id == profile.id:
        return True
    if viewer.suspended or profile.suspended:
        return False
    if profile.visibility == "paused" or profile_pending(profile):
        return False
    if profile.id in blocked_ids(viewer):
        return False
    if profile.visibility == "discrete" and not open_match_between(viewer, profile):
        return False
    return True


def can_interact_with(actor, target):
    if actor is None or target is None or actor.id == target.id:
        return False
    if actor.suspended or target.suspended:
        return False
    if actor.visibility == "paused" or target.visibility == "paused":
        return False
    if profile_pending(actor) or profile_pending(target):
        return False
    if target.id in blocked_ids(actor):
        return False
    return True


def visible_queryset(me):
    qs = Profile.objects.select_related("user").exclude(id=me.id)
    qs = qs.exclude(suspended=True).exclude(visibility="paused")
    qs = qs.exclude(user__terms_accepted_at__isnull=True).exclude(user__adult_declared=False)
    blocked = blocked_ids(me)
    if blocked:
        qs = qs.exclude(id__in=blocked)
    match_ids = []
    for match in Match.objects.filter(closed_at__isnull=True).filter(Q(profile_a=me) | Q(profile_b=me)):
        match_ids.append(match.profile_b_id if match.profile_a_id == me.id else match.profile_a_id)
    return qs.filter(Q(visibility="public") | Q(id__in=match_ids))


def has_staff_perm(user, code):
    if not getattr(user, "is_authenticated", False):
        return False
    if not (user.is_staff or user.is_superuser):
        return False
    if user.is_superuser:
        return True
    return bool(getattr(user, code, False))


def is_last_superuser(user):
    return bool(user and user.is_superuser and not User.objects.filter(is_superuser=True).exclude(pk=user.pk).exists())


def touch_activity(profile):
    if profile is None:
        return
    profile.last_active = timezone.now()
    profile.save(update_fields=["last_active"])


def can_moderate(user):
    return bool(user and getattr(user, "is_authenticated", False) and (user.is_superuser or getattr(user, "can_moderate", False)))


def can_view_media(user, photo):
    profile = getattr(user, "profile", None)
    if profile is not None and photo.profile_id == profile.id:
        return True
    if can_moderate(user) and getattr(user, "staff_2fa_ok", False):
        if photo.is_private:
            AuditLog.objects.create(
                actor=user,
                action="staff_view_private_photo",
                target=str(photo.id),
                detail=(photo.profile.display_name or "")[:80],
            )
        return True
    if (
        has_staff_perm(user, "can_manage_members")
        and getattr(user, "staff_2fa_ok", False)
        and not photo.is_private
        and photo.moderation_status == "approved"
        and photo.processing_status in ("", "ready")
    ):
        return True
    if profile is None or not can_view_profile(profile, photo.profile):
        return False
    if photo.moderation_status != "approved":
        return False
    if photo.media_type == "video" and photo.processing_status not in ("", "ready"):
        return False
    if not photo.is_private:
        return True
    if open_match_between(profile, photo.profile):
        return True
    if PrivateAccess.objects.filter(owner_id=photo.profile_id, grantee=profile, status="accepted").exists():
        return True
    return PhotoGrant.objects.filter(photo=photo, grantee=profile, revoked_at__isnull=True).exists()


_CONTACT_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_CONTACT_HANDLE_RE = re.compile(r"(?<![\w.])@[\w.]{2,}")
_CONTACT_PHONE_RE = re.compile(r"\+?[\d][\d\s.\-()]{6,}[\d]")
_CONTACT_DATE_RE = re.compile(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}")


def find_contact_info(text):
    """Détecte un e-mail, un numéro de téléphone ou un pseudo (@) dans un texte.

    Retourne "email", "phone", "handle" ou "" si rien n'est trouvé.
    """
    if not text:
        return ""
    if _CONTACT_EMAIL_RE.search(text):
        return "email"
    for match in _CONTACT_PHONE_RE.finditer(text):
        candidate = match.group(0)
        if _CONTACT_DATE_RE.search(candidate):
            continue
        digits = re.sub(r"\D", "", candidate)
        if 8 <= len(digits) <= 15:
            return "phone"
    if _CONTACT_HANDLE_RE.search(text):
        return "handle"
    return ""


def create_like(actor, target, client_key=""):
    if actor.id == target.id:
        raise AccessError("self")
    if not can_interact_with(actor, target):
        raise AccessError("blocked")
    client_key = (client_key or "").strip()[:64]
    delay = 0.02
    last = None
    for attempt in range(8):
        try:
            return _create_like_once(actor, target, client_key)
        except OperationalError as exc:
            last = exc
            if attempt == 7:
                break
            time.sleep(delay + random.random() * delay)
            delay = min(delay * 2, 0.2)
    raise last


def _create_like_once(actor, target, client_key):
    with transaction.atomic():
        existing = Like.objects.filter(actor=actor, target=target).first()
        if existing:
            return open_match_between(actor, target), True
        if client_key:
            keyed = Like.objects.filter(actor=actor, client_key=client_key).first()
            if keyed:
                return open_match_between(actor, keyed.target), True
        try:
            with transaction.atomic():
                Like.objects.create(actor=actor, target=target, client_key=client_key)
                consume_like(actor.user)
        except IntegrityError:
            return open_match_between(actor, target), True
        Pass.objects.filter(actor=actor, target=target).delete()
        match = None
        if Like.objects.filter(actor=target, target=actor).exists():
            a, b = sorted([actor.id, target.id])
            pa = actor if actor.id == a else target
            pb = target if actor.id == a else actor
            match, _ = Match.objects.get_or_create(profile_a=pa, profile_b=pb)
            if match.closed_at:
                match.closed_at = None
                match.save(update_fields=["closed_at"])
        return match, False


def prepare_image(uploaded, crop=None, masks=None, confirm_gif=False):
    from .media_pipeline import prepare_image as prepare

    return prepare(uploaded, crop=crop, masks=masks, confirm_gif=confirm_gif)


def ImageOps_transpose(uploaded):
    from PIL import ImageOps

    img = ImageOps.exif_transpose(Image.open(uploaded))
    return img.convert("RGB")


def apply_crop(img, crop):
    try:
        x, y, w, h = (float(crop[0]), float(crop[1]), float(crop[2]), float(crop[3]))
    except (TypeError, ValueError):
        return img
    if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x + w <= 1.01 and y + h <= 1.01):
        return img
    width, height = img.size
    box = (
        int(x * width),
        int(y * height),
        max(int(x * width) + 1, int((x + w) * width)),
        max(int(y * height) + 1, int((y + h) * height)),
    )
    box = (min(box[0], width - 1), min(box[1], height - 1), min(box[2], width), min(box[3], height))
    return img.crop(box)


def poster_for_video():
    img = Image.new("RGB", (800, 1000), (12, 8, 24))
    draw = ImageDraw.Draw(img)
    draw.ellipse((280, 380, 520, 620), fill=(80, 48, 224))
    draw.polygon([(360, 440), (360, 560), (470, 500)], fill=(255, 255, 255))
    out = BytesIO()
    img.save(out, format="JPEG", quality=80)
    out.seek(0)
    return out


def prepare_video(uploaded):
    from .media_pipeline import MediaError, convert_video_file

    uploaded.seek(0)
    raw = uploaded.read()
    if len(raw) > 32 * 1024 * 1024:
        raise MediaError("size", "Ce chemin ne charge pas une grande vidéo en mémoire. Utilisez l'importation par morceaux.")
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        dst = os.path.join(tmp, "out.mp4")
        with open(src, "wb") as handle:
            handle.write(raw)
        convert_video_file(src, dst)
        with open(dst, "rb") as handle:
            return handle.read(), "video/mp4"


def _video_duration(path):
    if not shutil.which("ffprobe"):
        return None
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path],
        capture_output=True, timeout=30,
    )
    if proc.returncode != 0:
        return None
    try:
        return float((proc.stdout or b"").decode().strip())
    except ValueError:
        return None


def maybe_validate(profile):
    has_photo = Photo.objects.filter(profile=profile, is_private=False, moderation_status="approved").exists()
    couple_ok = True
    if profile.kind == "couple":
        partner = getattr(profile, "partner", None)
        couple_ok = bool(partner and partner.consent_at and partner.age_years() >= 18)
    if profile.display_name and profile.city and profile.bio and has_photo and couple_ok and profile.user.email_verified_at:
        if not profile.validated_at:
            profile.validated_at = timezone.now()
            profile.save(update_fields=["validated_at"])
            sync_trial(profile)
    return profile


def webhook_signature_ok(body: bytes, header: str) -> bool:
    secret = settings.PAYMENT_WEBHOOK_SECRET
    if not secret or not header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def queue_email(to_email, subject, body, kind="message", ref=""):
    from .models import OutboundEmail

    row = OutboundEmail.objects.create(
        to_email=(to_email or "")[:254],
        subject=(subject or "")[:180],
        body=body or "",
        kind=kind,
        ref=(ref or "")[:80],
        status="pending",
    )
    deliver_email(row)
    return row


def deliver_email(row):
    from django.core.mail import EmailMultiAlternatives

    from .integrations import mail_connection, smtp_config

    from django.utils.html import escape as html_escape

    row.attempts += 1
    cfg = smtp_config("smtp")
    sender = (cfg or {}).get("from_email") or settings.DEFAULT_FROM_EMAIL
    html = "<p>" + "<br>".join(html_escape(line) for line in (row.body or "").splitlines()) + "</p>"
    try:
        message = EmailMultiAlternatives(row.subject, row.body, sender, [row.to_email], connection=mail_connection("smtp"))
        if cfg and cfg.get("reply_to"):
            message.reply_to = [cfg["reply_to"]]
        message.attach_alternative(html, "text/html")
        message.send(fail_silently=False)
    except Exception as exc:
        row.status = "failed"
        row.last_error = str(exc)[:300]
        delay = min(60, 2 ** min(row.attempts, 6))
        row.next_retry_at = timezone.now() + timedelta(minutes=delay)
        row.save(update_fields=["attempts", "status", "last_error", "next_retry_at"])
        return row
    row.status = "sent"
    row.last_error = ""
    row.sent_at = timezone.now()
    row.next_retry_at = None
    row.save(update_fields=["attempts", "status", "last_error", "sent_at", "next_retry_at"])
    return row


def flush_emails(limit=30, force=False):
    from .models import OutboundEmail

    pending = OutboundEmail.objects.filter(status="failed", attempts__lt=8)
    if not force:
        pending = pending.filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now()))
    for row in pending.order_by("id")[:limit]:
        deliver_email(row)


def notify_report_inbox(report, link):
    when = timezone.localtime(report.created_at).strftime("%Y-%m-%d %H:%M %Z")
    target = report.target
    reporter = report.reporter
    body = (
        f"Signalement iSwing.live n°{report.id}\n"
        f"Date : {when}\n"
        f"Motif : {report.reason} ({report.reason_code})\n"
        f"Commentaire : {report.comment or '—'}\n"
        f"Contenu concerné : {report.related_ref or 'profil'}\n\n"
        f"Compte signalé : #{target.id} {target.display_name} <{target.user.email}>\n"
        f"Compte à l'origine : #{reporter.id} {reporter.display_name} <{reporter.user.email}>\n\n"
        f"Dossier : {link}\n\n"
        "Aucun média n'est joint à ce courriel. La consultation se fait dans l'administration sécurisée.\n"
        "L'identité de la personne qui signale ne doit pas être transmise au membre signalé.\n"
    )
    return queue_email(
        settings.REPORT_INBOX,
        f"iSwing.live — signalement n°{report.id}",
        body,
        kind="report",
        ref=str(report.id),
    )


def personalize(text, profile):
    name = profile.display_name if profile is not None else ""
    return (text or "").replace("{display_name}", name).replace("{pseudonyme}", name)


def ensure_message_templates():
    from .models import MessageTemplate

    rows = [
        ("individual", "Message individuel", "Message de l'équipe iSwing.live", "Bonjour {display_name},\n\n", False, "both"),
        ("incomplete", "Rappel de profil incomplet", "iSwing.live — votre profil est incomplet", "Bonjour {display_name},\n\nVotre profil iSwing.live n'est pas encore complet. Vous pouvez le compléter depuis Mon profil.\n\n— L'équipe iSwing.live", False, "both"),
        ("verify", "Demande de vérification", "iSwing.live — vérification du compte", "Bonjour {display_name},\n\nL'équipe iSwing.live vous demande de confirmer les informations de votre compte. Ce message ne vaut pas une vérification d'identité.\n\n— L'équipe iSwing.live", False, "both"),
        ("warning", "Avertissement de modération", "iSwing.live — avertissement", "Bonjour {display_name},\n\nL'équipe iSwing.live vous adresse un avertissement concernant le respect des règles du service.\n\n— L'équipe iSwing.live", False, "both"),
        ("account", "Information compte ou abonnement", "iSwing.live — votre compte", "Bonjour {display_name},\n\nInformation de l'équipe iSwing.live au sujet de votre compte ou de votre abonnement.\n\n— L'équipe iSwing.live", False, "email"),
        ("announce", "Annonce générale", "iSwing.live — annonce", "Bonjour {display_name},\n\n\n\n— L'équipe iSwing.live", True, "both"),
    ]
    for code, name, subject, body, promo, channel in rows:
        MessageTemplate.objects.get_or_create(
            code=code,
            defaults={"name": name, "subject": subject, "body": body, "is_promo": promo, "channel": channel},
        )


def deliver_campaign_row(campaign, delivery):
    if delivery.status in ("sent", "skipped"):
        return delivery
    user = delivery.user
    profile = getattr(user, "profile", None)
    if profile is None:
        delivery.status = "skipped"
        delivery.detail = "no_profile"
        delivery.save(update_fields=["status", "detail"])
        return delivery
    if campaign.is_promo and not user.promo_consent:
        delivery.status = "skipped"
        delivery.detail = "promo_consent"
        delivery.save(update_fields=["status", "detail"])
        return delivery
    text = personalize(campaign.body, profile)
    if campaign.is_promo:
        from .integrations import unsub_link

        text += "\n\nPour ne plus recevoir les messages promotionnels : " + unsub_link(user)
    subject = "iSwing.live — " + personalize(campaign.subject, profile).replace("iSwing.live — ", "")
    if campaign.channel in ("notice", "both") and not delivery.notice_id:
        delivery.notice = Notice.objects.create(profile=profile, kind="team", body=text[:4000], url="/notifications/")
    email_failed = False
    if campaign.channel in ("email", "both"):
        if delivery.email_id and delivery.email.status != "sent":
            if delivery.email.attempts < 8:
                deliver_email(delivery.email)
        elif not delivery.email_id:
            delivery.email = queue_email(user.email, subject[:180], text + "\n\n— L'équipe iSwing.live\n", kind="message", ref=str(campaign.id))
        email_failed = bool(delivery.email_id and delivery.email.status != "sent")
    delivery.status = "failed" if email_failed else "sent"
    if email_failed and delivery.email_id:
        delivery.detail = (delivery.email.last_error or "mail_failed")[:200]
    elif delivery.email_id and delivery.email.status == "sent":
        delivery.detail = "accepted_by_mailer"
    elif delivery.notice_id:
        delivery.detail = "notice_created"
    delivery.save()
    return delivery


def send_campaign(campaign):
    if campaign.status in ("sent", "canceled", "paused"):
        return campaign
    from .integrations import campaign_room

    room = campaign_room()
    if room <= 0:
        campaign.status = "scheduled"
        campaign.scheduled_at = timezone.now() + timedelta(minutes=15)
        campaign.save(update_fields=["status", "scheduled_at"])
        return campaign
    sent_now = 0
    for delivery in campaign.deliveries.select_related("user", "user__profile", "email"):
        if sent_now >= room and delivery.status == "pending":
            break
        before = delivery.status
        deliver_campaign_row(campaign, delivery)
        if before != "sent" and delivery.status == "sent":
            sent_now += 1
    statuses = set(campaign.deliveries.values_list("status", flat=True))
    if "pending" in statuses:
        campaign.status = "scheduled"
        campaign.scheduled_at = timezone.now() + timedelta(minutes=15)
    elif not statuses or statuses <= {"sent", "skipped"}:
        campaign.status = "sent"
    elif "sent" in statuses:
        campaign.status = "partial"
    else:
        campaign.status = "failed"
    campaign.sent_at = timezone.now()
    campaign.save(update_fields=["status", "sent_at", "scheduled_at"])
    return campaign


def process_outbox(limit=20):
    from .models import Campaign

    now = timezone.now()
    due_ids = list(
        Campaign.objects.filter(status="scheduled", scheduled_at__lte=now).order_by("id").values_list("id", flat=True)[:limit]
    )
    for pk in due_ids:
        if Campaign.objects.filter(pk=pk, status="scheduled").update(status="sending"):
            send_campaign(Campaign.objects.get(pk=pk))
    flush_emails(limit=limit)
    retry = Campaign.objects.filter(
        status__in=("partial", "failed", "sent"),
        deliveries__status="failed",
    ).distinct().order_by("id")[:limit]
    for campaign in retry:
        for delivery in campaign.deliveries.filter(status="failed").select_related("user", "user__profile", "email")[:limit]:
            email = delivery.email
            if email is not None and email.next_retry_at and email.next_retry_at > now and email.attempts:
                continue
            deliver_campaign_row(campaign, delivery)
        statuses = set(campaign.deliveries.values_list("status", flat=True))
        if statuses <= {"sent", "skipped"}:
            campaign.status = "sent"
        elif "sent" in statuses:
            campaign.status = "partial"
        campaign.save(update_fields=["status"])


def billing_state(sub):
    now = timezone.now()
    if sub is None:
        return "none", "Aucun"
    if sub.status == "past_due":
        return "past_due", "Paiement en échec"
    if sub.cancel_at_period_end and sub.current_period_end and sub.current_period_end > now:
        return "ending", "Annulation programmée"
    if sub.status == "expired" or (sub.status == "canceled" and (not sub.current_period_end or sub.current_period_end <= now)):
        return "expired", "Expiré"
    if sub.status == "active":
        return "active", "Actif"
    if sub.status == "trial":
        return "trial", "Essai"
    return sub.status or "none", "Aucun"


def period_from_stamp(stamp):
    try:
        return datetime.fromtimestamp(int(stamp), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def inactive_members(days=365):
    cutoff = timezone.now() - timedelta(days=days)
    return User.objects.filter(is_staff=False, is_superuser=False, is_demo=False).filter(
        Q(last_login__isnull=True) | Q(last_login__lt=cutoff)
    ).filter(
        Q(profile__last_active__isnull=True) | Q(profile__last_active__lt=cutoff)
    ).filter(date_joined__lt=cutoff).distinct()


def flush_campaigns():
    process_outbox()


def convert_pending_videos(limit=2):
    from .media_pipeline import cleanup_abandoned, parallel_conversions, process_photo

    cleanup_abandoned()
    limit = max(1, min(limit, parallel_conversions()))
    ids = list(
        Photo.objects.filter(media_type="video", processing_status__in=("pending", "checking", "uploading"))
        .order_by("id")
        .values_list("id", flat=True)[:limit]
    )
    done = 0
    for pk in ids:
        process_photo(pk)
        if Photo.objects.filter(pk=pk, processing_status="ready").exists():
            done += 1
    return done
