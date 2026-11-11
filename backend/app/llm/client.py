import asyncio
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any, TypeVar

import litellm
from litellm import acompletion
from pydantic import BaseModel, ValidationError

from app.config import load_models
from app.llm.errors import describe
from app.llm.json_schema import response_format_for
from app.llm.usage import LLMCallRecord, Recorder, cost_of, current_session_id, tokens_of
from app.observability import trace_llm

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("coach.llm")

RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_WAIT_S = 30.0
# Groq: "Please try again in 12.34s" / "in 850ms"; OpenAI-style providers word it similarly
_RETRY_IN = re.compile(r"try again in\s*(?:(\d+)m)?\s*([\d.]+)\s*(ms|s)", re.IGNORECASE)


def rate_limit_wait_s(exc: BaseException) -> float | None:
    """Seconds to wait if exc is a rate limit (per-minute token caps on free tiers), else None."""
    text = str(exc)
    if not isinstance(exc, litellm.RateLimitError) and "rate limit" not in text.lower():
        return None
    m = _RETRY_IN.search(text)
    if not m:
        return 5.0
    minutes, amount, unit = m.groups()
    seconds = float(amount) / 1000 if unit.lower() == "ms" else float(amount)
    return min(MAX_RATE_LIMIT_WAIT_S, seconds + 60 * int(minutes or 0) + 0.5)


class LLMClient:
    """Single entry point for all LLM calls: routing, retries, fallbacks, tracing, usage records."""

    def __init__(self, models: dict[str, dict[str, Any]] | None = None, recorder: Recorder | None = None):
        self.models = models or load_models()
        self.recorder = recorder

    def _kwargs(self, task: str, messages: list[dict], stream: bool) -> dict[str, Any]:
        cfg = self.models[task]
        kwargs = {
            "model": cfg["model"],
            "messages": messages,
            "max_tokens": cfg["max_tokens"],
            "fallbacks": cfg.get("fallbacks", []),
            "num_retries": 2,
            "timeout": cfg.get("timeout", 20),
            "stream": stream,
            "metadata": {"task": task},
        }
        # Optional: current Claude models reject any non-default sampling parameter (400), so Claude tasks
        # in models.yaml set none; other providers can still use one.
        if "temperature" in cfg:
            kwargs["temperature"] = cfg["temperature"]
        if "reasoning_effort" in cfg:
            kwargs["reasoning_effort"] = cfg["reasoning_effort"]
        if stream:
            kwargs["stream_options"] = {"include_usage": True}  # final chunk carries token counts
        return kwargs

    async def _complete(self, task: str, kwargs: dict[str, Any]) -> Any:
        """acompletion, waiting out rate limits the way the provider asks (LiteLLM retries them immediately)."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                with trace_llm(task, kwargs["model"]):
                    return await acompletion(**kwargs)
            except Exception as e:
                wait = rate_limit_wait_s(e)
                if wait is None or attempt == RATE_LIMIT_RETRIES:
                    raise
                logger.warning("%s rate-limited; retrying in %.1fs", task, wait)
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")

    async def chat(self, task: str, messages: list[dict], stream: bool = False, prompt_version: str | None = None) -> Any:
        kwargs = self._kwargs(task, messages, stream)
        start = time.perf_counter()
        try:
            resp = await self._complete(task, kwargs)
        except Exception as e:
            self._record(task, None, start, prompt_version, error=e)
            raise
        if stream:
            return self._recorded_stream(task, resp, start, prompt_version)
        self._record(task, resp, start, prompt_version)
        return resp

    async def structured(
        self, task: str, messages: list[dict], response_model: type[T], prompt_version: str | None = None
    ) -> T:
        """JSON call validated by a Pydantic model; on failure retry once with the error appended."""
        kwargs = self._kwargs(task, messages, stream=False)
        kwargs["response_format"] = response_format_for(response_model)  # strict schema, cleaned per provider rules
        for attempt in range(2):
            start = time.perf_counter()
            try:
                resp = await self._complete(task, kwargs)
            except Exception as e:
                schema_miss = "json_validate_failed" in str(e)  # provider checked the output (e.g. Groq) and rejected it
                self._record(task, None, start, prompt_version, error=e, json_valid=False if schema_miss else None)
                if not schema_miss or attempt == 1:
                    raise
                kwargs["messages"] = [
                    *messages,
                    {"role": "user", "content": f"Your previous JSON didn't match the schema: {describe(e, 400)}\n"
                                                "Return JSON that includes every required field."},
                ]
                continue
            content = resp.choices[0].message.content
            try:
                result = response_model.model_validate_json(content)
            except ValidationError as e:
                self._record(task, resp, start, prompt_version, json_valid=False)
                if attempt == 1:
                    raise
                kwargs["messages"] = [
                    *messages,
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"Your JSON was invalid:\n{e}\nReturn corrected JSON only."},
                ]
                continue
            self._record(task, resp, start, prompt_version, json_valid=True)
            return result
        raise AssertionError("unreachable")

    async def _recorded_stream(self, task: str, stream: Any, start: float, prompt_version: str | None) -> AsyncIterator:
        ttft = None
        last_with_usage = None
        error: Exception | None = None
        try:
            async for chunk in stream:
                if ttft is None and chunk.choices and chunk.choices[0].delta.content:
                    ttft = (time.perf_counter() - start) * 1000
                if getattr(chunk, "usage", None):
                    last_with_usage = chunk
                yield chunk
        except Exception as e:
            error = e
            raise
        finally:
            self._record(task, last_with_usage, start, prompt_version, ttft_ms=ttft, error=error,
                         model_hint=getattr(last_with_usage, "model", None))

    def _record(
        self, task: str, resp: Any, start: float, prompt_version: str | None, *, json_valid: bool | None = None,
        ttft_ms: float | None = None, error: Exception | None = None, model_hint: str | None = None,
    ) -> None:
        if self.recorder is None:
            return
        cfg = self.models[task]
        input_tokens, output_tokens = tokens_of(resp)
        self.recorder(LLMCallRecord(
            task=task, configured_model=cfg["model"],
            model=model_hint or getattr(resp, "model", None) or cfg["model"],
            prompt_version=prompt_version, input_tokens=input_tokens, output_tokens=output_tokens,
            latency_ms=round((time.perf_counter() - start) * 1000, 1), ttft_ms=ttft_ms and round(ttft_ms, 1),
            cost_usd=cost_of(cfg, resp, input_tokens, output_tokens) if resp is not None else None,
            success=error is None and json_valid is not False, json_valid=json_valid,
            error=describe(error, 100) if error else None, session_id=current_session_id.get(),
        ))
