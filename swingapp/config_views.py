"""Onglets de configuration. Les secrets vides conservent la valeur déjà chiffrée."""

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from .gestion import _forbid, staff_only
from .integrations import (
    data_key_is_separate,
    dns_hints,
    ensure_vapid,
    get_integration,
    has_secret,
    mark_test,
    public_config,
    save_integration,
    secrets,
    send_push,
    status_label,
    stripe_values,
    test_smtp,
    test_stripe,
    TRANSACTIONAL,
)
from .branding import THEMES, category_rows, remove_custom, save_png, theme_choice
from .media_pipeline import storage_snapshot
from .models import AuditLog, PushDevice, SiteSetting

TABS = (
    ("apparence", "Apparence"),
    ("medias", "Médias et stockage"),
    ("paiements", "Paiements"),
    ("courriels", "Courriels transactionnels"),
    ("campagnes", "Campagnes"),
    ("push", "Notifications push"),
    ("seo", "SEO et indexation"),
    ("stats", "Statistiques"),
    ("pixels", "Pixels publicitaires"),
    ("sante", "Sécurité et intégrations"),
)


def _flag(data, name):
    return "1" if data.get(name) == "1" else ""


@staff_only
def configuration(request):
    tab = request.GET.get("onglet") or request.POST.get("onglet") or "medias"
    if tab not in dict(TABS):
        tab = "medias"
    if request.method == "POST":
        denied = _forbid(request, "can_configure")
        if denied:
            return denied
        action = request.POST.get("action") or "save"
        handler = {
            "medias": _save_media,
            "apparence": _save_look,
            "paiements": _save_stripe,
            "courriels": _save_smtp,
            "campagnes": _save_campaign,
            "push": _save_push,
            "seo": _save_seo,
            "stats": _save_stats,
            "pixels": _save_pixels,
        }.get(tab)
        if handler:
            handler(request, action)
        return redirect(f"/gestion/configuration/?onglet={tab}")
    rows = {code: get_integration(code) for code in ("stripe", "smtp", "campaign_smtp", "push", "seo", "stats", "pixels", "storage")}
    return render(request, "gestion/config.html", {
        "section": "config",
        "tab": tab,
        "tabs": TABS,
        "rows": rows,
        "labels": {row.code: status_label(row) for row in rows.values()},
        "public": {code: public_config(row) for code, row in rows.items()},
        "secret_flags": {code: {key: has_secret(row, key) for key in ("secret_test", "secret_live", "webhook_test", "webhook_live", "password", "private_pem")} for code, row in rows.items()},
        "storage": storage_snapshot(),
        "push_devices": PushDevice.objects.select_related("user").order_by("-id")[:30],
        "dns": dns_hints((public_config(rows["smtp"]).get("from_email") or "")),
        "separate_key": data_key_is_separate(),
        "webhook_url": request.build_absolute_uri("/paiements/webhook/"),
        "stripe_mode": stripe_values().get("mode") or "off",
        "letters": TRANSACTIONAL,
        "health_rows": [(code, status_label(row), row) for code, row in rows.items()],
        "campaign_hour": SiteSetting.get("campaign_per_hour", "100"),
        "campaign_day": SiteSetting.get("campaign_per_day", "1000"),
        "themes": THEMES,
        "theme": theme_choice(),
        "categories": category_rows(),
        "logo_custom": (Path(settings.BASE_DIR) / "data" / "brand" / "icons" / "logo.png").is_file(),
    })


def _save_look(request, action):
    from .choices import CATEGORY_CODES

    if action == "reset":
        target = (request.POST.get("reset") or "").strip()
        if target == "logo":
            remove_custom("icons/logo.png")
            remove_custom("icons/icon-192.png")
            remove_custom("icons/icon-512.png")
        elif target == "all":
            root = Path(settings.BASE_DIR) / "data" / "brand"
            if root.is_dir():
                for path in root.rglob("*"):
                    if path.is_file():
                        path.unlink()
        elif target in ("toutes", *CATEGORY_CODES):
            remove_custom(f"categories/{target}.png")
        else:
            messages.error(request, "Rien à remettre d'origine.")
            return
        AuditLog.objects.create(actor=request.user, action="brand_reset", detail=target[:80])
        messages.success(request, "Image d'origine rétablie.")
        return
    theme = request.POST.get("theme") or "violet"
    if theme not in {code for code, _label, _help in THEMES}:
        messages.error(request, "Thème inconnu.")
        return
    _set("theme", theme)
    try:
        if request.FILES.get("logo"):
            save_png("icons/logo.png", request.FILES["logo"], 512)
            request.FILES["logo"].seek(0)
            save_png("icons/icon-192.png", request.FILES["logo"], 192)
            request.FILES["logo"].seek(0)
            save_png("icons/icon-512.png", request.FILES["logo"], 512)
        for code in ("toutes", *CATEGORY_CODES):
            upload = request.FILES.get(f"cat_{code}")
            if upload:
                save_png(f"categories/{code}.png", upload, 512)
    except ValueError as exc:
        messages.error(request, str(exc))
        return
    AuditLog.objects.create(actor=request.user, action="brand_update", detail=theme)
    messages.success(request, "Apparence enregistrée. Rechargez le site si une image ne change pas tout de suite.")


