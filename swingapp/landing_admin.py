"""Onglet Landing : image principale et villes. Les quotas restent dans Paramètres."""

from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify

from .gestion import _forbid, staff_only
from .landing_images import LandingImageError, prepare_landing_image
from .models import AuditLog, LandingCity, SiteSetting

HERO_HINT = "Dimensions optimales : 960 × 720 px (ratio 4:3), JPG ou WebP, max 500 Ko."
CITY_HINT = "Dimensions optimales : 800 × 480 px (ratio 5:3), JPG ou WebP, max 500 Ko."
HERO_KEY = "landing_hero_image"
LANGS = ("fr", "en", "es")


def _paragraphs(text):
    return [part.strip() for part in (text or "").replace("\r\n", "\n").split("\n\n") if part.strip()]


def _unique_slug(base, field, exclude_pk=None):
    stem = slugify(base)[:70] or "ville"
    candidate = stem
    number = 2
    while LandingCity.objects.exclude(pk=exclude_pk).filter(**{field: candidate}).exists():
        candidate = f"{stem}-{number}"[:80]
        number += 1
    return candidate


def _blank(city, key):
    if city is None:
        return ""
    value = getattr(city, key)
    return "" if value is None else value


def _form_state(request, city):
    data = {}
    keys = [
        "name", "slug", "slug_en", "slug_es", "position",
    ]
    for lang in LANGS:
        keys.extend([f"name_{lang}", f"tagline_{lang}", f"h1_{lang}", f"title_{lang}", f"desc_{lang}", f"body_{lang}"])
    if request.method == "POST" and request.POST.get("action") == "save":
        for key in keys:
            data[key] = request.POST.get(key, "")
        data["is_active"] = request.POST.get("is_active") == "1"
    else:
        for key in keys:
            data[key] = _blank(city, key)
        data["is_active"] = True if city is None else city.is_active
        if city is None:
            data["position"] = str((LandingCity.objects.order_by("-position").values_list("position", flat=True).first() or 0) + 1)
    return data


def _save_city(request, city):
    data = _form_state(request, city)
    name = (data["name"] or "").strip()
    if not name:
        return None, "Indiquez le nom de la ville."
    slug = _unique_slug(data["slug"] or name, "slug", city.pk if city else None) if not (data["slug"] or "").strip() else slugify(data["slug"])[:80]
    if not slug:
        return None, "Le slug est vide. Utilisez des lettres et des chiffres."
    slug_en = slugify(data["slug_en"])[:80] if (data["slug_en"] or "").strip() else slug
    slug_es = slugify(data["slug_es"])[:80] if (data["slug_es"] or "").strip() else slug
    if not slug_en or not slug_es:
        return None, "Les segments d'URL anglais et espagnol sont vides."
    taken = LandingCity.objects.exclude(pk=city.pk if city else None)
    if taken.filter(slug=slug).exists() or taken.filter(slug_en=slug_en).exists() or taken.filter(slug_es=slug_es).exists():
        return None, "Ce slug est déjà utilisé par une autre ville."
    for lang, label in (("fr", "français"), ("en", "anglais"), ("es", "espagnol")):
        if not (data[f"title_{lang}"] or "").strip() or not (data[f"desc_{lang}"] or "").strip():
            return None, f"Le titre SEO et la meta description sont obligatoires en {label}."
        if len(_paragraphs(data[f"body_{lang}"])) < 2:
            return None, f"Le texte {label} doit contenir au moins deux paragraphes, séparés par une ligne vide."
    try:
        position = int(str(data["position"]).strip() or "0")
    except ValueError:
        return None, "L'ordre doit être un nombre."
    if position < 0 or position > 9999:
        return None, "L'ordre doit rester entre 0 et 9999."
    image_bytes = None
    upload = request.FILES.get("image")
    if upload:
        try:
            image_bytes = prepare_landing_image(upload, 800, 480)
        except LandingImageError as exc:
            return None, str(exc)
    if city is None:
        city = LandingCity(name=name)
    city.name = name[:80]
    city.slug = slug
    city.slug_en = slug_en
    city.slug_es = slug_es
    city.position = position
    city.is_active = data["is_active"]
    for lang in LANGS:
        setattr(city, f"name_{lang}", (data[f"name_{lang}"] or name).strip()[:80])
        setattr(city, f"tagline_{lang}", (data[f"tagline_{lang}"] or "").strip()[:160])
        title = (data[f"title_{lang}"] or "").strip()[:180]
        h1 = (data[f"h1_{lang}"] or "").strip()[:180] or title
        setattr(city, f"h1_{lang}", h1)
        setattr(city, f"title_{lang}", title)
        setattr(city, f"desc_{lang}", (data[f"desc_{lang}"] or "").strip())
        setattr(city, f"body_{lang}", (data[f"body_{lang}"] or "").strip())
    if image_bytes is not None:
        if city.image:
            city.image.delete(save=False)
        city.image.save(f"{slug}.webp", ContentFile(image_bytes), save=False)
    city.save()
    return city, ""


