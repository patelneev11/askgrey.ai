"""Serving the built frontend from the API process (single-origin deployment)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.headers import SecurityHeadersMiddleware
from app.core.spa import IMMUTABLE_CACHE, mount_spa

INDEX = '<!doctype html><html><body><div id="root"></div></body></html>'


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX)
    (root / "assets" / "app-a1b2c3.js").write_text("export const x = 1;\n")
    (root / "favicon.svg").write_text("<svg/>")
    return root


@pytest.fixture
def served(dist: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_spa(app, str(dist))
    with TestClient(app) as client:
        yield client


def test_the_root_serves_the_app(served: TestClient) -> None:
    response = served.get("/")

    assert response.status_code == 200
    assert '<div id="root">' in response.text


def test_a_client_route_serves_the_app_so_a_deep_link_survives_a_reload(
    served: TestClient,
) -> None:
    # The router owns /literature; a 404 here is the classic broken refresh.
    response = served.get("/literature")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_the_served_page_is_allowed_to_load_its_own_scripts(served: TestClient) -> None:
    # The API's `default-src 'none'` would block every script in the bundle, so a page
    # response has to carry the app policy instead.
    policy = served.get("/").headers["Content-Security-Policy"]

    assert "script-src 'self'" in policy
    assert "worker-src 'self' blob:" in policy
    assert "frame-ancestors 'none'" in policy


def test_an_api_response_keeps_the_locked_down_policy(served: TestClient) -> None:
    policy = served.get("/api/health").headers["Content-Security-Policy"]

    assert policy.startswith("default-src 'none'")


def test_an_unknown_api_path_stays_a_json_404(served: TestClient) -> None:
    # Falling through to index.html would answer a mistyped fetch URL with HTML and a 200.
    response = served.get("/api/nope")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_hashed_assets_are_cached_forever_and_the_page_is_not(served: TestClient) -> None:
    asset = served.get("/assets/app-a1b2c3.js")

    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == IMMUTABLE_CACHE
    # index.html names the hashed files, so a cached copy outlives the assets it points at.
    assert served.get("/").headers["Cache-Control"] == "no-store"


def test_a_real_file_in_the_build_root_is_served_as_itself(served: TestClient) -> None:
    response = served.get("/favicon.svg")

    assert response.status_code == 200
    assert response.text == "<svg/>"


def test_a_traversal_attempt_cannot_read_outside_the_build(served: TestClient, dist: Path) -> None:
    secret = dist.parent / "secret.txt"
    secret.write_text("not yours")

    response = served.get("/../secret.txt")

    # Either normalised away by the client or answered with the app; never the file.
    assert "not yours" not in response.text


def test_an_unbuilt_directory_fails_at_boot_rather_than_404ing_every_page(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="FRONTEND_DIST_DIR"):
        mount_spa(FastAPI(), str(tmp_path))
