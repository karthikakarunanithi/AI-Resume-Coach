"""Per-call usage records: tokens, latency, cost, fallbacks (plan 15/16: cost per session, p95 latency, fallback rate)."""

from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

import litellm

# Set by the interview manager around every turn/finalize; background tasks inherit it (asyncio copies context)
current_session_id: ContextVar[str | None] = ContextVar("current_session_id", default=None)


@dataclass
class LLMCallRecord:
    task: str
    configured_model: str
    model: str  # the model that answered; differs from configured_model when a fallback was used
    prompt_version: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: float
    ttft_ms: float | None  # time to first token (streaming only)
    cost_usd: float | None
    success: bool
    json_valid: bool | None  # structured calls only
    error: str | None
    session_id: str | None


Recorder = Callable[[LLMCallRecord], None]


def tokens_of(resp: Any) -> tuple[int, int]:
    usage = getattr(resp, "usage", None)
    if not usage:
        return 0, 0
    return int(getattr(usage, "prompt_tokens", 0) or 0), int(getattr(usage, "completion_tokens", 0) or 0)


def cost_of(cfg: dict, resp: Any, input_tokens: int, output_tokens: int) -> float | None:
    """Prices from models.yaml (input/output USD per million tokens) win; otherwise LiteLLM's price table."""
    if "input_usd_per_mtok" in cfg and "output_usd_per_mtok" in cfg:
        return (input_tokens * cfg["input_usd_per_mtok"] + output_tokens * cfg["output_usd_per_mtok"]) / 1e6
    try:
        return float(litellm.completion_cost(completion_response=resp))
    except Exception:  # noqa: BLE001 - LiteLLM raises various errors for unknown models or missing usage
        return None
