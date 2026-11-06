from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

urlpatterns = [
    path("booth/", admin.site.urls),
    path("api/", include("core.urls")),
]

if settings.SERVE_MEDIA:
    # Uploaded posters and avatars. Fine for a small community site; a busy one should let Apache serve media/.
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]
