"""Réglages d'intégration. Les secrets chiffrés ne sont pas renvoyés au navigateur."""

import base64
import hashlib
import json
import re
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.utils import timezone

from .models import Integration, PushDevice

SECRET_MARK = "••••"

PUSH_KINDS = ("message", "match", "access_request", "access_ok", "access_no", "team", "reminder")
PUSH_BODY = {
    "message": "Nouveau message",
    "match": "Nouveau match",
    "access_request": "Nouvelle demande",
    "access_ok": "Réponse à une demande",
    "access_no": "Réponse à une demande",
    "team": "Message de l'équipe",
    "reminder": "Rappel",
    "test": "Notification de test",
}


def data_key_is_separate():
    return bool(os_environ("ISWING_DATA_KEY"))


def os_environ(name):
    import os

    return os.environ.get(name, "").strip()


def _fernet():
    from cryptography.fernet import Fernet

    raw = os_environ("ISWING_DATA_KEY") or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    return Fernet(key)


def encrypt_dict(payload):
    token = _fernet().encrypt(json.dumps(payload or {}).encode())
    return token.decode("ascii")


def decrypt_dict(blob):
    if not blob:
        return {}
    try:
        raw = _fernet().decrypt(blob.encode("ascii"))
        data = json.loads(raw.decode())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def get_integration(code):
    row, _ = Integration.objects.get_or_create(code=code)
    return row


def public_config(row):
    data = row.public_data if isinstance(row.public_data, dict) else {}
    return dict(data)


def secrets(row):
    return decrypt_dict(row.secret_data)


def merge_secrets(old, posted):
    merged = dict(old)
    for key, value in (posted or {}).items():
        if value:
            merged[key] = value
    return merged


def save_integration(code, public, secret_updates, enabled, mode, actor=None):
    row = get_integration(code)
    row.public_data = public or {}
    row.secret_data = encrypt_dict(merge_secrets(secrets(row), secret_updates))
    row.enabled = bool(enabled)
    row.mode = mode if mode in ("off", "test", "production") else "off"
    row.status = "unconfigured"
    if row.enabled and row.mode == "test":
        row.status = "test"
    elif row.enabled and row.mode == "production":
        row.status = "active"
    elif secret_updates or secrets(row):
        row.status = "unconfigured" if not row.enabled else row.status
    row.save()
    if actor is not None:
        from .models import AuditLog

        AuditLog.objects.create(actor=actor, action="integration_save", target=code, detail=row.status)
    return row


def mark_test(row, ok, message):
    row.last_test_at = timezone.now()
    row.last_test_ok = bool(ok)
    row.last_test_message = (message or "")[:300]
    if not ok:
        row.status = "error"
    elif row.enabled and row.mode == "production":
        row.status = "active"
    elif row.enabled:
        row.status = "test"
    row.save(update_fields=["last_test_at", "last_test_ok", "last_test_message", "status"])


def status_label(row):
    return {"unconfigured": "Non configuré", "test": "Test", "active": "Actif", "error": "Erreur"}.get(row.status, "Non configuré")


def has_secret(row, key):
    return bool(secrets(row).get(key))


def stripe_values():
    row = Integration.objects.filter(code="stripe").first()
    stored = secrets(row) if row else {}
    public = public_config(row) if row else {}
    mode = (row.mode if row and row.enabled else "") or ""
    if mode == "production":
        secret = stored.get("secret_live") or settings.STRIPE_SECRET_KEY
        webhook = stored.get("webhook_live") or settings.STRIPE_WEBHOOK_SECRET
        price = public.get("price_live") or settings.STRIPE_PRICE_ID
        publishable = public.get("publishable_live") or ""
    elif mode == "test":
        secret = stored.get("secret_test") or settings.STRIPE_SECRET_KEY
        webhook = stored.get("webhook_test") or settings.STRIPE_WEBHOOK_SECRET
        price = public.get("price_test") or settings.STRIPE_PRICE_ID
        publishable = public.get("publishable_test") or ""
    else:
        secret = settings.STRIPE_SECRET_KEY
        webhook = settings.STRIPE_WEBHOOK_SECRET
        price = settings.STRIPE_PRICE_ID
        publishable = ""
    return {"secret": secret, "webhook": webhook, "price": price, "publishable": publishable, "mode": mode}


