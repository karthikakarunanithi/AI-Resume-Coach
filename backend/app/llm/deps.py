from functools import lru_cache

from app.llm.call_log import get_call_logger
from app.llm.client import LLMClient


@lru_cache
def get_llm() -> LLMClient:
    """FastAPI dependency; tests override it with a fake client. Every call is logged to llm_calls."""
    return LLMClient(recorder=get_call_logger().record)
