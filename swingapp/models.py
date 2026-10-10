import base64
import hashlib
import hmac
import secrets
import struct
import time
from datetime import date

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("email required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("birth_date", date(1990, 1, 1))
        extra.setdefault("terms_accepted_at", timezone.now())
        extra.setdefault("email_verified_at", timezone.now())
        extra.setdefault("adult_declared", True)
        return self.create_user(email, password, **extra)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    birth_date = models.DateField(null=True, blank=True)
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    adult_declared = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    AGE_STATUS = [
        ("unconfirmed", "Non confirmé par la personne"),
        ("declared", "Déclaration seulement"),
        ("pending_review", "Preuve en attente"),
        ("verified", "Majorité vérifiée"),
        ("rejected", "Preuve refusée"),
    ]
    age_proof_status = models.CharField(max_length=20, choices=AGE_STATUS, default="declared")
    can_moderate = models.BooleanField(default=False)
    can_manage_members = models.BooleanField(default=False)
    can_manage_billing = models.BooleanField(default=False)
    can_manage_comms = models.BooleanField(default=False)
    can_configure = models.BooleanField(default=False)
    failed_logins = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    admin_totp_secret = models.CharField(max_length=64, blank=True)
    is_demo = models.BooleanField(default=False)
    intimate_consent = models.BooleanField(default=False)
    prefs_consent = models.BooleanField(default=False)
    reco_consent = models.BooleanField(default=False)
    promo_consent = models.BooleanField(default=False)
    objects = UserManager()
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    def age_years(self):
        if not self.birth_date:
            return None
        today = timezone.now().date()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


class EmailToken(models.Model):
    PURPOSE = [("verify", "verify"), ("reset", "reset"), ("partner", "partner"), ("invite", "invite")]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="email_tokens")
    purpose = models.CharField(max_length=16, choices=PURPOSE)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Profile(models.Model):
    KIND = [("single", "Célibataire"), ("couple", "Couple"), ("business", "Entreprise")]
    VISIBILITY = [
        ("public", "Visible"),
        ("discrete", "Discret (matchs seulement)"),
        ("paused", "En pause"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    kind = models.CharField(max_length=16, choices=KIND, default="single")
    display_name = models.CharField(max_length=40)
    holder_name = models.CharField(max_length=40, blank=True, default="")
    gender = models.CharField(max_length=32, blank=True)
    orientation = models.CharField(max_length=32, blank=True)
    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=2, default="FR")
    languages = models.CharField(max_length=300, blank=True)
    language_other = models.CharField(max_length=40, blank=True)
    seeking = models.CharField(max_length=120, blank=True)
    seeking_serious = models.BooleanField(default=False)
    bio = models.TextField(blank=True)
    tastes = models.TextField(blank=True)
    desires = models.TextField(blank=True)
    activities = models.CharField(max_length=200, blank=True)
    availability = models.CharField(max_length=120, blank=True)
    limits = models.TextField(blank=True)
    hide_orientation = models.BooleanField(default=False)
    hide_desires = models.BooleanField(default=False)
    show_distance = models.BooleanField(default=True)
    show_online = models.BooleanField(default=True)
    visibility = models.CharField(max_length=16, choices=VISIBILITY, default="public")
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    location_updated_at = models.DateTimeField(null=True, blank=True)
    validated_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    suspended = models.BooleanField(default=False)
    last_active = models.DateTimeField(null=True, blank=True)
    read_receipts = models.BooleanField(default=False)
    is_demo = models.BooleanField(default=False)
    lifetime_member = models.BooleanField(default=False)
    certified = models.BooleanField(default=False)
    origins = models.CharField(max_length=160, blank=True)
    city_ref = models.CharField(max_length=180, blank=True)
    travel_city = models.CharField(max_length=80, blank=True, default="")
    travel_country = models.CharField(max_length=2, blank=True, default="")
    travel_lat = models.FloatField(null=True, blank=True)
    travel_lng = models.FloatField(null=True, blank=True)
    travel_start = models.DateField(null=True, blank=True)
    travel_end = models.DateField(null=True, blank=True)
    external_key = models.CharField(max_length=80, unique=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.display_name

    @property
    def public_age(self):
        return self.user.age_years()


class Partner(models.Model):
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="partner")
    display_name = models.CharField(max_length=40)
    birth_date = models.DateField()
    gender = models.CharField(max_length=32, blank=True)
    orientation = models.CharField(max_length=32, blank=True, default="")
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_email = models.EmailField(blank=True)
    age_proof_status = models.CharField(max_length=20, default="declared")
    user = models.OneToOneField(
        "User", null=True, blank=True, on_delete=models.SET_NULL, related_name="partner_seat"
    )

    def age_years(self):
        today = timezone.now().date()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years


class Photo(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="photos/%Y/%m/")
    is_primary = models.BooleanField(default=False)
    is_private = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)
    STATUS = [("pending", "En attente"), ("approved", "Approuvée"), ("rejected", "Refusée"), ("removed", "Retirée")]
    moderation_status = models.CharField(max_length=16, choices=STATUS, default="pending")
    moderation_note = models.CharField(max_length=240, blank=True, default="")
    processing_status = models.CharField(max_length=16, default="ready")
    processing_error = models.CharField(max_length=200, blank=True, default="")
    media_type = models.CharField(max_length=8, default="photo")
    video = models.FileField(upload_to="videos/%Y/%m/", blank=True)
    thumb = models.ImageField(upload_to="thumbs/%Y/%m/", blank=True)
    byte_size = models.BigIntegerField(default=0)
    estimated_bytes = models.BigIntegerField(default=0)
    width = models.PositiveIntegerField(default=0)
    height = models.PositiveIntegerField(default=0)
    duration_s = models.FloatField(null=True, blank=True)
    source_path = models.CharField(max_length=500, blank=True, default="")
    role = models.CharField(max_length=16, default="gallery")
    title = models.CharField(max_length=80, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]


