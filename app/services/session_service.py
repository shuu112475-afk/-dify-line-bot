import json
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings


def get_redis() -> aioredis.Redis:
    return aioredis.Redis.from_url(settings.redis_url, decode_responses=True)


# ──────────────────────────────────────────────
# Session (conversation_id cache)
# ──────────────────────────────────────────────

async def get_conversation_id(line_user_id: str) -> Optional[str]:
    r = get_redis()
    raw = await r.hget(f"session:{line_user_id}", "conversation_id")
    await r.aclose()
    return raw


async def set_conversation_id(line_user_id: str, conversation_id: str) -> None:
    r = get_redis()
    pipe = r.pipeline()
    pipe.hset(
        f"session:{line_user_id}",
        mapping={
            "conversation_id": conversation_id,
            "last_active": datetime.now(timezone.utc).isoformat(),
        },
    )
    pipe.expire(f"session:{line_user_id}", settings.session_ttl_seconds)
    await pipe.execute()
    await r.aclose()


async def delete_session(line_user_id: str) -> None:
    r = get_redis()
    await r.delete(f"session:{line_user_id}")
    await r.aclose()


# ──────────────────────────────────────────────
# Event deduplication
# ──────────────────────────────────────────────

async def is_duplicate_event(webhook_event_id: str) -> bool:
    r = get_redis()
    key = f"event:{webhook_event_id}"
    result = await r.set(key, "1", nx=True, ex=settings.event_dedup_ttl_seconds)
    await r.aclose()
    return result is None  # None means key already existed → duplicate


# ──────────────────────────────────────────────
# Reply token used-state
# ──────────────────────────────────────────────

async def mark_reply_token_used(reply_token: str) -> bool:
    """Returns True if the token was freshly marked (first use), False if already used."""
    r = get_redis()
    key = f"reply:{reply_token}"
    result = await r.set(key, "1", nx=True, ex=settings.reply_token_ttl_seconds)
    await r.aclose()
    return result is not None


# ──────────────────────────────────────────────
# Job tracking
# ──────────────────────────────────────────────

async def set_job_status(job_id: str, status: str, extra: Optional[dict] = None) -> None:
    r = get_redis()
    data = {"status": status, **(extra or {})}
    await r.set(f"job:{job_id}", json.dumps(data), ex=settings.job_ttl_seconds)
    await r.aclose()


async def get_job_status(job_id: str) -> Optional[dict]:
    r = get_redis()
    raw = await r.get(f"job:{job_id}")
    await r.aclose()
    return json.loads(raw) if raw else None
