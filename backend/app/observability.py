import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager

import litellm

from app.config import get_settings

logger = logging.getLogger("coach.llm")


def setup_observability() -> None:
    """Send LiteLLM traces to Langfuse when keys are configured."""
    s = get_settings()
    if s.langfuse_public_key and s.langfuse_secret_key:
        os.environ.setdefault("LANGFUSE_PUBLIC_KEY", s.langfuse_public_key)
        os.environ.setdefault("LANGFUSE_SECRET_KEY", s.langfuse_secret_key)
        os.environ.setdefault("LANGFUSE_HOST", s.langfuse_host)
        litellm.success_callback = ["langfuse"]
        litellm.failure_callback = ["langfuse"]
        logger.info("Langfuse tracing enabled")
    else:
        logger.info("Langfuse keys not set; tracing disabled")


@contextmanager
def trace_llm(task: str, model: str) -> Iterator[None]:
    start = time.perf_counter()
    ok = False
    try:
        yield
        ok = True
    finally:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info("llm task=%s model=%s ok=%s latency_ms=%.0f", task, model, ok, latency_ms)
