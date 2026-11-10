import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from redis import Redis
from redis.exceptions import RedisError
from fastapi.encoders import jsonable_encoder

load_dotenv(Path(__file__).with_name(".env"))
logger = logging.getLogger(__name__)
REDIS_URL = os.getenv("REDIS_URL", "").strip()
CACHE_TTL_SECONDS = max(1, int(os.getenv("CACHE_TTL_SECONDS", "30")))
_client = Redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1, socket_timeout=1) if REDIS_URL else None


def cache_get(key: str) -> Any | None:
    if _client is None:
        return None
    try:
        cached = _client.get(key)
        return json.loads(cached) if cached is not None else None
    except (RedisError, ValueError) as error:
        logger.warning("Redis cache read skipped: %s", error)
        return None


def cache_set(key: str, value: Any, ttl: int = CACHE_TTL_SECONDS) -> None:
    if _client is None:
        return
    try:
        _client.setex(key, ttl, json.dumps(jsonable_encoder(value), separators=(",", ":")))
    except (RedisError, TypeError, ValueError) as error:
        logger.warning("Redis cache write skipped: %s", error)


def invalidate_cache(*patterns: str) -> None:
    if _client is None:
        return
    try:
        for pattern in patterns:
            for key in _client.scan_iter(match=pattern, count=100):
                _client.delete(key)
    except RedisError as error:
        logger.warning("Redis cache invalidation skipped: %s", error)


def redis_health() -> bool:
    if _client is None:
        return False
    try:
        return bool(_client.ping())
    except RedisError:
        return False
