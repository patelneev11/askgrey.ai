from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.db.session import get_db
from app.main import app
from app.models.base import Base


@pytest.fixture(autouse=True)
def fresh_limiters() -> Iterator[None]:
    """The limiters are process-wide singletons, so a test must not inherit another's window."""
    for limiter in (
        deps.auth_ip_limiter,
        deps.auth_account_limiter,
        deps.api_limiter,
        deps.llm_limiter,
        deps.llm_ip_limiter,
    ):
        limiter.reset()
    deps.llm_budget.reset()
    yield


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db() -> Iterator[object]:
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
