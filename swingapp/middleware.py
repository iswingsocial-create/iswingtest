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

            ensure_profile(user)
            user.staff_2fa_ok = bool(request.session.get("staff_2fa"))
            if _needs_invite(request, user):
                from django.shortcuts import redirect

                return redirect("/invitation/en-attente/")
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


def _needs_invite(request, user):
    if user.is_staff or user.is_superuser:
        return False
    if user.terms_accepted_at and user.adult_declared:
        return False
    path = request.path or "/"
    allowed = ("/invitation", "/legal/", "/comptes/deconnexion", "/brand/", "/sw.js", "/manifest", "/sante", "/static/")
    return not any(path.startswith(prefix) for prefix in allowed)
