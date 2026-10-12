import importlib.util
import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render

_MODULE = None
_SVG = {
    "montreal": "city-montreal.svg",
    "quebec": "city-quebec.svg",
    "cancun": "city-cancun.svg",
    "mexico": "city-mexico.svg",
}
_MEDIA_TYPES = {
    ".webp": "image/webp",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def load_build():
    global _MODULE
    if _MODULE is None:
        path = settings.BASE_DIR / "landing" / "_build" / "build.py"
        spec = importlib.util.spec_from_file_location("iswing_landing_build", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def live_trial():
    from .services import setting_int

    return {
        "days": setting_int("trial_days", settings.TRIAL_DAYS, 1, 30),
        "likes": setting_int("trial_daily_likes", settings.TRIAL_DAILY_LIKES, 1, 100),
        "messages": setting_int("trial_messages_per_match", settings.TRIAL_MESSAGES_PER_MATCH, 0, 30),
    }


def _paths(city):
    return {
        "fr": f"/rencontre-echangiste-{city.slug}/",
        "en": f"/en/swinger-dating-{city.slug_en}/",
        "es": f"/es/citas-swingers-{city.slug_es}/",
    }


def _slug_for(city, lang):
    return {"fr": city.slug, "en": city.slug_en, "es": city.slug_es}[lang]


def _active_cities():
    from .models import LandingCity

    return list(LandingCity.objects.filter(is_active=True).order_by("position", "id"))


def sitemap_groups():
    module = load_build()
    groups = [module.home_paths()]
    rows = _active_cities()
    if rows:
        for city in rows:
            groups.append(_paths(city))
        return groups
    for city in module.CITIES:
        groups.append(dict(city["paths"]))
    return groups


def _public_media(rel):
    if not rel or not str(rel).startswith("landing/"):
        return ""
    path = Path(settings.MEDIA_ROOT) / rel
    if not path.is_file():
        return ""
    return "/landing-media/" + str(rel)[len("landing/"):]


def hero_url():
    from .models import SiteSetting

    return _public_media(SiteSetting.get("landing_hero_image", "") or "")


def _image_url(city):
    name = city.image.name if city.image else ""
    return _public_media(name)


def _field(city, prefix, lang, tokens):
    module = load_build()
    value = getattr(city, f"{prefix}_{lang}") or getattr(city, f"{prefix}_fr") or ""
    return module.apply_tokens(value, tokens)


def _city_public(city, lang, tokens):
    module = load_build()
    body = _field(city, "body", lang, tokens)
    paragraphs = [part.strip() for part in body.replace("\r\n", "\n").split("\n\n") if part.strip()]
    raw_faq = getattr(city, f"faq_{lang}") or []
    faqs = []
    for index, item in enumerate(raw_faq):
        if not isinstance(item, (list, tuple)) or len(item) < 2:
            continue
        faqs.append({
            "q": module.apply_tokens(item[0], tokens),
            "a": module.apply_tokens(item[1], tokens),
            "open": index == 0,
        })
    paths = _paths(city)
    name = _field(city, "name", lang, tokens) or city.name
    return {
        "key": city.slug,
        "name": name,
        "h1": _field(city, "h1", lang, tokens) or _field(city, "title", lang, tokens) or name,
        "title": _field(city, "title", lang, tokens) or name,
        "desc": _field(city, "desc", lang, tokens),
        "kw": _field(city, "kw", lang, tokens),
        "paragraphs": paragraphs,
        "faqs": faqs,
        "path": paths[lang],
        "paths": paths,
        "svg": _SVG.get(city.slug, ""),
        "image_url": _image_url(city),
        "slug": _slug_for(city, lang),
        "slugs": {"fr": city.slug, "en": city.slug_en, "es": city.slug_es},
        "url_name": f"landing_city_{lang}",
        "card": module.apply_tokens(getattr(city, f"tagline_{lang}") or "", tokens),
    }


def _lookup(lang, slug):
    from .models import LandingCity

    field = {"fr": "slug", "en": "slug_en", "es": "slug_es"}[lang]
    return LandingCity.objects.filter(**{field: slug, "is_active": True}).first()


def _context(lang, slug=None):
    module = load_build()
    if lang not in ("fr", "en", "es"):
        raise Http404(lang)
    trial = live_trial()
    tokens = module.trial_tokens(lang, trial["days"], trial["likes"], trial["messages"])
    page = module.pack(lang, trial)
    city = None
    if slug:
        row = _lookup(lang, slug)
        if row is None:
            raise Http404(slug)
        city = _city_public(row, lang, tokens)
        if not city["faqs"]:
            city["faqs"] = page["faq"]
        city["alt"] = page["city_alt"].replace("{name}", city["name"])
    labels = {"fr": "FR", "en": "EN", "es": "ES"}
    if city:
        lang_links = [
            {"name": f"landing_city_{code}", "args": [city["slugs"][code]], "code": code, "label": labels[code]}
            for code in ("fr", "en", "es")
        ]
        paths = city["paths"]
    else:
        lang_links = [
            {"name": "home", "args": [], "code": "fr", "label": "FR"},
            {"name": "landing_en", "args": [], "code": "en", "label": "EN"},
            {"name": "landing_es", "args": [], "code": "es", "label": "ES"},
        ]
        paths = module.home_paths()
    cards = []
    for row in _active_cities():
        public = _city_public(row, lang, tokens)
        cards.append({
            "name": public["name"],
            "card": public["card"],
            "svg": public["svg"],
            "image_url": public["image_url"],
            "slug": public["slug"],
            "url_name": public["url_name"],
            "alt": page["city_alt"].replace("{name}", public["name"]),
        })
    site = settings.ISWING_PUBLIC_BASE_URL.rstrip("/")
    asset_root = site + settings.STATIC_URL.rstrip("/") + "/landing"
    from .integrations import pixel_config, stats_config

    return {
        "L": page,
        "city": city,
        "cards": cards,
        "hero_url": hero_url(),
        "canonical": site + (city["path"] if city else page["path"]),
        "alternates": module.alternates(paths, site),
        "json_ld": module.json_ld(lang, None, site, site, asset_root, trial=trial, city=city),
        "og_image": asset_root + "/" + page["og_img"],
        "lang_links": lang_links,
        "home_url_name": {"fr": "home", "en": "landing_en", "es": "landing_es"}[lang],
        "leave_url": module.LEAVE_URL,
        "page_title": city["title"] if city else page["title"],
        "page_desc": city["desc"] if city else page["desc"],
        "page_kw": city["kw"] if city else page["kw"],
        "stats": stats_config(),
        "pixel": pixel_config(),
    }


def render_home(request, lang="fr"):
    if request.user.is_authenticated:
        return redirect("discover")
    request.session["lang"] = lang
    return render(request, "landing_home.html", _context(lang))


def render_city(request, slug, lang="fr"):
    if request.user.is_authenticated:
        return redirect("discover")
    request.session["lang"] = lang
    return render(request, "landing_home.html", _context(lang, slug))


def landing_media(request, name):
    root = (Path(settings.MEDIA_ROOT) / "landing").resolve()
    target = (root / name).resolve()
    if target != root and root not in target.parents:
        raise Http404(name)
    if not target.is_file():
        raise Http404(name)
    content_type = _MEDIA_TYPES.get(target.suffix.lower())
    if not content_type:
        guessed = mimetypes.guess_type(target.name)[0]
        if guessed not in _MEDIA_TYPES.values():
            raise Http404(name)
        content_type = guessed
    response = FileResponse(target.open("rb"), content_type=content_type)
    response["Cache-Control"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response
