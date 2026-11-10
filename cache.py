import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi.encoders import jsonable_encoder
from redis import Redis
from redis.exceptions import RedisError

load_dotenv(Path(__file__).with_name(".env"))
logger = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_TTL_SECONDS = max(1, int(os.getenv("CACHE_TTL_SECONDS", "30")))
REDIS_FAILURE_COOLDOWN_SECONDS = max(5, int(os.getenv("REDIS_FAILURE_COOLDOWN_SECONDS", "60")))
_client = Redis.from_url(
    REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=0.25,
    socket_timeout=0.25,
    retry_on_timeout=False,
) if REDIS_URL else None
_redis_disabled_until = 0.0


def _available_client():
    if _client is None or time.monotonic() < _redis_disabled_until:
        return None
    return _client


def _disable_temporarily(error):
    global _redis_disabled_until
    _redis_disabled_until = time.monotonic() + REDIS_FAILURE_COOLDOWN_SECONDS
    logger.warning("Redis unavailable; bypassing cache for %ss: %s", REDIS_FAILURE_COOLDOWN_SECONDS, error)


def cache_get(key: str) -> Any | None:
    client = _available_client()
    if client is None:
        return None
    try:
        cached = client.get(key)
        return json.loads(cached) if cached is not None else None
    except RedisError as error:
        _disable_temporarily(error)
        return None
    except ValueError:
        logger.warning("Invalid JSON in Redis cache; treating it as a cache miss")
        return None


def cache_set(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    client = _available_client()
    if client is None:
        return
    try:
        client.setex(key, ttl, json.dumps(jsonable_encoder(value), separators=(",", ":")))
    except RedisError as error:
        _disable_temporarily(error)
    except (TypeError, ValueError) as error:
        logger.warning("Redis cache serialization skipped: %s", error)


def invalidate_cache(*patterns: str) -> None:
    client = _available_client()
    if client is None:
        return
    try:
        for pattern in patterns:
            for key in client.scan_iter(match=pattern, count=100):
                client.delete(key)
    except RedisError as error:
        _disable_temporarily(error)


def redis_health() -> bool:
    client = _available_client()
    if client is None:
        return False
    try:
        return bool(client.ping())
    except RedisError as error:
        _disable_temporarily(error)
        return False
