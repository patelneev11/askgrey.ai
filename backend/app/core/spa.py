"""Serving the built frontend from the API process.

Optional, and off unless `FRONTEND_DIST_DIR` is set. When it is on, the app and the API share
one origin, which is what makes the session cookie a first-party cookie and removes CORS from
the deployment; when it is off nothing here is mounted and the API behaves as it always did.
"""

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from starlette.responses import FileResponse, Response
from starlette.staticfiles import StaticFiles

# Vite writes hashed filenames into assets/, so a stale copy can never be served under a name
# whose contents changed — the only safe long cache in the build.
IMMUTABLE_CACHE = "public, max-age=31536000, immutable"
# index.html names those hashed files, so a cached copy would point at assets a later deploy
# has already removed.
INDEX_CACHE = "no-store"

# Where the interactive docs live when they are published. A deployment does not publish them,
# and they are not client routes either, so without this the catch-all answers a scanner's
# `/openapi.json` with the app and a 200 — a hit, where the path should read as absent. In
# development FastAPI owns these routes and is matched first.
SCHEMA_PATHS = frozenset({"docs", "docs/oauth2-redirect", "redoc", "openapi.json"})


class HashedAssets(StaticFiles):
    """`assets/` only, served with an immutable cache since every name carries a digest."""

    async def get_response(self, path: str, scope: Any) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = IMMUTABLE_CACHE
        return response


def mount_spa(app: FastAPI, dist_dir: str) -> None:
    """Serve `dist_dir` as the app: hashed assets, then index.html for client routes.

    Raises if the directory has no build in it, because the alternative is a deployment that
    boots healthy and answers every page with 404.
    """
    root = Path(dist_dir).expanduser().resolve()
    index = root / "index.html"
    if not index.is_file():
        raise RuntimeError(
            f"FRONTEND_DIST_DIR={dist_dir!r} has no index.html; build the frontend "
            "(`npm run build` in frontend/) or leave it unset to serve only the API"
        )

    assets = root / "assets"
    if assets.is_dir():
        app.mount("/assets", HashedAssets(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        """Any non-API path renders the app, so a deep link survives a full page load.

        `/api/...` is excluded rather than falling through: an unknown API path must stay a
        JSON 404, or a typo in a fetch URL comes back as HTML with a 200.
        """
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")

        if path in SCHEMA_PATHS:
            raise HTTPException(status_code=404, detail="Not found")

        # `/.env`, `/.git/config` and the rest of a scanner's list are not client routes, and
        # answering them with the app means a 200 for a path that should read as absent. The
        # build contains no dotfiles, so refusing every one of them costs nothing —
        # `/.well-known/...` excepted, which a build may legitimately publish as a real file.
        segments = path.split("/")
        hidden = [
            segment
            for index, segment in enumerate(segments)
            if segment.startswith(".") and not (index == 0 and segment == ".well-known")
        ]
        if hidden:
            raise HTTPException(status_code=404, detail="Not found")

        # A real file in the build root (favicon, manifest, the pdf.js worker) is served as
        # itself; anything else is a client route. `resolve` plus the containment check is
        # what keeps `..` inside the build directory.
        candidate = (root / path).resolve() if path else index
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)

        return FileResponse(index, headers={"Cache-Control": INDEX_CACHE})
