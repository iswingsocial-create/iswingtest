from .branding import brand_stamp, theme_choice
from .choices import REPORT_REASONS
from .i18n import STRINGS, t
from .models import SiteSetting
from .integrations import pixel_config, seo_config, stats_config, tracking_allowed


def ui(request):
    lang = getattr(request, "lang", "fr")
    unread = 0
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        from .models import Notice

        profile = getattr(user, "profile", None)
        if profile is not None:
            unread = Notice.objects.filter(profile=profile, read_at__isnull=True).count()
    session_label = ""
    if user is not None and user.is_authenticated:
        from .models import Partner
        from .services import author_label_for

        seat = Partner.objects.filter(user_id=user.id).select_related("profile").first()
        if seat is not None and seat.profile_id:
            session_label = author_label_for(seat.profile, user)
    path = getattr(request, "path", "/") or "/"
    query = request.GET.copy()
    lang_links = []
    for code, label in (("fr", "FR"), ("en", "EN"), ("es", "ES")):
        query["lang"] = code
        lang_links.append((code, label, path + "?" + query.urlencode()))
    public = tracking_allowed(path)
    seo = seo_config() if public else {}
    indexable = public and seo.get("enabled")
    return {
        "lang": lang,
        "T": {key: t(lang, key) for key in STRINGS["fr"]},
        "langs": [("fr", "FR"), ("en", "EN"), ("es", "ES")],
        "lang_links": lang_links,
        "unread_notices": unread,
        "report_reasons": [(code, t(lang, key)) for code, key in REPORT_REASONS],
        "robots_meta": "index,follow" if indexable else "noindex,nofollow",
        "seo": seo if indexable else {},
        "stats": stats_config() if indexable else {},
        "pixel": pixel_config() if indexable else {"meta": ""},
        "canonical": ((seo.get("canonical") or "").rstrip("/") + path) if indexable and seo.get("canonical") else "",
        "theme": theme_choice(),
        "brand_stamp": brand_stamp(),
        "businesses_on": SiteSetting.get("businesses_enabled", "0") == "1",
        "session_label": session_label,
        "is_seller": bool(user and user.is_authenticated and not user.is_superuser and user.groups.filter(name="Vendeurs").exists()),
    }