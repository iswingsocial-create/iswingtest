from django.conf import settings
from django.contrib import admin
from django.http import FileResponse, Http404
from django.urls import include, path
from django.views.generic import RedirectView
import mimetypes


def brand_file(request, asset):
    root = (settings.BASE_DIR / "static").resolve()
    full = (root / asset).resolve()
    if root != full and root not in full.parents:
        raise Http404()
    if not full.is_file():
        raise Http404(asset)
    content_type = mimetypes.guess_type(full.name)[0] or "application/octet-stream"
    response = FileResponse(full.open("rb"), content_type=content_type)
    if full.suffix in {".css", ".js"}:
        response["Cache-Control"] = "no-cache"
    else:
        response["Cache-Control"] = "public, max-age=300"
    return response


urlpatterns = [
    path("brand/<path:asset>", brand_file, name="brand"),
    path("admin/", admin.site.urls),
    path("", include("swingapp.urls")),
    path("favicon.ico", RedirectView.as_view(url="/brand/icons/icon-192.png", permanent=False)),
]

handler404 = "swingapp.views.page_not_found"
handler403 = "swingapp.views.permission_denied"
handler500 = "swingapp.views.server_error"