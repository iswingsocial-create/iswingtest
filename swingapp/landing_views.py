import importlib.util

from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render

_MODULE = None


def load_build():
    global _MODULE
    if _MODULE is None:
        path = settings.BASE_DIR / "landing" / "_build" / "build.py"
        spec = importlib.util.spec_from_file_location("iswing_landing_build", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _MODULE = module
    return _MODULE


def sitemap_groups():
    module = load_build()
    groups = [module.home_paths()]
    for city in module.CITIES:
        groups.append(dict(city["paths"]))
    return groups


def _context(lang, city_key=None):
    module = load_build()
    if lang not in ("fr", "en", "es"):
        raise Http404(lang)
    page = module.pack(lang)
    city = module.city_pack(lang, city_key) if city_key else None
    if city_key and city is None:
        raise Http404(city_key)
    site = settings.ISWING_PUBLIC_BASE_URL.rstrip("/")
    asset_root = site + settings.STATIC_URL.rstrip("/") + "/landing"
    paths = city["paths"] if city else module.home_paths()
    labels = {"fr": "FR", "en": "EN", "es": "ES"}
    if city:
        lang_links = [
            {"name": f"landing_{code}_{city['key']}", "code": code, "label": labels[code]}
            for code in ("fr", "en", "es")
        ]
    else:
        lang_links = [
            {"name": "home", "code": "fr", "label": "FR"},
            {"name": "landing_en", "code": "en", "label": "EN"},
            {"name": "landing_es", "code": "es", "label": "ES"},
        ]
    cards = module.city_cards(lang)
    for card in cards:
        card["alt"] = page["city_alt"].format(name=card["name"])
    if city:
        city["alt"] = page["city_alt"].format(name=city["name"])
    from .integrations import pixel_config, stats_config

    return {
        "L": page,
        "city": city,
        "cards": cards,
        "canonical": site + (city["path"] if city else page["path"]),
        "alternates": module.alternates(paths, site),
        "json_ld": module.json_ld(lang, city_key, site, site, asset_root),
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


def render_city(request, lang, key):
    request.session["lang"] = lang
    return render(request, "landing_home.html", _context(lang, key))


def city_paths():
    from django.urls import path

    module = load_build()
    patterns = []
    for city in module.CITIES:
        for lang, route in city["paths"].items():
            patterns.append(path(
                route.strip("/") + "/",
                render_city,
                {"lang": lang, "key": city["key"]},
                name=f"landing_{lang}_{city['key']}",
            ))
    return patterns
