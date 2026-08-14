from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services.export import (
    ExportError,
    ExportFile,
    ExportFormat,
    ExportOptions,
    ExportService,
)
from app.services.pdf_extraction import ExtractionTable

router = APIRouter(prefix="/export", tags=["export"])


def get_export_service() -> ExportService:
    return ExportService()


Service = Annotated[ExportService, Depends(get_export_service)]


class ExportRequest(BaseModel):
    """A review table plus the shape options for the rendered file."""

    table: ExtractionTable
    options: ExportOptions = Field(default_factory=ExportOptions)


def _download(file: ExportFile) -> Response:
    """
    RFC 6266 disposition.

    Headers are latin-1 on the wire, so the plain `filename` is an ASCII fallback and the
    real name rides in the percent-encoded `filename*` that every current browser prefers.
    """
    ascii_name = file.filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file.filename)}"
    return Response(
        content=file.content,
        media_type=file.media_type,
        headers={"Content-Disposition": disposition, "Content-Length": str(file.size)},
    )


def _render(service: ExportService, request: ExportRequest, fmt: ExportFormat) -> Response:
    try:
        return _download(service.render(request.table, fmt, request.options))
    except ExportError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/xlsx")
def export_xlsx(_user: CurrentUser, service: Service, request: ExportRequest) -> Response:
    return _render(service, request, ExportFormat.XLSX)


@router.post("/csv")
def export_csv(_user: CurrentUser, service: Service, request: ExportRequest) -> Response:
    return _render(service, request, ExportFormat.CSV)
