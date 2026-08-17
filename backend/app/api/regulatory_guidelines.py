import json
import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.api.deps import ThrottledUser
from app.services.regulatory.guidelines import (
    GuidelineChecker,
    GuidelineCheckReport,
    GuidelineConfigError,
    GuidelineInputError,
    Jurisdiction,
    ReferenceLibrary,
)

MAX_SECTION_ID = 40
MAX_DRAFT_CHARS = 60_000
# A draft is text, so the body cannot legitimately be much larger than the character cap even at
# four bytes per character plus JSON escaping.
MAX_BODY_BYTES = 4 * MAX_DRAFT_CHARS

# CTD section ids are dotted digits with optional single letters ("3.2.S.4.1", "2.6.6", "4.2.3").
SECTION_ID_PATTERN = re.compile(r"^[0-9]+(\.[0-9A-Za-z]{1,3})*$")

router = APIRouter(prefix="/regulatory/guidelines", tags=["regulatory"])


def get_guideline_checker() -> GuidelineChecker:
    """Loaded per request; the datasets are small files read from the installed package."""
    try:
        return GuidelineChecker.from_reference_files()
    except GuidelineConfigError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, "guideline reference data is unavailable"
        ) from exc


Checker = Annotated[GuidelineChecker, Depends(get_guideline_checker)]


class GuidelineCheckRequest(BaseModel):
    """
    One draft section, checked against the jurisdictions asked for.

    The draft carries proprietary manufacturing and study data, so it is bounded on the way in and
    never echoed back in an error: a validation message that quotes the text would put it into
    client-side logs and error trackers. The model is therefore validated by hand in the handler
    rather than declared as a body parameter — see `_parse_request`.
    """

    section_id: str = Field(min_length=1, max_length=MAX_SECTION_ID)
    # Deliberately not bounded with `max_length`: the cap is enforced in the handler so that the
    # rejection cannot depend on an error payload carrying the draft. The body size is capped first.
    draft_text: str = Field(min_length=1)
    jurisdictions: list[Jurisdiction] = Field(min_length=1, max_length=len(Jurisdiction))

    @field_validator("section_id")
    @classmethod
    def _check_section_id(cls, value: str) -> str:
        section_id = value.strip()
        if not SECTION_ID_PATTERN.match(section_id):
            raise ValueError("section_id must be a dotted CTD section id, e.g. 3.2.S.4 or 4.2.3")
        return section_id


def _guard_body_size(http_request: Request) -> None:
    """Reject an oversized body on its declared length. Belt and braces behind the deployment's
    own body limit: Starlette has already buffered the body by the time a handler runs."""
    declared = http_request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"request body is larger than {MAX_BODY_BYTES} bytes",
        )


def _rejection_reason(exc: ValidationError) -> str:
    """Name the fields and why, and nothing else. Pydantic's own 422 payload carries the offending
    input alongside the message, which for this route is proprietary draft text."""
    reasons = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"]) or "body"
        reasons.append(f"{field}: {error['msg']}")
    return "; ".join(reasons) or "request body is invalid"


async def _parse_request(http_request: Request) -> GuidelineCheckRequest:
    """Validate the body here rather than declaring it as a parameter, so that no rejected value is
    reflected back to the client: FastAPI's 422 body includes the input it rejected."""
    try:
        payload = await http_request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "request body must be a JSON object"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "request body must be a JSON object"
        )
    try:
        return GuidelineCheckRequest.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, _rejection_reason(exc)) from exc


@router.post(
    "/check",
    response_model=GuidelineCheckReport,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": GuidelineCheckRequest.model_json_schema()}},
        }
    },
)
async def check(
    http_request: Request,
    _user: ThrottledUser,
    checker: Checker,
) -> GuidelineCheckReport:
    """Compare a draft CTD section against the shipped requirement snapshots. No model is called."""
    _guard_body_size(http_request)
    request = await _parse_request(http_request)
    if len(request.draft_text) > MAX_DRAFT_CHARS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"draft_text is longer than {MAX_DRAFT_CHARS} characters",
        )
    try:
        return checker.check(request.section_id, request.draft_text, request.jurisdictions)
    except GuidelineInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.get("/reference", response_model=ReferenceLibrary)
def reference(_user: ThrottledUser, checker: Checker) -> ReferenceLibrary:
    """Versions, retrieved dates, requirement titles and citations behind the checker."""
    return checker.reference()