class CertificationRequest(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="certifications")
    photo = models.ForeignKey(Photo, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, default="pending")
    note = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]


class PhotoGrant(models.Model):
    photo = models.ForeignKey(Photo, on_delete=models.CASCADE, related_name="grants")
    grantee = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="photo_grants")
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["photo", "grantee"], name="uniq_photo_grant"),
        ]


class PrivateAccess(models.Model):
    owner = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="private_grants")
    grantee = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="private_access")
    status = models.CharField(max_length=16, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "grantee"], name="uniq_private_access")]


class Notice(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="notices")
    kind = models.CharField(max_length=40)
    body = models.TextField(blank=True)
    code = models.CharField(max_length=40, blank=True, default="")
    params = models.TextField(blank=True, default="")
    url = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]


class Like(models.Model):
    actor = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="likes_sent")
    target = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="likes_received")
    created_at = models.DateTimeField(auto_now_add=True)
    client_key = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["actor", "target"], name="uniq_like"),
            models.UniqueConstraint(fields=["actor", "client_key"], condition=~models.Q(client_key=""), name="uniq_like_client_key"),
        ]


class Pass(models.Model):
    actor = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="passes")
    target = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="passed_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["actor", "target"], name="uniq_pass")]


class Match(models.Model):
    profile_a = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="matches_a")
    profile_b = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="matches_b")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile_a", "profile_b"], name="uniq_match")]

    def other(self, profile):
        return self.profile_b if self.profile_a_id == profile.id else self.profile_a

    def involves(self, profile):
        return profile.id in (self.profile_a_id, self.profile_b_id)


class Favorite(models.Model):
    owner = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="favorites")
    target = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="favorited_by")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "target"], name="uniq_fav")]


class Block(models.Model):
    blocker = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="blocks_made")
    blocked = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="blocks_received")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["blocker", "blocked"], name="uniq_block")]


class Message(models.Model):
    match = models.ForeignKey(Match, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="messages_sent")
    body = models.TextField(blank=True)
    photo = models.ForeignKey(Photo, null=True, blank=True, on_delete=models.SET_NULL)
    client_key = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    is_demo = models.BooleanField(default=False)
    author_label = models.CharField(max_length=90, blank=True, default="")

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["match", "sender", "client_key"],
                condition=~models.Q(client_key=""),
                name="uniq_msg_client_key",
            )
        ]

    def __str__(self):
        return (self.body or "")[:40] or f"Message {self.pk}"