def _price_label():
    from .landing_views import load_build

    module = load_build()
    return module.price_label("fr"), module.PRICE_AMOUNT, module.PRICE_CURRENCY


@staff_only
def landing_page(request):
    if request.method == "POST":
        denied = _forbid(request, "can_configure")
        if denied:
            return denied
        upload = request.FILES.get("image")
        if request.POST.get("action") != "hero" or upload is None:
            messages.error(request, "Choisissez une image principale.")
            return redirect("gestion_landing")
        try:
            data = prepare_landing_image(upload, 960, 720)
        except LandingImageError as exc:
            messages.error(request, str(exc))
            return redirect("gestion_landing")
        dest = Path(settings.MEDIA_ROOT) / "landing" / "hero.webp"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        SiteSetting.objects.update_or_create(key=HERO_KEY, defaults={"value": "landing/hero.webp"})
        AuditLog.objects.create(actor=request.user, action="landing_hero", detail="hero.webp")
        messages.success(request, "Image principale enregistrée.")
        return redirect("gestion_landing")
    from .services import setting_int

    price, amount, currency = _price_label()
    cities = []
    for city in LandingCity.objects.order_by("position", "id"):
        thumb = ""
        if city.image and city.image.name.startswith("landing/") and (Path(settings.MEDIA_ROOT) / city.image.name).is_file():
            thumb = "/landing-media/" + city.image.name[len("landing/"):]
        cities.append({"row": city, "thumb": thumb})
    return render(request, "gestion/landing.html", {
        "section": "landing",
        "hero_hint": HERO_HINT,
        "city_hint": CITY_HINT,
        "cities": cities,
        "hero_set": bool(SiteSetting.get(HERO_KEY, "")),
        "days": setting_int("trial_days", settings.TRIAL_DAYS, 1, 30),
        "likes": setting_int("trial_daily_likes", settings.TRIAL_DAILY_LIKES, 1, 100),
        "messages_cap": setting_int("trial_messages_per_match", settings.TRIAL_MESSAGES_PER_MATCH, 0, 30),
        "price": price,
        "price_amount": amount,
        "price_currency": currency,
    })


@staff_only
def city_edit(request, pk=None):
    city = get_object_or_404(LandingCity, pk=pk) if pk else None
    if request.method == "POST":
        denied = _forbid(request, "can_configure")
        if denied:
            return denied
        action = request.POST.get("action", "save")
        if city and action == "deactivate":
            city.is_active = False
            city.save(update_fields=["is_active"])
            AuditLog.objects.create(actor=request.user, action="landing_city", target=city.slug, detail="inactive")
            messages.success(request, f"{city.name} est masquée. Elle reste en base.")
            return redirect("gestion_landing")
        if city and action == "activate":
            city.is_active = True
            city.save(update_fields=["is_active"])
            AuditLog.objects.create(actor=request.user, action="landing_city", target=city.slug, detail="active")
            messages.success(request, f"{city.name} est de nouveau visible.")
            return redirect("gestion_landing")
        saved, error = _save_city(request, city)
        if error:
            messages.error(request, error)
        else:
            AuditLog.objects.create(actor=request.user, action="landing_city", target=saved.slug, detail="save")
            messages.success(request, "Ville enregistrée.")
            return redirect("gestion_landing")
    return render(request, "gestion/landing_city.html", {
        "section": "landing",
        "city": city,
        "form": _form_state(request, city),
        "city_hint": CITY_HINT,
    })