def _set(key, value):
    SiteSetting.objects.update_or_create(key=key, defaults={"value": str(value)[:200]})


def _save_media(request, action):
    if action == "disable":
        return
    fields = {
        "video_max_bytes": request.POST.get("video_max_bytes") or "2000000000",
        "video_max_seconds": request.POST.get("video_max_seconds") or "600",
        "photo_max_bytes": request.POST.get("photo_max_bytes") or "50000000",
        "photo_max_edge": request.POST.get("photo_max_edge") or "2560",
        "member_media_bytes": request.POST.get("member_media_bytes") or "0",
        "video_parallel": request.POST.get("video_parallel") or "1",
        "storage_alert_percent": request.POST.get("storage_alert_percent") or "85",
    }
    for key, value in fields.items():
        if not str(value).strip().lstrip("-").isdigit():
            messages.error(request, "Une limite n'est pas un nombre. Les anciennes valeurs sont conservées.")
            return
        _set(key, int(value))
    AuditLog.objects.create(actor=request.user, action="media_limits", detail="updated")
    messages.success(request, "Limites de médias enregistrées. Les quotas de likes et de messages n'ont pas été modifiés.")


def _save_stripe(request, action):
    row = get_integration("stripe")
    if action == "disable":
        row.enabled = False
        row.mode = "off"
        row.status = "unconfigured"
        row.save(update_fields=["enabled", "mode", "status"])
        messages.success(request, "Stripe est désactivé. Les clés restent chiffrées sur le serveur.")
        return
    mode = request.POST.get("mode") if request.POST.get("mode") in ("test", "production") else "test"
    public = {
        "publishable_test": request.POST.get("publishable_test", "").strip(),
        "publishable_live": request.POST.get("publishable_live", "").strip(),
        "price_test": request.POST.get("price_test", "").strip(),
        "price_live": request.POST.get("price_live", "").strip(),
        "currency": (request.POST.get("currency") or "usd").strip()[:8],
    }
    old_public = public_config(row)
    for key, value in public.items():
        if not value:
            public[key] = old_public.get(key, "")
    secret_updates = {
        "secret_test": request.POST.get("secret_test", "").strip(),
        "secret_live": request.POST.get("secret_live", "").strip(),
        "webhook_test": request.POST.get("webhook_test", "").strip(),
        "webhook_live": request.POST.get("webhook_live", "").strip(),
    }
    save_integration("stripe", public, secret_updates, True, mode, request.user)
    if action == "test":
        ok, text = test_stripe()
        mark_test(get_integration("stripe"), ok, text)
        (messages.success if ok else messages.error)(request, text)
    else:
        messages.success(request, "Réglages Stripe enregistrés. L'admissibilité du site auprès de Stripe n'est pas garantie.")


def _save_smtp(request, action):
    _mail_form(request, action, "smtp")


def _save_campaign(request, action):
    for key in ("campaign_per_hour", "campaign_per_day"):
        raw = request.POST.get(key, "")
        if raw.strip().isdigit():
            _set(key, int(raw))
    _mail_form(request, action, "campaign_smtp")


