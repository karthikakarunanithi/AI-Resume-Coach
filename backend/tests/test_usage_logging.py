from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.db.models import LLMCall
from app.llm import client as client_mod
from app.llm.call_log import LLMCallLogger
from app.llm.client import LLMClient
from app.llm.schemas import InterviewerAction
from app.llm.usage import current_session_id

MODELS = {
    "evaluator": {"model": "anthropic/claude-sonnet-5-5", "temperature": 0, "max_tokens": 100,
                  "input_usd_per_mtok": 3.0, "output_usd_per_mtok": 15.0},
    "interviewer": {"model": "groq/llama-3.3-70b-versatile", "temperature": 0.6, "max_tokens": 100},
}
VALID = '{"action": "next_question", "spoken_text": "Next.", "reason": "r"}'


def resp(content: str, model: str = "claude-sonnet-5-5", tokens=(1000, 200)):
    return SimpleNamespace(
        model=model, choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=tokens[0], completion_tokens=tokens[1]),
    )


def chunk(text: str | None, usage=None, model="groq/llama"):
    choices = [SimpleNamespace(delta=SimpleNamespace(content=text))] if text is not None else []
    return SimpleNamespace(choices=choices, usage=usage, model=model)


@pytest.fixture
def records():
    return []


async def test_structured_records_each_attempt_with_cost(monkeypatch, records):
    replies = iter([resp("not json"), resp(VALID)])

    async def fake(**kwargs):
        return next(replies)

    monkeypatch.setattr(client_mod, "acompletion", fake)
    llm = LLMClient(MODELS, recorder=records.append)
    token = current_session_id.set("8f7e6d5c-0000-0000-0000-000000000001")
    try:
        await llm.structured("evaluator", [{"role": "user", "content": "x"}], InterviewerAction, prompt_version="evaluator_v1")
    finally:
        current_session_id.reset(token)

    assert [(r.json_valid, r.success) for r in records] == [(False, False), (True, True)]
    r = records[-1]
    assert (r.task, r.prompt_version, r.input_tokens, r.output_tokens) == ("evaluator", "evaluator_v1", 1000, 200)
    assert r.cost_usd == pytest.approx((1000 * 3 + 200 * 15) / 1e6)
    assert r.session_id.endswith("0001")


async def test_streaming_records_ttft_usage_and_fallback(monkeypatch, records):
    async def stream():
        yield chunk("ACTION next_question q2\n")
        yield chunk("Next question?")
        yield chunk(None, usage=SimpleNamespace(prompt_tokens=800, completion_tokens=20), model="anthropic/claude-haiku-5-5")

    async def fake(**kwargs):
        assert kwargs["stream_options"] == {"include_usage": True}
        return stream()

    monkeypatch.setattr(client_mod, "acompletion", fake)
    llm = LLMClient(MODELS, recorder=records.append)
    out = [c async for c in await llm.chat("interviewer", [], stream=True, prompt_version="interviewer_v2")]

    assert len(out) == 3 and len(records) == 1
    r = records[0]
    assert r.ttft_ms is not None and r.ttft_ms <= r.latency_ms
    assert (r.input_tokens, r.output_tokens) == (800, 20)
    assert r.configured_model == "groq/llama-3.3-70b-versatile" and r.model == "anthropic/claude-haiku-5-5"  # fallback


async def test_failed_call_is_recorded(monkeypatch, records):
    async def fake(**kwargs):
        raise TimeoutError("slow provider")

    monkeypatch.setattr(client_mod, "acompletion", fake)
    with pytest.raises(TimeoutError):
        await LLMClient(MODELS, recorder=records.append).chat("evaluator", [])
    assert (records[0].success, records[0].error, records[0].cost_usd) == (False, "TimeoutError: slow provider", None)


async def test_call_logger_writes_rows(db_sessionmaker, records, monkeypatch):
    async def fake(**kwargs):
        return resp(VALID)

    monkeypatch.setattr(client_mod, "acompletion", fake)
    logger = LLMCallLogger(db_sessionmaker)
    llm = LLMClient(MODELS, recorder=logger.record)
    for _ in range(3):
        await llm.structured("evaluator", [], InterviewerAction)
    await logger.flush()

    async with db_sessionmaker() as db:
        rows = list(await db.scalars(select(LLMCall)))
    assert len(rows) == 3
    assert all(r.task == "evaluator" and r.json_valid and float(r.cost_usd) > 0 for r in rows)
