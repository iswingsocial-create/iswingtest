from django.utils import timezone


class LanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = request.GET.get("lang")
        if lang in ("fr", "en", "es"):
            request.session["lang"] = lang
        request.lang = request.session.get("lang", "fr")
        return self.get_response(request)


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user and user.is_authenticated:
            from .services import ensure_profile

            profile = ensure_profile(user)
            user.staff_2fa_ok = bool(request.session.get("staff_2fa"))
            if _needs_invite(request, user):
                from django.shortcuts import redirect

                return redirect("/invitation/en-attente/")
            locked = _profile_gate(request, user, profile)
            if locked:
                from django.shortcuts import redirect

                return redirect(locked)
            if _admin_needs_2fa(request, user):
                from django.shortcuts import redirect

                return redirect("/gestion/2fa/")
        response = self.get_response(request)
        return response


def _admin_needs_2fa(request, user):
    if not (user.is_staff or user.is_superuser):
        return False
    if request.session.get("staff_2fa"):
        return False
    path = request.path or "/"
    if path.startswith("/gestion/2fa"):
        return False
    return path.startswith("/gestion") or path.startswith("/admin")


def _profile_gate(request, user, profile):
    if user.is_staff or user.is_superuser or user.is_demo or profile.is_demo or profile.kind == "business":
        return None
    path = request.path or "/"
    allowed = (
        "/moi/",
        "/legal/",
        "/comptes/deconnexion",
        "/comptes/connexion",
        "/comptes/inscription",
        "/comptes/mot-de-passe",
        "/comptes/verifier/",
        "/invitation/",
        "/brand/",
        "/static/",
        "/sw.js",
        "/manifest",
        "/sante",
        "/villes/",
        "/photos/",
    )
    if any(path.startswith(prefix) for prefix in allowed):
        return None
    from .services import profile_fields_complete

    if not profile_fields_complete(profile):
        return "/moi/"
    from .views import _verification_required

    if _verification_required(user):
        return "/comptes/verifier/"
    return None


def _needs_invite(request, user):
    if user.is_staff or user.is_superuser:
        return False
    if user.terms_accepted_at and user.adult_declared:
        return False
    path = request.path or "/"
    allowed = ("/invitation", "/legal/", "/comptes/deconnexion", "/brand/", "/sw.js", "/manifest", "/sante", "/static/")
    return not any(path.startswith(prefix) for prefix in allowed)
