import asyncio

import redis.asyncio as redis
from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db.session import engine

router = APIRouter()


async def _check_db() -> str:
    try:
        async with asyncio.timeout(2):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception:  # noqa: BLE001 - any failure means "unavailable"
        return "unavailable"


async def _check_redis() -> str:
    client = redis.from_url(get_settings().redis_url)
    try:
        async with asyncio.timeout(2):
            await client.ping()
        return "ok"
    except Exception:  # noqa: BLE001 - any failure means "unavailable"
        return "unavailable"
    finally:
        await client.aclose()


@router.get("/health")
async def health() -> dict:
    db, cache = await asyncio.gather(_check_db(), _check_redis())
    return {"status": "ok", "database": db, "redis": cache}
