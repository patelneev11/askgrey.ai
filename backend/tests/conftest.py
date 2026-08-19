from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
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
def engine() -> Iterator[Engine]:
    """The database the API under test is talking to, so a test can inspect the rows it wrote."""
    built = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=built)
    yield built
    Base.metadata.drop_all(bind=built)
    built.dispose()


@pytest.fixture
def client(engine: Engine) -> Iterator[TestClient]:
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


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session on the API's own database, for arranging state the HTTP surface cannot."""
    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    try:
        yield session
    finally:
        session.close()
