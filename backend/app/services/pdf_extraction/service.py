from __future__ import annotations

from app.core.config import Settings, get_settings

from .errors import (
    ExtractionRequestError,
    ExtractorError,
    ExtractorUnavailableError,
    PdfExtractionError,
    UnsupportedPdfError,
)
from .extractor import ClaudeDataPointExtractor, DataPointExtractor, RawDataPoint
from .fetch import PdfFetcher
from .grounding import cite, collapse_whitespace
from .models import (
    CellStatus,
    ExtractionCell,
    ExtractionField,
    ExtractionTable,
    PaperRow,
    ParsedDocument,
    RowStatus,
    fields_from_goal,
)
from .parsing import parse_pdf

MAX_FIELDS = 25


class PdfExtractionService:
    """
    Turns research PDFs into review-table rows whose every cell cites its source span.

    A run is three stages: parse the PDF into position-aware blocks, ask the LLM for values
    with a verbatim supporting quote, then ground each quote back to a block by string
    matching. The grounding stage is deterministic and is what makes a citation trustworthy —
    a value the model could not quote is kept but marked `ungrounded`, never presented as
    sourced.
    """

    def __init__(
        self,
        extractor: DataPointExtractor | None = None,
        fetcher: PdfFetcher | None = None,
        *,
        max_pages: int | None = None,
    ) -> None:
        self.extractor = extractor
        self.fetcher = fetcher or PdfFetcher()
        self.max_pages = max_pages

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PdfExtractionService:
        settings = settings or get_settings()
        extractor: DataPointExtractor | None = None
        if settings.anthropic_api_key:
            extractor = ClaudeDataPointExtractor(
                api_key=settings.anthropic_api_key,
                model=settings.llm_model,
                base_url=settings.anthropic_base_url,
                anthropic_version=settings.anthropic_version,
                max_tokens=settings.pdf_extraction_max_tokens,
                timeout=settings.pdf_extraction_timeout_seconds,
                max_context_chars=settings.pdf_extraction_context_chars,
            )
        return cls(
            extractor,
            PdfFetcher(timeout=settings.pdf_fetch_timeout_seconds),
            max_pages=settings.pdf_extraction_max_pages,
        )

    async def aclose(self) -> None:
        await self.fetcher.aclose()
        extractor = self.extractor
        if isinstance(extractor, ClaudeDataPointExtractor):
            await extractor.aclose()

    def parse(self, data: bytes, *, filename: str = "", source_url: str = "") -> ParsedDocument:
        return parse_pdf(data, filename=filename, source_url=source_url, max_pages=self.max_pages)

    async def fetch(self, url: str) -> tuple[bytes, str]:
        return await self.fetcher.fetch(url)

    def resolve_fields(
        self, goal: str = "", fields: list[ExtractionField] | None = None
    ) -> list[ExtractionField]:
        resolved = list(fields) if fields else fields_from_goal(goal)
        if not resolved:
            raise ExtractionRequestError("an extraction goal with at least one field is required")
        if len(resolved) > MAX_FIELDS:
            raise ExtractionRequestError(f"at most {MAX_FIELDS} fields can be extracted at once")
        return resolved

    async def extract_row(
        self,
        document: ParsedDocument,
        fields: list[ExtractionField],
    ) -> PaperRow:
        """Fill one paper's row. Every returned cell is grounded, ungrounded, or not found."""
        if self.extractor is None:
            raise ExtractorUnavailableError(
                "no LLM credentials are configured; set ANTHROPIC_API_KEY"
            )
        points = await self.extractor.extract(document, fields)
        return self.build_row(document, fields, points)

    def build_row(
        self,
        document: ParsedDocument,
        fields: list[ExtractionField],
        points: list[RawDataPoint],
    ) -> PaperRow:
        by_field = {point.field: point for point in points}
        cells: dict[str, ExtractionCell] = {}
        warnings: list[str] = []

        for field in fields:
            point = by_field.get(field.key)
            if point is None:
                cells[field.key] = ExtractionCell(
                    status=CellStatus.NOT_FOUND, note="not stated in this paper"
                )
                continue
            value = collapse_whitespace(point.value)
            citation = cite(document, point.quote, block_id=point.block_id) if point.quote else None
            if citation is None:
                warnings.append(f"{field.key}: quoted text was not found in the parsed PDF")
                cells[field.key] = ExtractionCell(
                    value=value,
                    status=CellStatus.UNGROUNDED,
                    note="the supporting quote could not be located in the source text",
                )
                continue
            cells[field.key] = ExtractionCell(
                value=value, citation=citation, status=CellStatus.GROUNDED
            )

        return PaperRow(
            document_id=document.document_id,
            title=document.title,
            source_url=document.source_url,
            filename=document.filename,
            page_count=document.page_count,
            status=RowStatus.EXTRACTED,
            cells=cells,
            warnings=warnings,
        )

    async def extract_from_bytes(
        self,
        data: bytes,
        *,
        goal: str = "",
        fields: list[ExtractionField] | None = None,
        filename: str = "",
        source_url: str = "",
    ) -> ExtractionTable:
        resolved = self.resolve_fields(goal, fields)
        document = self.parse(data, filename=filename, source_url=source_url)
        row = await self.extract_row(document, resolved)
        return ExtractionTable(goal=goal, columns=resolved, rows=[row])

    async def extract_from_url(
        self,
        url: str,
        *,
        goal: str = "",
        fields: list[ExtractionField] | None = None,
    ) -> ExtractionTable:
        resolved = self.resolve_fields(goal, fields)
        data, resolved_url = await self.fetch(url)
        return await self.extract_from_bytes(
            data, fields=resolved, goal=goal, source_url=resolved_url
        )

    async def extract_table(
        self,
        documents: list[ParsedDocument],
        *,
        goal: str = "",
        fields: list[ExtractionField] | None = None,
    ) -> ExtractionTable:
        """
        Fill one row per paper against a shared column set.

        A paper that cannot be read or extracted still produces a row — with an
        `unsupported` or `failed` status and a warning — so the table keeps its shape.
        """
        resolved = self.resolve_fields(goal, fields)
        rows: list[PaperRow] = []
        for document in documents:
            try:
                rows.append(await self.extract_row(document, resolved))
            except ExtractorError as exc:
                rows.append(self._failed_row(document, RowStatus.FAILED, str(exc)))
            except UnsupportedPdfError as exc:
                rows.append(self._failed_row(document, RowStatus.UNSUPPORTED, str(exc)))
        return ExtractionTable(goal=goal, columns=resolved, rows=rows)

    @staticmethod
    def _failed_row(document: ParsedDocument, status: RowStatus, message: str) -> PaperRow:
        return PaperRow(
            document_id=document.document_id,
            title=document.title,
            source_url=document.source_url,
            filename=document.filename,
            page_count=document.page_count,
            status=status,
            warnings=[message],
        )


__all__ = ["PdfExtractionService", "PdfExtractionError"]