class Report(models.Model):
    reporter = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="reports_made")
    target = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="reports_received")
    reason = models.CharField(max_length=240)
    reason_code = models.CharField(max_length=40, blank=True, default="")
    comment = models.TextField(blank=True, default="")
    related_ref = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=16, default="open")
    created_at = models.DateTimeField(auto_now_add=True)


class ReportNote(models.Model):
    report = models.ForeignKey(Report, on_delete=models.CASCADE, related_name="notes")
    author = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    body = models.TextField(blank=True)
    action = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]


class OutboundEmail(models.Model):
    to_email = models.EmailField()
    subject = models.CharField(max_length=180)
    body = models.TextField()
    html_body = models.TextField(blank=True, default="")
    kind = models.CharField(max_length=20, default="message")
    ref = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=16, default="pending")
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=300, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)


class MessageTemplate(models.Model):
    code = models.SlugField(unique=True)
    name = models.CharField(max_length=80)
    subject = models.CharField(max_length=180)
    body = models.TextField()
    channel = models.CharField(max_length=16, default="both")
    is_promo = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class Campaign(models.Model):
    sender = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="campaigns")
    template = models.ForeignKey(MessageTemplate, null=True, blank=True, on_delete=models.SET_NULL)
    subject = models.CharField(max_length=180)
    body = models.TextField()
    channel = models.CharField(max_length=16, default="notice")
    is_promo = models.BooleanField(default=False)
    criteria = models.CharField(max_length=300, blank=True)
    client_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    scheduled_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)


class CampaignDelivery(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="deliveries")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    status = models.CharField(max_length=16, default="pending")
    detail = models.CharField(max_length=200, blank=True)
    notice = models.ForeignKey(Notice, null=True, blank=True, on_delete=models.SET_NULL)
    email = models.ForeignKey(OutboundEmail, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "user"], name="uniq_campaign_user")]


class Subscription(models.Model):
    STATUS = [
        ("none", "Aucun"),
        ("trial", "Essai"),
        ("active", "Actif"),
        ("past_due", "Paiement en échec"),
        ("canceled", "Annulé, accès jusqu'à échéance"),
        ("expired", "Expiré"),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="subscription")
    status = models.CharField(max_length=16, choices=STATUS, default="none")
    provider = models.CharField(max_length=32, blank=True)
    external_id = models.CharField(max_length=80, blank=True)
    customer_id = models.CharField(max_length=80, blank=True, default="")
    source = models.CharField(max_length=16, blank=True, default="")
    current_period_end = models.DateTimeField(null=True, blank=True)
    cancel_at_period_end = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class DailyUsage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="daily_usage")
    day = models.DateField()
    likes = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "day"], name="uniq_usage_day")]


class MatchUsage(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    match = models.ForeignKey(Match, on_delete=models.CASCADE)
    messages_sent = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "match"], name="uniq_match_usage")]


class PaymentEvent(models.Model):
    provider = models.CharField(max_length=32)
    event_id = models.CharField(max_length=80)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=32)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider", "event_id"], name="uniq_pay_event")]


class AuditLog(models.Model):
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=120, blank=True)
    detail = models.CharField(max_length=300, blank=True)
    reason = models.CharField(max_length=240, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)


class LegalPage(models.Model):
    slug = models.SlugField(unique=True)
    title_fr = models.CharField(max_length=180)
    title_en = models.CharField(max_length=180)
    title_es = models.CharField(max_length=180)
    body_fr = models.TextField()
    body_en = models.TextField()
    body_es = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)

    def title(self, lang):
        return getattr(self, f"title_{lang}", self.title_fr) or self.title_fr

    def body(self, lang):
        return getattr(self, f"body_{lang}", self.body_fr) or self.body_fr

    def __str__(self):
        return self.title_fr


class SiteSetting(models.Model):
    key = models.CharField(max_length=40, unique=True)
    value = models.CharField(max_length=200)

    @classmethod
    def get(cls, key, default):
        row = cls.objects.filter(key=key).first()
        return row.value if row else default


class Integration(models.Model):
    code = models.SlugField(unique=True)
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=16, default="off")
    status = models.CharField(max_length=16, default="unconfigured")
    public_data = models.JSONField(default=dict, blank=True)
    secret_data = models.TextField(blank=True)
    last_test_at = models.DateTimeField(null=True, blank=True)
    last_test_ok = models.BooleanField(null=True)
    last_test_message = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return self.code