def stripe_ready():
    values = stripe_values()
    return bool(values["secret"] and values["price"] and values["webhook"])


def test_stripe():
    values = stripe_values()
    secret = values["secret"]
    if not secret:
        return False, "Aucune clé secrète enregistrée."
    if values["mode"] == "production" and secret.startswith("sk_test"):
        return False, "La clé fournie est une clé de test, pas une clé de production."
    if values["mode"] == "test" and secret.startswith("sk_live"):
        return False, "La clé fournie est une clé de production. Le test n'a pas été lancé."
    try:
        import stripe

        stripe.api_key = secret
        stripe.Balance.retrieve()
    except Exception:
        return False, "Le prestataire a refusé la connexion. Aucun paiement n'a été créé."
    kind = "test" if secret.startswith("sk_test") else "production"
    return True, f"Connexion acceptée ({kind}). Aucun paiement réel n'a été créé."


def smtp_config(code="smtp"):
    row = Integration.objects.filter(code=code, enabled=True).first()
    if row is None:
        return None
    secret = secrets(row)
    public = public_config(row)
    host = public.get("host") or ""
    if not host:
        return None
    return {
        "host": host,
        "port": int(public.get("port") or 587),
        "username": public.get("username") or "",
        "password": secret.get("password") or "",
        "use_tls": public.get("tls") == "starttls",
        "use_ssl": public.get("tls") == "ssl",
        "from_email": public.get("from_email") or settings.DEFAULT_FROM_EMAIL,
        "reply_to": public.get("reply_to") or "",
        "report_to": public.get("report_to") or settings.REPORT_INBOX,
    }


def mail_connection(code="smtp"):
    cfg = smtp_config(code)
    if cfg is None:
        return None
    from django.core.mail import get_connection

    try:
        timeout = int(os_environ("SMTP_TIMEOUT") or 20)
    except ValueError:
        timeout = 20
    timeout = min(max(timeout, 5), 60)
    return get_connection(
        backend="django.core.mail.backends.smtp.EmailBackend",
        host=cfg["host"],
        port=cfg["port"],
        username=cfg["username"],
        password=cfg["password"],
        use_tls=cfg["use_tls"],
        use_ssl=cfg["use_ssl"],
        timeout=timeout,
    )


def test_smtp(code, recipient):
    if not recipient or "@" not in recipient:
        return False, "Indiquez une adresse de test."
    cfg = smtp_config(code)
    if cfg is None:
        return False, "Renseignez l'hôte SMTP et enregistrez avant le test."
    from django.core.mail import EmailMultiAlternatives

    try:
        message = EmailMultiAlternatives(
            "iSwing.live — essai de courriel",
            "Ceci est un essai. L'acceptation par le serveur ne prouve pas que le message est arrivé dans la boîte.",
            cfg["from_email"],
            [recipient],
            reply_to=[cfg["reply_to"]] if cfg["reply_to"] else None,
            connection=mail_connection(code),
        )
        message.attach_alternative("<p>Ceci est un essai iSwing.live.</p>", "text/html")
        message.send(fail_silently=False)
    except Exception as exc:
        text = str(exc)
        if cfg["password"] and cfg["password"] in text:
            text = "échec d'authentification"
        return False, f"Envoi refusé : {text[:180]}"
    return True, "Le serveur SMTP a accepté l'essai. Cela ne prouve pas la délivrance dans la boîte du destinataire."


