import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import HTTPException
from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import ArgumentError, OperationalError, TimeoutError as SQLAlchemyTimeoutError
from sqlalchemy.orm import declarative_base, sessionmaker

load_dotenv(Path(__file__).with_name(".env"))


def _database_url(raw_url: str | None = None):
    url = (raw_url if raw_url is not None else os.getenv("DATABASE_URL", "")).strip()
    # Accept values pasted as `DATABASE_URL=...` or wrapped in quotes from a dotenv snippet.
    if url.startswith("DATABASE_URL="):
        url = url[len("DATABASE_URL="):].strip()
    if len(url) >= 2 and url[0] == url[-1] and url[0] in {'\"', "'"}:
        url = url[1:-1].strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL is missing. Set it in the hosting environment or backend/.env."
        )
    # Normalize the legacy PostgreSQL scheme.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    # Always parse the authority at its final @ separator, then let SQLAlchemy
    # encode username/password. This tolerates passwords containing raw @ or /.
    try:
        return _build_url_from_raw_credentials(url)
    except (ArgumentError, ValueError, TypeError) as parse_error:
        raise RuntimeError(
            "DATABASE_URL is malformed. Set a PostgreSQL URL with username, password, "
            "host, and database; URL-encode special characters if needed."
        ) from parse_error


def _build_url_from_raw_credentials(url: str) -> str:
    from urllib.parse import unquote
    from sqlalchemy.engine import make_url

    scheme, separator, rest = url.partition("://")
    if not separator or scheme not in {"postgresql+psycopg", "postgresql"}:
        raise ValueError("unsupported database URL scheme")
    userinfo, at, host_and_path = rest.rpartition("@")
    if not at or not userinfo or not host_and_path:
        raise ValueError("missing URL credentials or host")
    username, colon, password = userinfo.partition(":")
    if not colon or not username or not password:
        raise ValueError("missing URL username or password")
    parsed = make_url(f"{scheme}://{host_and_path}")
    if not parsed.host or not parsed.database:
        raise ValueError("missing database host or database name")
    params = dict(parsed.query)
    safe = URL.create(
        "postgresql+psycopg",
        username=unquote(username),
        password=unquote(password),
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
        query=params,
    )
    return safe.render_as_string(hide_password=False)


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