class MediaUpload(models.Model):
    token = models.CharField(max_length=32, unique=True)
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="uploads")
    kind = models.CharField(max_length=8, default="video")
    filename = models.CharField(max_length=120, blank=True)
    total_size = models.BigIntegerField(default=0)
    received = models.BigIntegerField(default=0)
    next_index = models.PositiveIntegerField(default=0)
    is_private = models.BooleanField(default=False)
    status = models.CharField(max_length=16, default="uploading")
    temp_path = models.CharField(max_length=500, blank=True)
    photo = models.ForeignKey(Photo, null=True, blank=True, on_delete=models.SET_NULL)
    error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class PushDevice(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="push_devices")
    endpoint_hash = models.CharField(max_length=64, unique=True)
    endpoint = models.TextField()
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=120)
    user_agent = models.CharField(max_length=200, blank=True)
    kinds = models.JSONField(default=dict, blank=True)
    disabled = models.BooleanField(default=False)
    fail_count = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class InactivityRun(models.Model):
    mode = models.CharField(max_length=16)
    matched = models.PositiveIntegerField(default=0)
    deleted = models.PositiveIntegerField(default=0)
    detail = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]


class TestBatch(models.Model):
    """Lot de profils fictifs. Ne référence jamais un compte réel."""

    STATUS = [
        ("queued", "En file"),
        ("generating", "Génération"),
        ("images_blocked", "Images indisponibles"),
        ("packaged", "Paquet prêt"),
        ("imported", "Importé"),
        ("failed", "Échec"),
        ("deleted", "Supprimé"),
    ]
    batch_id = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    seed = models.CharField(max_length=64)
    reference_date = models.DateField()
    status = models.CharField(max_length=24, choices=STATUS, default="queued")
    params = models.JSONField(default=dict, blank=True)
    report = models.JSONField(default=dict, blank=True)
    zip_path = models.CharField(max_length=300, blank=True)
    error = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.batch_id


class TestPersona(models.Model):
    """Métadonnées de génération, non exposées aux membres."""

    batch = models.ForeignKey(TestBatch, on_delete=models.CASCADE, related_name="personas")
    external_key = models.CharField(max_length=80, unique=True)
    profile = models.ForeignKey(Profile, null=True, blank=True, on_delete=models.SET_NULL, related_name="test_persona")
    visual = models.JSONField(default=dict, blank=True)
    sheet = models.JSONField(default=dict, blank=True)
    simulated = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return self.external_key



class BusinessAccount(models.Model):
    CATEGORIES = [
        ("club", "club"), ("sauna", "sauna"), ("party", "party"), ("travel", "travel"),
        ("cruise", "cruise"), ("shop", "shop"), ("photo", "photo"), ("organizer", "organizer"), ("other", "other"),
    ]
    PLAN = [("none", "none"), ("active", "active"), ("unpaid", "unpaid"), ("canceled", "canceled")]
    profile = models.OneToOneField(Profile, on_delete=models.CASCADE, related_name="business")
    category = models.CharField(max_length=16, choices=CATEGORIES, default="other")
    description = models.TextField(blank=True)
    address = models.CharField(max_length=160, blank=True)
    website = models.CharField(max_length=200, blank=True)
    ticket_url = models.CharField(max_length=200, blank=True)
    logo = models.ImageField(upload_to="business/logos/", blank=True)
    verified = models.BooleanField(default=False)
    plan_status = models.CharField(max_length=16, choices=PLAN, default="none")
    plan_until = models.DateField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    sold_by = models.ForeignKey("User", null=True, blank=True, on_delete=models.SET_NULL, related_name="sold_businesses")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.profile.display_name


class BusinessPhoto(models.Model):
    business = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="business/photos/")
    created_at = models.DateTimeField(auto_now_add=True)


