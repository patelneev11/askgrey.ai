from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import mount_frontend


def build_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>askgrey</title>")
    (dist / "assets" / "index.js").write_text("console.log('app')")
    return dist


def spa_client(tmp_path: Path) -> TestClient:
    application = FastAPI()

    @application.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    mount_frontend(application, build_dist(tmp_path))
    return TestClient(application)


def test_the_api_still_answers_when_the_spa_is_mounted(tmp_path: Path) -> None:
    assert spa_client(tmp_path).get("/api/health").json() == {"status": "ok"}


def test_a_client_route_reloads_into_the_spa(tmp_path: Path) -> None:
    # Client-side routes have no file of their own; reloading one must not 404.
    response = spa_client(tmp_path).get("/literature")

    assert response.status_code == 200
    assert "askgrey" in response.text


def test_built_assets_are_served(tmp_path: Path) -> None:
    assert spa_client(tmp_path).get("/assets/index.js").status_code == 200


def test_a_traversal_path_cannot_escape_the_dist_directory(tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("not for the browser")

    response = spa_client(tmp_path).get("/../secret.txt")

    assert "not for the browser" not in response.text
