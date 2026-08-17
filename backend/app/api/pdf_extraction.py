import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import ClientIp, DbSession, LlmUser
from app.api.literature import DocumentId
from app.core import audit
from app.core.config import get_settings
from app.services import literature as literature_service
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


class StoredExtractionRequest(BaseModel):
    """Extraction against a paper this user already added, re-read from the stored bytes."""

    goal: str = Field(default="", max_length=2000)
    fields: list[ExtractionField] = Field(default_factory=list)


class UrlExtractionRequest(BaseModel):
    """Extraction against a full-text link; a PMC article URL is resolved to its PDF."""

    url: str = Field(min_length=1, max_length=2000)
    goal: str = Field(default="", max_length=2000)
    fields: list[ExtractionField] = Field(default_factory=list)


async def _read_upload(request: Request, file: UploadFile) -> bytes:
    """Read the upload with the size cap enforced as it streams, not after it is buffered."""
    too_large = HTTPException(
        status.HTTP_413_CONTENT_TOO_LARGE,
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
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    if isinstance(exc, UnsupportedPdfError):
        return HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, str(exc))
    if isinstance(exc, PdfParseError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    if isinstance(exc, PdfFetchError):
        return HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))
    if isinstance(exc, ExtractorUnavailableError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"extraction failed: {exc}")


def _record_outbound(actor: str, ip: str, source: str, size: int) -> None:
    """Note that document text left the deployment for the model vendor.

    Only the provenance is recorded — never the text, the goal or the extracted values.
    """
    audit.record(
        "document.sent_to_llm",
        actor=actor,
        client_ip=ip,
        detail={
            "source": source,
            "bytes": size,
            "vendor": "anthropic",
            "model": get_settings().llm_model,
        },
    )


def _keep(
    db: Session,
    user_id: str,
    table: ExtractionTable,
    data: bytes,
    *,
    filename: str = "",
    source_url: str = "",
) -> None:
    """Keep the paper's bytes for this user so the citation viewer can render its pages.

    Without this a linked paper can only ever be quoted — the browser cannot re-fetch it
    cross-origin — and an uploaded one is lost the moment the tab reloads.
    """
    for row in table.rows:
        literature_service.store_document(
            db,
            user_id,
            document_id=row.document_id,
            content=data,
            filename=filename or row.filename,
            source_url=source_url or row.source_url,
        )


@router.post("/upload", response_model=ExtractionTable)
async def extract_from_upload(
    user: LlmUser,
    ip: ClientIp,
    service: Service,
    db: DbSession,
    request: Request,
    file: Annotated[UploadFile, File(description="The research PDF")],
    goal: Annotated[str, Form(max_length=2000, description="e.g. 'sample size, dosing'")],
) -> ExtractionTable:
    data = await _read_upload(request, file)
    _record_outbound(str(user.id), ip, file.filename or "upload.pdf", len(data))
    if _parse_slots.locked():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "too many documents are being parsed right now; retry shortly",
        )
    try:
        async with _parse_slots:
            table = await service.extract_from_bytes(
                data, goal=goal, filename=file.filename or "upload.pdf"
            )
        _keep(db, str(user.id), table, data, filename=file.filename or "upload.pdf")
        return table
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


@router.post("/documents/{document_id}", response_model=ExtractionTable)
async def extract_from_stored_document(
    user: LlmUser,
    ip: ClientIp,
    service: Service,
    db: DbSession,
    document_id: DocumentId,
    request: StoredExtractionRequest,
) -> ExtractionTable:
    """Re-run extraction over a paper the user added earlier.

    After a reload the browser no longer holds the uploaded bytes, so a saved workspace can
    only add a column to an uploaded paper if the server can re-read it. The bytes are read
    from this user's own stored copy — never fetched from anywhere.
    """
    document = literature_service.get_document(db, str(user.id), document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no such document")
    data = document.content
    _record_outbound(str(user.id), ip, document.filename or document_id, len(data))
    if _parse_slots.locked():
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "too many documents are being parsed right now; retry shortly",
        )
    try:
        async with _parse_slots:
            return await service.extract_from_bytes(
                data,
                goal=request.goal,
                fields=request.fields or None,
                filename=document.filename,
                source_url=document.source_url,
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
    user: LlmUser,
    ip: ClientIp,
    service: Service,
    db: DbSession,
    request: UrlExtractionRequest,
) -> ExtractionTable:
    _record_outbound(str(user.id), ip, request.url, 0)
    try:
        data, resolved_url = await service.fetch(request.url)
        table = await service.extract_from_bytes(
            data,
            goal=request.goal,
            fields=request.fields or None,
            source_url=resolved_url,
        )
        _keep(db, str(user.id), table, data, source_url=resolved_url)
        return table
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