def dns_hints(domain):
    domain = (domain or "").split("@")[-1].strip().lower()
    if not domain or "." not in domain:
        return ["Indiquez un domaine d'expéditeur pour afficher les noms DNS à vérifier."]
    lines = [
        f"SPF : un enregistrement TXT sur {domain} doit autoriser le serveur qui envoie le courriel.",
        f"DKIM : un enregistrement TXT sur un sélecteur choisi, par exemple selector._domainkey.{domain}.",
        f"DMARC : un enregistrement TXT sur _dmarc.{domain}.",
        "iSwing n'a pas créé ces enregistrements. Leur présence doit être vérifiée chez le registrar.",
    ]
    try:
        import socket

        socket.getaddrinfo(domain, 25)
        lines.append(f"Le nom {domain} se résout. Cela ne confirme ni SPF, ni DKIM, ni DMARC.")
    except Exception:
        lines.append("La résolution DNS n'a pas pu être faite depuis ce serveur.")
    return lines


TRANSACTIONAL = {
    "verify": {
        "fr": ("Confirmez votre adresse", "Bienvenue sur iSwing !\n\nMerci d'avoir créé votre compte. Confirmez votre adresse courriel pour l'activer :\n{link}\n\nSi vous n'avez pas créé ce compte, ignorez ce courriel.\nContact : {contact}\nConditions : {terms}\nConfidentialité : {privacy}\n"),
        "en": ("Confirm your address", "Welcome to iSwing!\n\nThanks for creating your account. Confirm your email address to activate it:\n{link}\n\nIf you did not create this account, ignore this email.\nContact: {contact}\nTerms: {terms}\nPrivacy: {privacy}\n"),
        "es": ("Confirme su dirección", "¡Bienvenido a iSwing!\n\nGracias por crear su cuenta. Confirme su dirección de correo para activarla:\n{link}\n\nSi usted no ha creado esta cuenta, ignore este correo.\nContacto: {contact}\nCondiciones: {terms}\nPrivacidad: {privacy}\n"),
    },
    "reset": {
        "fr": ("Nouveau mot de passe", "Bonjour,\n\nChoisissez un nouveau mot de passe :\n{link}\n"),
        "en": ("New password", "Hello,\n\nChoose a new password:\n{link}\n"),
        "es": ("Nueva contraseña", "Hola,\n\nElija una nueva contraseña:\n{link}\n"),
    },
    "invite": {
        "fr": ("Activez votre compte", "Bonjour,\n\nChoisissez votre mot de passe et acceptez vous-même les conditions :\n{link}\n"),
        "en": ("Activate your account", "Hello,\n\nChoose your password and accept the terms yourself:\n{link}\n"),
        "es": ("Active su cuenta", "Hola,\n\nElija su contraseña y acepte usted mismo las condiciones:\n{link}\n"),
    },
    "report": {
        "fr": ("Nouveau signalement", "Un signalement a été enregistré.\n{link}\n"),
        "en": ("New report", "A report was recorded.\n{link}\n"),
        "es": ("Nueva denuncia", "Se ha registrado una denuncia.\n{link}\n"),
    },
    "reminder": {
        "fr": ("Rappel", "Bonjour,\n\nRappel concernant votre compte iSwing.live :\n{link}\n"),
        "en": ("Reminder", "Hello,\n\nA reminder about your iSwing.live account:\n{link}\n"),
        "es": ("Recordatorio", "Hola,\n\nUn recordatorio sobre su cuenta iSwing.live:\n{link}\n"),
    },
}


def render_transactional(code, lang, **context):
    lang = lang if lang in ("fr", "en", "es") else "fr"
    link = context.get("link") or ""
    if code == "verify":
        return _render_verify(lang, link)
    branded = _BRANDED.get(code)
    if branded:
        copy = branded.get(lang) or branded["fr"]
        return _render_branded(
            lang,
            title=copy["title"],
            lead=copy["lead"],
            button_label=copy["button"],
            button_url=link,
            raw_intro=_VERIFY_COPY[lang]["raw"],
            footer_note=copy["footer"],
            subject=copy["subject"],
        )
    table = TRANSACTIONAL.get(code) or TRANSACTIONAL["verify"]
    subject, body = table.get(lang) or table["fr"]
    text = body.format(**context)
    html = "<p>" + "<br>".join(escape(line) for line in text.splitlines()) + "</p>"
    return "iSwing.live — " + subject, text, html