def _mail_form(request, action, code):
    row = get_integration(code)
    if action == "disable":
        row.enabled = False
        row.status = "unconfigured"
        row.mode = "off"
        row.save(update_fields=["enabled", "status", "mode"])
        messages.success(request, "Transport désactivé. Le mot de passe déjà enregistré est conservé.")
        return
    old = public_config(row)
    public = {
        "host": request.POST.get("host", "").strip() or old.get("host", ""),
        "port": request.POST.get("port", "").strip() or old.get("port", "587"),
        "username": request.POST.get("username", "").strip() or old.get("username", ""),
        "tls": request.POST.get("tls") if request.POST.get("tls") in ("starttls", "ssl", "none") else old.get("tls", "starttls"),
        "from_email": request.POST.get("from_email", "").strip() or old.get("from_email", ""),
        "reply_to": request.POST.get("reply_to", "").strip() or old.get("reply_to", ""),
        "report_to": request.POST.get("report_to", "").strip() or old.get("report_to", "Info@iswing.live"),
        "test_to": request.POST.get("test_to", "").strip() or old.get("test_to", ""),
    }
    enabled = bool(public.get("host"))
    save_integration(code, public, {"password": request.POST.get("password", "").strip()}, enabled, "test" if enabled else "off", request.user)
    if action == "test":
        ok, text = test_smtp(code, public.get("test_to"))
        mark_test(get_integration(code), ok, text)
        (messages.success if ok else messages.error)(request, text)
    else:
        messages.success(request, "Réglages enregistrés. Un champ secret vide n'efface pas le mot de passe déjà stocké.")


def _save_push(request, action):
    row = ensure_vapid()
    if action == "disable":
        row.enabled = False
        row.status = "unconfigured"
        row.save(update_fields=["enabled", "status"])
        messages.success(request, "Push désactivé. Les notifications internes restent en place.")
        return
    row.enabled = True
    row.mode = "test"
    row.status = "test"
    row.save(update_fields=["enabled", "mode", "status"])
    if action == "test":
        device = PushDevice.objects.filter(pk=request.POST.get("device") or 0, disabled=False).first()
        if device is None:
            mark_test(row, False, "Aucun appareil enregistré pour cet essai.")
            messages.error(request, "Aucun appareil enregistré. Le test n'a pas été envoyé.")
            return
        results = send_push(device.user, "test", "/notifications/")
        ok = bool(results and results[0][1])
        text = "Le service push a accepté l'envoi." if ok else "Le service push a refusé l'envoi. La réception sur le téléphone n'est pas garantie."
        if not ok and results:
            text = "Échec : " + results[0][2]
        mark_test(get_integration("push"), ok, text)
        (messages.success if ok else messages.error)(request, text + " Cela ne garantit pas l'affichage sur l'écran.")
    else:
        messages.success(request, "Notifications push activées avec les clés de ce serveur.")


def _save_seo(request, action):
    row = get_integration("seo")
    if action == "disable":
        row.enabled = False
        row.status = "unconfigured"
        row.save(update_fields=["enabled", "status"])
        messages.success(request, "Indexation désactivée.")
        return
    old = public_config(row)
    public = {
        "index": "1" if request.POST.get("index") == "1" else "",
        "title": request.POST.get("title", "").strip()[:180] or old.get("title", "iSwing"),
        "description": request.POST.get("description", "").strip()[:300] or old.get("description", ""),
        "canonical": request.POST.get("canonical", "").strip()[:200] or old.get("canonical", ""),
        "search_console": request.POST.get("search_console", "").strip()[:80] or old.get("search_console", ""),
    }
    if public["search_console"] and not re_ok(public["search_console"]):
        messages.error(request, "Le code Search Console contient des caractères refusés.")
        return
    save_integration("seo", public, {}, public["index"] == "1", "production" if public["index"] == "1" else "off", request.user)
    messages.success(request, "Réglages SEO enregistrés. Les profils, messages et médias restent exclus.")


def _save_stats(request, action):
    _id_form(request, action, "stats", ("ga4", "gtm"))


def _save_pixels(request, action):
    _id_form(request, action, "pixels", ("meta",))


def _id_form(request, action, code, keys):
    row = get_integration(code)
    if action == "disable":
        row.enabled = False
        row.status = "unconfigured"
        row.save(update_fields=["enabled", "status"])
        messages.success(request, "Désactivé.")
        return
    old = public_config(row)
    public = {key: request.POST.get(key, "").strip() or old.get(key, "") for key in keys}
    enabled = request.POST.get("enabled") == "1"
    save_integration(code, public, {}, enabled, "production" if enabled else "off", request.user)
    messages.success(request, "Enregistré. Aucun script libre n'est accepté. Les pages privées ne reçoivent pas ces identifiants.")


def re_ok(value):
    import re

    return bool(re.match(r"^[A-Za-z0-9_\-]{8,80}$", value))
