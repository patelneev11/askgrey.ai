from collections.abc import Generator
from typing import Any

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings

settings = get_settings()


def engine_options(url: str, config: Settings) -> dict[str, Any]:
    """Engine arguments for the database this URL names.

    SQLite and a pooled network database want opposite things: SQLite needs the
    single-thread check waived because FastAPI hands a session to a worker thread and has no
    pool to size, while Postgres needs a bounded pool whose connections are recycled before
    the server or its pooler drops them out from under us.
    """
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {
        "pool_size": config.db_pool_size,
        "max_overflow": config.db_max_overflow,
        "pool_recycle": config.db_pool_recycle_seconds,
        "pool_pre_ping": True,
    }


def create_app_engine(config: Settings) -> Engine:
    url = config.sqlalchemy_url
    return create_engine(url, **engine_options(url, config))


engine = create_app_engine(settings)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