_VERIFY_COPY = {
    "fr": {
        "welcome": "Bienvenue sur iSwing !",
        "lead": "Merci d'avoir créé votre compte. Confirmez votre adresse courriel pour l'activer.",
        "button": "Confirmer mon adresse",
        "raw": "Si le bouton ne s'ouvre pas, copiez ce lien dans votre navigateur :",
        "ignore": "Si vous n'avez pas créé ce compte, ignorez ce courriel.",
        "contact": "Contact",
        "terms": "Conditions",
        "privacy": "Confidentialité",
    },
    "en": {
        "welcome": "Welcome to iSwing!",
        "lead": "Thanks for creating your account. Confirm your email address to activate it.",
        "button": "Confirm my address",
        "raw": "If the button does not open, copy this link into your browser:",
        "ignore": "If you did not create this account, ignore this email.",
        "contact": "Contact",
        "terms": "Terms",
        "privacy": "Privacy",
    },
    "es": {
        "welcome": "¡Bienvenido a iSwing!",
        "lead": "Gracias por crear su cuenta. Confirme su dirección de correo para activarla.",
        "button": "Confirmar mi dirección",
        "raw": "Si el botón no se abre, copie este enlace en su navegador:",
        "ignore": "Si usted no ha creado esta cuenta, ignore este correo.",
        "contact": "Contacto",
        "terms": "Condiciones",
        "privacy": "Privacidad",
    },
}


