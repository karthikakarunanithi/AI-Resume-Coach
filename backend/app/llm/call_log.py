"""Writes LLM usage records to the llm_calls table from a background queue, so logging never slows a turn."""

import asyncio
import logging
import uuid
from functools import lru_cache

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import LLMCall
from app.llm.usage import LLMCallRecord

logger = logging.getLogger("coach.llm")

MAX_QUEUE = 10_000
BATCH = 100


class LLMCallLogger:
    def __init__(self, session_factory: async_sessionmaker):
        self.session_factory = session_factory
        self.queue: asyncio.Queue[LLMCallRecord] = asyncio.Queue(maxsize=MAX_QUEUE)
        self._task: asyncio.Task | None = None

    def record(self, rec: LLMCallRecord) -> None:
        """LLMClient recorder hook. Called on the event loop; never blocks or raises."""
        try:
            self.queue.put_nowait(rec)
        except asyncio.QueueFull:
            logger.warning("LLM call log queue full; dropping a record")
            return
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def flush(self) -> None:
        """Write everything queued so far (shutdown, tests)."""
        while not self.queue.empty():
            await self._write_batch()

    async def _run(self) -> None:
        while not self.queue.empty():
            await self._write_batch()

    async def _write_batch(self) -> None:
        batch = []
        while not self.queue.empty() and len(batch) < BATCH:
            batch.append(self.queue.get_nowait())
        if not batch:
            return
        try:
            async with self.session_factory() as db:
                db.add_all(_row(r) for r in batch)
                await db.commit()
        except Exception:
            logger.exception("Writing %d LLM call records failed", len(batch))


def _row(r: LLMCallRecord) -> LLMCall:
    return LLMCall(
        session_id=uuid.UUID(r.session_id) if r.session_id else None, task=r.task, model=r.model,
        configured_model=r.configured_model, prompt_version=r.prompt_version, input_tokens=r.input_tokens,
        output_tokens=r.output_tokens, latency_ms=r.latency_ms, ttft_ms=r.ttft_ms, cost_usd=r.cost_usd,
        success=r.success, json_valid=r.json_valid, error=r.error,
    )


@lru_cache
def get_call_logger() -> LLMCallLogger:
    from app.db.session import SessionLocal

    return LLMCallLogger(SessionLocal)
