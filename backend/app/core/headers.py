from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.config import get_settings

# The API serves JSON and file downloads, never markup that should run script or be framed.
# `default-src 'none'` is therefore the honest policy: nothing here needs to load anything.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# The single-origin deployment serves the built SPA from this process, and that markup does
# need to load its own bundle, styles, and the pdf.js worker (a blob URL).
APP_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'wasm-unsafe-eval' blob:; "
    "worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "font-src 'self' data:; "
    "connect-src 'self' blob: data:; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)
HSTS = "max-age=31536000; includeSubDomains"

BASE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
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
        csp = API_CSP if request.url.path.startswith("/api") else APP_CSP
        response.headers.setdefault("Content-Security-Policy", csp)
        if get_settings().environment != "development":
            response.headers.setdefault("Strict-Transport-Security", HSTS)
        return response