def _render_branded(lang, *, title, lead, button_label, button_url, raw_intro, footer_note, subject=None):
    chrome = _VERIFY_COPY.get(lang) or _VERIFY_COPY["fr"]
    base = settings.ISWING_PUBLIC_BASE_URL.rstrip("/")
    logo = base + "/brand/icons/logo.png"
    terms = base + "/legal/conditions/"
    privacy = base + "/legal/confidentialite/"
    contact = settings.REPORT_INBOX
    text = (
        f"{title}\n\n{lead}\n\n{button_url}\n\n{footer_note}\n"
        f"{chrome['contact']} : {contact}\n{chrome['terms']} : {terms}\n{chrome['privacy']} : {privacy}\n"
    )
    safe_link = escape(button_url)
    safe_logo = escape(logo)
    html = f"""<!DOCTYPE html>
<html lang="{lang}">
<body style="margin:0;padding:0;background:#f4f0f8;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f0f8;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:16px;">
<tr><td align="center" style="padding:28px 24px 8px;"><img src="{safe_logo}" width="72" height="72" alt="iSwing" style="display:block;border:0;"></td></tr>
<tr><td style="padding:8px 32px 0;font-family:Georgia,serif;font-size:26px;line-height:1.3;color:#2a1038;text-align:center;">{escape(title)}</td></tr>
<tr><td style="padding:16px 32px 0;font-family:Arial,sans-serif;font-size:16px;line-height:1.5;color:#3d3348;text-align:center;">{escape(lead)}</td></tr>
<tr><td align="center" style="padding:28px 32px 8px;"><a href="{safe_link}" style="display:inline-block;background:#5b2c83;color:#ffffff;text-decoration:none;font-family:Arial,sans-serif;font-size:16px;font-weight:bold;padding:14px 28px;border-radius:999px;">{escape(button_label)}</a></td></tr>
<tr><td style="padding:8px 32px 24px;font-family:Arial,sans-serif;font-size:14px;line-height:1.5;color:#5c5366;text-align:center;">{escape(raw_intro)}<br><a href="{safe_link}" style="color:#5b2c83;word-break:break-all;">{safe_link}</a></td></tr>
<tr><td style="padding:16px 32px 28px;border-top:1px solid #efeaf3;font-family:Arial,sans-serif;font-size:12px;line-height:1.6;color:#6b6474;text-align:center;">{escape(chrome["contact"])} : {escape(contact)}<br><a href="{escape(terms)}" style="color:#5b2c83;">{escape(chrome["terms"])}</a> · <a href="{escape(privacy)}" style="color:#5b2c83;">{escape(chrome["privacy"])}</a><br>{escape(footer_note)}</td></tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    return "iSwing.live — " + (subject or title), text, html


def _render_verify(lang, link):
    copy = _VERIFY_COPY.get(lang) or _VERIFY_COPY["fr"]
    subject_label, body = TRANSACTIONAL["verify"][lang]
    _subject, _text, html = _render_branded(
        lang,
        title=copy["welcome"],
        lead=copy["lead"],
        button_label=copy["button"],
        button_url=link,
        raw_intro=copy["raw"],
        footer_note=copy["ignore"],
        subject=subject_label,
    )
    base = settings.ISWING_PUBLIC_BASE_URL.rstrip("/")
    text = body.format(
        link=link,
        contact=settings.REPORT_INBOX,
        terms=base + "/legal/conditions/",
        privacy=base + "/legal/confidentialite/",
    )
    return "iSwing.live — " + subject_label, text, html


_BRANDED = {
    "reset": {
        "fr": {
            "subject": "Nouveau mot de passe",
            "title": "Nouveau mot de passe",
            "lead": "Vous avez demandé à choisir un nouveau mot de passe. Le lien reste valable 24 heures.",
            "button": "Choisir un nouveau mot de passe",
            "footer": "Si vous n'avez pas fait cette demande, ignorez ce courriel.",
        },
        "en": {
            "subject": "New password",
            "title": "New password",
            "lead": "You asked to choose a new password. The link stays valid for 24 hours.",
            "button": "Choose a new password",
            "footer": "If you did not ask for this, ignore this email.",
        },
        "es": {
            "subject": "Nueva contraseña",
            "title": "Nueva contraseña",
            "lead": "Ha pedido elegir una nueva contraseña. El enlace sigue siendo válido durante 24 horas.",
            "button": "Elegir una nueva contraseña",
            "footer": "Si usted no ha hecho esta solicitud, ignore este correo.",
        },
    },
    "invite": {
        "fr": {
            "subject": "Activez votre compte",
            "title": "Activez votre compte",
            "lead": "L'équipe iSwing a préparé un compte à votre nom. Ce message n'accepte aucune condition à votre place. Choisissez votre mot de passe et cochez vous-même les consentements. Le lien expire dans 7 jours.",
            "button": "Activer mon compte",
            "footer": "Si vous n'attendiez pas ce message, ignorez ce courriel.",
        },
        "en": {
            "subject": "Activate your account",
            "title": "Activate your account",
            "lead": "The iSwing team prepared an account in your name. This message does not accept any terms for you. Choose your password and tick the consents yourself. The link expires in 7 days.",
            "button": "Activate my account",
            "footer": "If you were not expecting this message, ignore this email.",
        },
        "es": {
            "subject": "Active su cuenta",
            "title": "Active su cuenta",
            "lead": "El equipo de iSwing ha preparado una cuenta a su nombre. Este mensaje no acepta ninguna condición por usted. Elija su contraseña y marque usted mismo los consentimientos. El enlace caduca en 7 días.",
            "button": "Activar mi cuenta",
            "footer": "Si no esperaba este mensaje, ignore este correo.",
        },
    },
    "partner": {
        "fr": {
            "subject": "Confirmation d'un profil de couple",
            "title": "Confirmation d'un profil de couple",
            "lead": "Un profil de couple iSwing cite votre pseudonyme. Ouvrez le lien, choisissez votre mot de passe et acceptez vous-même.",
            "button": "Confirmer ma participation",
            "footer": "Si ce profil ne vous concerne pas, ignorez ce courriel.",
        },
        "en": {
            "subject": "Couple profile confirmation",
            "title": "Couple profile confirmation",
            "lead": "A couple profile on iSwing uses your pseudonym. Open the link, choose your password and accept for yourself.",
            "button": "Confirm my participation",
            "footer": "If this profile is not about you, ignore this email.",
        },
        "es": {
            "subject": "Confirmación de un perfil de pareja",
            "title": "Confirmación de un perfil de pareja",
            "lead": "Un perfil de pareja en iSwing cita su seudónimo. Abra el enlace, elija su contraseña y acepte usted mismo.",
            "button": "Confirmar mi participación",
            "footer": "Si este perfil no le concierne, ignore este correo.",
        },
    },
    "billing": {
        "fr": {
            "subject": "Lien de paiement",
            "title": "Votre facture",
            "lead": "Un lien de paiement est prêt pour votre facture iSwing. Le montant est celui convenu avec l'équipe.",
            "button": "Payer la facture",
            "footer": "Si vous n'attendiez pas ce lien, ignorez ce courriel.",
        },
        "en": {
            "subject": "Payment link",
            "title": "Your invoice",
            "lead": "A payment link is ready for your iSwing invoice. The amount is the one agreed with the team.",
            "button": "Pay the invoice",
            "footer": "If you were not expecting this link, ignore this email.",
        },
        "es": {
            "subject": "Enlace de pago",
            "title": "Su factura",
            "lead": "Un enlace de pago está listo para su factura de iSwing. El importe es el acordado con el equipo.",
            "button": "Pagar la factura",
            "footer": "Si no esperaba este enlace, ignore este correo.",
        },
    },
}


def escape(value):
    from django.utils.html import escape as html_escape

    return html_escape(value or "")


def unsub_token(user):
    return signing.dumps({"u": user.id}, salt="iswing-promo")


def unsub_link(user):
    token = quote(unsub_token(user), safe="")
    return settings.ISWING_PUBLIC_BASE_URL.rstrip("/") + f"/desabonnement/{token}/"


def read_unsub(token):
    data = signing.loads(token, salt="iswing-promo", max_age=60 * 60 * 24 * 365)
    return int(data["u"])


def ensure_vapid():
    row = get_integration("push")
    current = secrets(row)
    if current.get("private_pem") and current.get("public"):
        return row
    from py_vapid import Vapid
    from cryptography.hazmat.primitives import serialization

    vapid = Vapid()
    vapid.generate_keys()
    raw = vapid.public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    public = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    private = vapid.private_pem().decode("ascii")
    row.secret_data = encrypt_dict(merge_secrets(current, {"private_pem": private, "public": public}))
    row.save()
    return row


def vapid_public():
    row = Integration.objects.filter(code="push").first()
    if row is None:
        return ""
    return secrets(row).get("public") or ""


def push_payload(kind, url):
    safe = url if isinstance(url, str) and url.startswith("/") and not url.startswith("//") else "/notifications/"
    return {"title": "iSwing", "body": PUSH_BODY.get(kind, "Nouvelle activité"), "url": safe}


def send_push(user, kind, url):
    if kind not in PUSH_KINDS and kind != "test":
        return []
    row = Integration.objects.filter(code="push", enabled=True).first()
    if row is None:
        return []
    private = secrets(row).get("private_pem")
    if not private:
        return []
    payload = json.dumps(push_payload(kind, url))
    results = []
    from pywebpush import WebPushException, webpush

    for device in PushDevice.objects.filter(user=user, disabled=False):
        allowed = device.kinds or {}
        if allowed and allowed.get(kind) is False:
            continue
        try:
            webpush(
                subscription_info={"endpoint": device.endpoint, "keys": {"p256dh": device.p256dh, "auth": device.auth}},
                data=payload,
                vapid_private_key=private,
                vapid_claims={"sub": "mailto:Info@iswing.live"},
            )
            device.fail_count = 0
            device.last_error = ""
            device.save(update_fields=["fail_count", "last_error", "updated_at"])
            results.append((device.id, True, "accepted"))
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", 0)
            device.fail_count += 1
            device.last_error = f"http {status}"[:200]
            if status in (404, 410) or device.fail_count >= 5:
                device.disabled = True
            device.save(update_fields=["fail_count", "last_error", "disabled", "updated_at"])
            results.append((device.id, False, device.last_error))
        except Exception:
            device.fail_count += 1
            device.last_error = "envoi impossible"
            device.save(update_fields=["fail_count", "last_error", "updated_at"])
            results.append((device.id, False, "envoi impossible"))
    return results


def remember_device(user, endpoint, p256dh, auth, agent, kinds=None):
    digest = hashlib.sha256(endpoint.encode()).hexdigest()
    device, _ = PushDevice.objects.update_or_create(
        endpoint_hash=digest,
        defaults={
            "user": user,
            "endpoint": endpoint,
            "p256dh": p256dh[:200],
            "auth": auth[:120],
            "user_agent": (agent or "")[:200],
            "kinds": kinds or {key: True for key in PUSH_KINDS},
            "disabled": False,
        },
    )
    return device


def disable_endpoint(user, endpoint):
    if not endpoint:
        return
    digest = hashlib.sha256(endpoint.encode()).hexdigest()
    PushDevice.objects.filter(user=user, endpoint_hash=digest).update(disabled=True)


def seo_config():
    row = Integration.objects.filter(code="seo").first()
    data = public_config(row) if row else {}
    data["enabled"] = bool(row and row.enabled and data.get("index") == "1")
    return data


def stats_config():
    row = Integration.objects.filter(code="stats", enabled=True).first()
    data = public_config(row) if row else {}
    data["ga4"] = _clean_id(data.get("ga4"), r"^G-[A-Z0-9]+$")
    data["gtm"] = _clean_id(data.get("gtm"), r"^GTM-[A-Z0-9]+$")
    return data


def pixel_config():
    row = Integration.objects.filter(code="pixels", enabled=True).first()
    if row is None:
        return {"meta": ""}
    data = public_config(row)
    return {"meta": _clean_id(data.get("meta"), r"^\d{5,20}$")}


def _clean_id(value, pattern):
    value = (value or "").strip()
    return value if re.match(pattern, value) else ""


def tracking_allowed(path):
    path = path or "/"
    private = ("/profil/", "/photos/", "/messages", "/gestion", "/admin", "/moi", "/decouvrir", "/matchs", "/parametres", "/abonnement", "/notifications")
    if any(path.startswith(prefix) for prefix in private):
        return False
    return path == "/" or path.startswith("/legal/") or path.startswith("/comptes/") or path.startswith("/installer")


def campaign_room():
    from datetime import timedelta

    from .models import Notice, OutboundEmail

    now = timezone.now()
    per_hour = limit_from_settings("campaign_per_hour", 100)
    per_day = limit_from_settings("campaign_per_day", 1000)
    hour = OutboundEmail.objects.filter(kind="message", status="sent", sent_at__gte=now - timedelta(hours=1)).count()
    hour += Notice.objects.filter(kind="team", created_at__gte=now - timedelta(hours=1)).count()
    day = OutboundEmail.objects.filter(kind="message", status="sent", sent_at__gte=now - timedelta(days=1)).count()
    day += Notice.objects.filter(kind="team", created_at__gte=now - timedelta(days=1)).count()
    return max(0, min(per_hour - hour, per_day - day))


def limit_from_settings(key, default):
    from .models import SiteSetting

    row = SiteSetting.objects.filter(key=key).first()
    if row is None or str(row.value).strip() == "":
        return default
    try:
        return int(row.value)
    except ValueError:
        return default
