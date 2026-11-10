import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine
from sqlalchemy.exc import OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(Path(__file__).with_name(".env"))


def _database_url():
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Add your Render PostgreSQL connection URL "
            "to backend/.env."
        )
    # Render may provide the legacy postgres:// scheme; SQLAlchemy expects postgresql://.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


POOL_SIZE = max(1, int(os.getenv("DB_POOL_SIZE", "5")))
MAX_OVERFLOW = max(0, int(os.getenv("DB_MAX_OVERFLOW", "5")))
POOL_TIMEOUT = max(1, int(os.getenv("DB_POOL_TIMEOUT", "3")))
_url = _database_url()
_engine_options = {
    "pool_pre_ping": True,
    "pool_size": POOL_SIZE,
    "max_overflow": MAX_OVERFLOW,
    "pool_timeout": POOL_TIMEOUT,
    "pool_recycle": 1800,
}
if _url.startswith("postgresql+"):
    _engine_options["connect_args"] = {"connect_timeout": max(1, int(os.getenv("DB_CONNECT_TIMEOUT", "5")))}
engine = create_engine(_url, **_engine_options)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
Base = declarative_base(metadata=MetaData(schema="collabrun_app"))


def get_db():
    db = SessionLocal()
    try:
        # Retry connection establishment only; never replay a transaction/write.
        for attempt, delay in enumerate((0.0, 0.1, 0.25), start=1):
            if delay:
                time.sleep(delay)
            try:
                db.connection()
                break
            except (OperationalError, SQLAlchemyTimeoutError) as error:
                db.rollback()
                if attempt == 3:
                    raise HTTPException(
                        status_code=503,
                        detail="Database is temporarily unavailable. Retry shortly.",
                        headers={"Retry-After": "2"},
                    ) from error
        yield db
    finally:
        db.close()
