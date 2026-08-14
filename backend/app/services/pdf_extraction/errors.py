class PdfExtractionError(Exception):
    """Base class for every failure raised by the PDF extraction pipeline."""


class UnsupportedPdfError(PdfExtractionError):
    """The file is not a PDF, or carries no text layer (scanned/image-only)."""


class PdfParseError(PdfExtractionError):
    """The bytes claim to be a PDF but pdfplumber could not open them."""


class PdfFetchError(PdfExtractionError):
    """The source URL could not be fetched, or did not serve a PDF."""


class ExtractionRequestError(PdfExtractionError):
    """The extraction goal was empty or otherwise unusable."""


class ExtractorError(PdfExtractionError):
    """The LLM was unreachable, or returned something that could not be parsed."""


class ExtractorUnavailableError(ExtractorError):
    """No LLM credentials are configured, so no extraction can be attempted."""
