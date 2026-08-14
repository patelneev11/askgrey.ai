from __future__ import annotations

import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app.services.export import CSV_MEDIA_TYPE, DATA_SHEET, XLSX_MEDIA_TYPE
from tests.export.conftest import sample_table

CREDENTIALS = {"email": "exporter@askgrey.ai", "password": "obsidian-workspace-1"}


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def body(**options: object) -> dict[str, object]:
    payload: dict[str, object] = {"table": sample_table().model_dump(mode="json")}
    if options:
        payload["options"] = options
    return payload


def test_export_requires_authentication(client: TestClient) -> None:
    assert client.post("/api/export/csv", json=body()).status_code == 401


def test_csv_download(client: TestClient) -> None:
    response = client.post("/api/export/csv", json=body(), headers=auth_header(client))

    assert response.status_code == 200
    assert response.headers["content-type"] == CSV_MEDIA_TYPE
    assert 'filename="review-table.csv"' in response.headers["content-disposition"]
    assert "73 patients" in response.content.decode("utf-8")


def test_xlsx_download_is_a_readable_workbook(client: TestClient) -> None:
    response = client.post("/api/export/xlsx", json=body(), headers=auth_header(client))

    assert response.status_code == 200
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    workbook = load_workbook(io.BytesIO(response.content))
    assert workbook[DATA_SHEET]["E2"].value == "73 patients"


def test_filename_stem_is_honoured_and_encoded(client: TestClient) -> None:
    response = client.post(
        "/api/export/csv",
        json=body(filename_stem="ziprasidone review — 中文"),
        headers=auth_header(client),
    )

    disposition = response.headers["content-disposition"]
    assert 'filename="ziprasidone review ? ??.csv"' in disposition
    assert (
        "filename*=UTF-8''ziprasidone%20review%20%E2%80%94%20%E4%B8%AD%E6%96%87.csv" in disposition
    )


def test_a_table_with_no_columns_is_422(client: TestClient) -> None:
    response = client.post(
        "/api/export/csv",
        json={
            "table": {"goal": "", "columns": [], "rows": []},
            "options": {"include_metadata": False},
        },
        headers=auth_header(client),
    )

    assert response.status_code == 422