class BusinessDocument(models.Model):
    STATUS = [("pending", "pending"), ("approved", "approved"), ("rejected", "rejected")]
    business = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name="documents")
    document = models.FileField(upload_to="business/docs/")
    status = models.CharField(max_length=16, choices=STATUS, default="pending")
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class BusinessInvoice(models.Model):
    KIND = [("plan", "plan"), ("push", "push")]
    STATUS = [("due", "due"), ("paid", "paid"), ("void", "void")]
    business = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name="invoices")
    kind = models.CharField(max_length=16, choices=KIND)
    amount = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=STATUS, default="due")
    note = models.CharField(max_length=180, blank=True)
    payment_url = models.CharField(max_length=300, blank=True, default="")
    payment_ref = models.CharField(max_length=80, blank=True, default="")
    sold_by = models.ForeignKey("User", null=True, blank=True, on_delete=models.SET_NULL, related_name="sold_invoices")
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Event(models.Model):
    business = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name="events")
    title = models.CharField(max_length=120)
    category = models.CharField(max_length=16, default="party")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    place = models.CharField(max_length=160, blank=True)
    city = models.CharField(max_length=80, blank=True)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    description = models.TextField(blank=True)
    practical = models.TextField(blank=True)
    price_note = models.CharField(max_length=240, blank=True)
    ticket_url = models.CharField(max_length=200, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    views = models.PositiveIntegerField(default=0)
    published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["starts_at", "id"]


class EventPhoto(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="business/events/")
    created_at = models.DateTimeField(auto_now_add=True)


class EventRsvp(models.Model):
    STATUS = [("interested", "interested"), ("going", "going"), ("waitlist", "waitlist")]
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="rsvps")
    user = models.ForeignKey("User", on_delete=models.CASCADE, related_name="event_rsvps")
    status = models.CharField(max_length=16, choices=STATUS, default="interested")
    anonymous = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "user"], name="uniq_event_rsvp")]


class BusinessPush(models.Model):
    business = models.ForeignKey(BusinessAccount, on_delete=models.CASCADE, related_name="pushes")
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.SET_NULL)
    city = models.CharField(max_length=80, blank=True)
    lat = models.FloatField()
    lng = models.FloatField()
    radius_km = models.PositiveIntegerField(default=30)
    category = models.CharField(max_length=32, blank=True)
    purpose = models.CharField(max_length=16, default="ad")
    promo_code = models.CharField(max_length=40, blank=True, default="")
    offer_details = models.CharField(max_length=400, blank=True, default="")
    offer_ends_at = models.DateField(null=True, blank=True)
    target_kinds = models.CharField(max_length=40, blank=True, default="")
    body = models.TextField()
    audience = models.PositiveIntegerField(default=0)
    amount = models.PositiveIntegerField(default=0)
    campaign = models.ForeignKey(Campaign, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=16, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)


class Prospect(models.Model):
    STATUS = [
        ("new", "new"), ("contacted", "contacted"), ("follow", "follow"),
        ("client", "client"), ("lost", "lost"),
    ]
    name = models.CharField(max_length=120)
    contact = models.CharField(max_length=80, blank=True, default="")
    email = models.EmailField(blank=True, default="")
    phone = models.CharField(max_length=40, blank=True, default="")
    category = models.CharField(max_length=16, blank=True, default="other")
    status = models.CharField(max_length=16, choices=STATUS, default="new")
    notes = models.TextField(blank=True, default="")
    next_follow = models.DateField(null=True, blank=True)
    seller = models.ForeignKey("User", null=True, blank=True, on_delete=models.SET_NULL, related_name="prospects")
    business = models.ForeignKey(BusinessAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="prospects")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["next_follow", "-id"]


class SellerPayout(models.Model):
    seller = models.ForeignKey("User", on_delete=models.CASCADE, related_name="payouts")
    period = models.CharField(max_length=7)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["seller", "period"], name="uniq_seller_period")]


def new_token():
    raw = secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def _totp_key(secret: str) -> bytes:
    raw = (secret or "").strip()
    if len(raw) == 40 and all(ch in "0123456789abcdef" for ch in raw.lower()):
        return raw.encode()
    padded = raw.upper().replace(" ", "")
    padded += "=" * ((8 - len(padded) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def totp_now(secret: str, step: int = 30, drift: int = 0) -> str:
    counter = int(time.time() // step) + drift
    msg = struct.pack(">Q", counter)
    digest = hmac.new(_totp_key(secret), msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{code % 1000000:06d}"


def totp_valid(secret: str, code: str) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not secret or len(code) != 6 or not code.isdigit():
        return False
    return any(code == totp_now(secret, drift=drift) for drift in (-1, 0, 1))


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
