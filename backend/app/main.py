import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.clinicaltrials import router as clinicaltrials_router
from app.api.export import router as export_router
from app.api.grants import router as grants_router
from app.api.pdf_extraction import router as pdf_extraction_router
from app.api.pubchem import router as pubchem_router
from app.api.pubmed import router as pubmed_router
from app.core.config import get_settings
from app.db.session import engine
from app.models.base import Base
from app.models.session import RefreshSession  # noqa: F401  (registers the table)
from app.models.user import User  # noqa: F401  (registers the table on Base.metadata)

settings = get_settings()

# Audit events are emitted at INFO on their own logger so a deployment can route them to a
# separate sink without turning on debug logging for everything else.
logging.getLogger("askgrey.audit").setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api")
app.include_router(pubmed_router, prefix="/api")
app.include_router(pubchem_router, prefix="/api")
app.include_router(clinicaltrials_router, prefix="/api")
app.include_router(pdf_extraction_router, prefix="/api")
app.include_router(export_router, prefix="/api")
app.include_router(grants_router, prefix="/api")


@app.get("/api/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}
