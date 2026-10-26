"""Serves the React app's entry page for every /app/ route.

Hashed JS and CSS files under /app/assets/ are served by WhiteNoise. This view only
returns index.html, so client-side routes survive a refresh. If the frontend has not
been built, it answers with a plain 503 explaining what to run.
"""

from django.conf import settings
from django.http import HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

INDEX = settings.BASE_DIR / "frontend" / "dist" / "app" / "index.html"


@never_cache
@require_GET
def spa_index(request, path=""):
    try:
        html = INDEX.read_text(encoding="utf-8")
    except OSError:
        return HttpResponse(
            "The ZuuVi app has not been built yet. Run `npm ci && npm run build` in the frontend "
            "folder, then reload.",
            status=503,
            content_type="text/plain; charset=utf-8",
        )
    return HttpResponse(html, content_type="text/html; charset=utf-8")
