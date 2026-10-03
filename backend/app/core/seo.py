"""robots.txt and sitemap.xml, answered per hostname.

The marketing site and the product are one image on two hostnames, so these two files cannot be
static: the public site wants to be crawled and listed, and the signed-in product wants neither.
Serving a single static robots.txt would either hide the marketing pages or invite crawlers into
an app where every path is a redirect to a sign-in screen.
"""

from fastapi import FastAPI, Request
from starlette.responses import PlainTextResponse, Response

from app.core.config import get_settings

CACHE = "public, max-age=3600"

# Only the public marketing routes, including the page each product tab has of its own. The
# signed-in app's routes are deliberately absent: they need a session, so listing them would
# advertise a surface that answers nothing useful to a crawler.
PRODUCT_TABS = (
    "literature",
    "screening",
    "protocol",
    "regulatory",
    "grants",
    "assistant",
    "workspace",
    "audit",
    "settings",
)
MARKETING_PATHS = (
    "/",
    *(f"/product/{tab}" for tab in PRODUCT_TABS),
    "/security",
    "/terms",
)


def _is_marketing(request: Request) -> bool:
    host = (request.headers.get("host") or "").split(":")[0].lower()
    marketing = get_settings().marketing_host.lower()
    return bool(marketing) and host in {marketing, f"www.{marketing}"}


def _robots(request: Request) -> str:
    if not _is_marketing(request):
        return "User-agent: *\nDisallow: /\n"
    settings = get_settings()
    return (
        "User-agent: *\n"
        "Allow: /\n"
        # The API is not content, and a crawler walking it burns rate limit for nothing.
        "Disallow: /api/\n"
        f"\nSitemap: https://{settings.marketing_host}/sitemap.xml\n"
    )


def _sitemap(request: Request) -> str:
    base = f"https://{get_settings().marketing_host}"
    urls = "".join(
        f"  <url><loc>{base}{path}</loc><changefreq>weekly</changefreq>"
        f"<priority>{'1.0' if path == '/' else '0.6'}</priority></url>\n"
        for path in MARKETING_PATHS
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}"
        "</urlset>\n"
    )


def mount_seo(app: FastAPI) -> None:
    """Register the two crawler files. Must run before the SPA catch-all claims every path."""

    @app.get("/robots.txt", include_in_schema=False)
    def robots(request: Request) -> Response:
        return PlainTextResponse(_robots(request), headers={"Cache-Control": CACHE})

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap(request: Request) -> Response:
        # A crawler that found the sitemap on the product host is told nothing about it: the
        # listed URLs are the marketing host's either way.
        return Response(
            _sitemap(request), media_type="application/xml", headers={"Cache-Control": CACHE}
        )
