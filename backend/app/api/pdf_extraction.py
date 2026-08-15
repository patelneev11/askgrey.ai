import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser
from app.services.pdf_extraction import (
    ExtractionField,
    ExtractionRequestError,
    ExtractionTable,
    ExtractorError,
    ExtractorUnavailableError,
    PdfExtractionService,
    PdfFetchError,
    PdfParseError,
    UnsupportedPdfError,
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 512 * 1024
PDF_MAGIC = b"%PDF-"
# pdfplumber parsing is CPU-bound and holds the whole page tree in memory, so the number of
# documents being parsed at once is capped process-wide rather than left to arrive.
MAX_CONCURRENT_PARSES = 4
_parse_slots = asyncio.Semaphore(MAX_CONCURRENT_PARSES)

router = APIRouter(prefix="/pdf-extraction", tags=["pdf-extraction"])


def get_pdf_extraction_service() -> PdfExtractionService:
    return PdfExtractionService.from_settings()


Service = Annotated[PdfExtractionService, Depends(get_pdf_extraction_service)]


class UrlExtractionRequest(BaseModel):
    """Extraction against a full-text link; a PMC article URL is resolved to its PDF."""

    url: str = Field(min_length=1, max_length=2000)
    goal: str = Field(default="", max_length=2000)
    fields: list[ExtractionField] = Field(default_factory=list)


async def _read_upload(request: Request, file: UploadFile) -> bytes:
    """Read the upload with the size cap enforced as it streams, not after it is buffered."""
    too_large = HTTPException(
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        f"PDF is larger than {MAX_UPLOAD_BYTES} bytes",
    )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise too_large
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(UPLOAD_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise too_large
        chunks.append(chunk)
    data = b"".join(chunks)
    # An arbitrary blob would otherwise reach the PDF parser, which is a large C-adjacent
    # attack surface fed by whatever the caller chose to upload.
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "the uploaded file is not a PDF"
        )
    return data


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, ExtractionRequestError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if isinstance(exc, UnsupportedPdfError):
        return HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc))
    if isinstance(exc, PdfParseError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, PdfFetchError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    if isinstance(exc, ExtractorUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"extraction failed: {exc}")


@router.post("/upload", response_model=ExtractionTable)
async def extract_from_upload(
    _user: CurrentUser,
    service: Service,
    request: Request,
    file: Annotated[UploadFile, File(description="The research PDF")],
    goal: Annotated[str, Form(max_length=2000, description="e.g. 'sample size, dosing'")],
) -> ExtractionTable:
    data = await _read_upload(request, file)
    if _parse_slots.locked():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "too many documents are being parsed right now; retry shortly",
        )
    try:
        async with _parse_slots:
            return await service.extract_from_bytes(
                data, goal=goal, filename=file.filename or "upload.pdf"
            )
    except (
        ExtractionRequestError,
        UnsupportedPdfError,
        PdfParseError,
        ExtractorUnavailableError,
        ExtractorError,
    ) as exc:
        raise _handle(exc) from exc
    finally:
        await service.aclose()


@router.post("/url", response_model=ExtractionTable)
async def extract_from_url(
    _user: CurrentUser,
    service: Service,
    request: UrlExtractionRequest,
) -> ExtractionTable:
    try:
        return await service.extract_from_url(
            request.url, goal=request.goal, fields=request.fields or None
        )
    except (
        ExtractionRequestError,
        UnsupportedPdfError,
        PdfParseError,
        PdfFetchError,
        ExtractorUnavailableError,
        ExtractorError,
    ) as exc:
        raise _handle(exc) from exc
    finally:
        await service.aclose()
