"""File-flag maintenance page: 503 HTML without touching the database."""
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string

from common.maintenance import REASON_UPDATE, read_status

# Cheap exists() check each request so an updater / ops can flip the flag
# without restarting Gunicorn. Path is relative to BASE_DIR, not cwd.
MAINTENANCE_FLAG_PATH = Path(settings.BASE_DIR) / "run" / "MAINTENANCE"


class MaintenanceModeMiddleware:
    """If ``run/MAINTENANCE`` exists, return a 503 page and skip the rest of the stack.

    ``render_to_string`` with no request — no context processors, sessions, CSRF,
    or database. Inline CSS only; does not depend on ``frontend/dist``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not MAINTENANCE_FLAG_PATH.exists():
            return self.get_response(request)
        status = read_status(MAINTENANCE_FLAG_PATH)
        html = render_to_string("maintenance.html", {"status": status})
        response = HttpResponse(html, status=503)
        response["Cache-Control"] = "no-store"
        response["Retry-After"] = "5" if status and status.reason == REASON_UPDATE else "120"
        return response
