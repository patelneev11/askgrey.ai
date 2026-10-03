"""Reading an uploaded PDF, under the same limits wherever a tab accepts one.

Shared by the Literature extraction routes and the assistant's attachments: the size cap, the
`%PDF` check and the process-wide parse concurrency are properties of feeding a C-adjacent parser
untrusted bytes, not of the tab that happened to accept the file.
"""

import asyncio

from fastapi import HTTPException, Request, UploadFile, status

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
UPLOAD_CHUNK_BYTES = 512 * 1024
PDF_MAGIC = b"%PDF-"
# pdfplumber parsing is CPU-bound and holds the whole page tree in memory, so the number of
# documents being parsed at once is capped process-wide rather than left to arrive.
MAX_CONCURRENT_PARSES = 4
parse_slots = asyncio.Semaphore(MAX_CONCURRENT_PARSES)


async def read_pdf_upload(request: Request, file: UploadFile) -> bytes:
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


def busy() -> HTTPException:
    return HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "too many documents are being parsed right now; retry shortly",
    )
