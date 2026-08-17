from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings

# The API serves JSON and file downloads, never markup that should run script or be framed.
# `default-src 'none'` is therefore the honest policy: nothing here needs to load anything.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# The app itself, when this process also serves the built frontend. Everything it needs is
# same-origin: hashed JS and CSS, the pdf.js worker, and `/api`. `style-src 'unsafe-inline'`
# is the one concession — React sets inline styles for the resizable pane and the PDF canvas.
# `blob:` covers the object URLs pdf.js and the export download create, and images are
# `data:` because the rendered page is drawn into a canvas.
APP_CSP = (
    "default-src 'self'; script-src 'self'; worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; "
    "connect-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'self'"
)
HSTS = "max-age=31536000; includeSubDomains"

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": API_CSP,
    # An export or an extracted table should never sit in a shared cache.
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach the response headers that browsers enforce on our behalf.

    HSTS is deliberately withheld in development: pinning `localhost` to HTTPS for a year
    would break every other local project on the machine.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in BASE_HEADERS.items():
            response.headers.setdefault(header, value)
        # A served page is the one response that must be allowed to load its own scripts, so
        # it gets the app policy instead of the API's `default-src 'none'`. Keyed on the
        # content type rather than the path so a JSON or file response never picks it up.
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = APP_CSP
        if get_settings().environment != "development":
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response
