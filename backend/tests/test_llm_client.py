from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.config import load_models
from app.llm import client as client_mod
from app.llm.client import LLMClient
from app.llm.schemas import InterviewerAction

VALID = '{"action": "next_question", "spoken_text": "Tell me about FastAPI.", "reason": "start"}'


def _resp(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def test_models_yaml_has_all_tasks():
    models = load_models()
    for task in ["resume_parser", "jd_analyzer", "planner", "interviewer", "evaluator", "coach", "guardrail"]:
        assert {"model", "max_tokens"} <= models[task].keys()


def test_claude_tasks_send_no_sampling_parameters():
    """Current Claude models return 400 for any non-default temperature/top_p/top_k."""
    for task, cfg in load_models().items():
        if str(cfg.get("model", "")).startswith("anthropic/"):
            assert not {"temperature", "top_p", "top_k"} & cfg.keys(), task


def test_no_fallback_to_a_local_server_by_default():
    """An unreachable fallback (e.g. Ollama not running) turns a 3 s failure into a 60 s one."""
    for task, cfg in load_models().items():
        assert not any(f.startswith("ollama/") for f in cfg.get("fallbacks", [])), task


def test_request_omits_temperature_unless_configured():
    llm = LLMClient({"a": {"model": "anthropic/claude-haiku-5-5", "max_tokens": 10},
                     "b": {"model": "groq/x", "max_tokens": 10, "temperature": 0.6, "reasoning_effort": "low"}})
    assert "temperature" not in llm._kwargs("a", [], stream=False)
    kw = llm._kwargs("b", [], stream=False)
    assert (kw["temperature"], kw["reasoning_effort"]) == (0.6, "low")


async def test_structured_retries_once_on_invalid_json(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return _resp("not json" if len(calls) == 1 else VALID)

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    result = await LLMClient().structured("interviewer", [{"role": "user", "content": "hi"}], InterviewerAction)

    assert result.action == "next_question"
    assert len(calls) == 2
    assert "invalid" in calls[1]["messages"][-1]["content"]


async def test_structured_raises_after_second_failure(monkeypatch):
    async def fake_acompletion(**kwargs):
        return _resp("still not json")

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    with pytest.raises(ValidationError):
        await LLMClient().structured("evaluator", [{"role": "user", "content": "hi"}], InterviewerAction)


@pytest.mark.parametrize(
    "model_name", ["CandidateProfile", "JDAnalysis", "InterviewPlan", "EvaluationDraft", "CoachNarrative", "InterviewerAction"]
)
def test_structured_output_schemas_meet_claude_rules(model_name):
    """Every object closed with additionalProperties: false; no numeric/length/array-size constraints."""
    from app.llm import schemas
    from app.llm.json_schema import UNSUPPORTED_KEYWORDS, structured_output_schema

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "object" or "properties" in node:
                assert node.get("additionalProperties") is False, node.get("title")
                # strict mode on OpenAI-compatible providers (OpenAI, Groq): every property listed as required
                assert set(node.get("required", [])) == set(node.get("properties", {})), node.get("title")
            assert not UNSUPPORTED_KEYWORDS & node.keys(), node
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(structured_output_schema(getattr(schemas, model_name)))


def test_constraints_still_enforced_on_the_reply():
    from pydantic import ValidationError

    from app.llm.schemas import InterviewPlan

    bad = '{"questions": [{"text": "Q?", "topic": "rag", "difficulty": 9, "source": "bank", "ideal_key_points": ["kp"]}]}'
    with pytest.raises(ValidationError):
        InterviewPlan.model_validate_json(bad)


def test_open_ended_maps_are_refused():
    from pydantic import BaseModel

    from app.llm.json_schema import structured_output_schema

    class Bad(BaseModel):
        scores: dict[str, int]

    with pytest.raises(ValueError, match="Open-ended maps"):
        structured_output_schema(Bad)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ('AnthropicException - {"error":{"message":"Your credit balance is too low to access the Anthropic API."}}', "no credit"),
        ("invalid x-api-key", "rejected the API key"),
        ("The model `groq/llama-3.3-70b-versatile` does not exist", "isn't available"),
        ("connection reset", "please try again"),
    ],
)
def test_user_message_explains_provider_failures(message, expected):
    from app.llm.errors import user_message

    assert expected in user_message(RuntimeError(message), "Resume parsing")


@pytest.mark.parametrize(
    ("message", "wait"),
    [
        ("Rate limit reached for model `qwen`. Please try again in 12.34s. Need more tokens?", 12.84),
        ("Rate limit reached ... Please try again in 850ms.", 1.35),
        ("Rate limit reached ... Please try again in 1m2.5s.", 30.0),  # capped
        ("Rate limit reached, slow down", 5.0),
        ("Some other failure", None),
    ],
)
def test_rate_limit_wait(message, wait):
    from app.llm.client import rate_limit_wait_s

    assert rate_limit_wait_s(RuntimeError(message)) == (pytest.approx(wait) if wait else None)


async def test_rate_limited_call_waits_and_retries(monkeypatch):
    import asyncio

    calls, slept = [], []

    async def fake_acompletion(**kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("Rate limit reached for model. Please try again in 2s.")
        return _resp(VALID)

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    result = await LLMClient().structured("interviewer", [{"role": "user", "content": "hi"}], InterviewerAction)
    assert result.action == "next_question" and slept == [2.5] and len(calls) == 2


@pytest.mark.parametrize("profile", ["models.yaml", "models.free.yaml"])
def test_every_profile_configures_every_task(profile):
    from app.config import ROOT_DIR

    models = load_models.__wrapped__(ROOT_DIR / "config" / profile)
    tasks = {"resume_parser", "jd_analyzer", "planner", "interviewer", "evaluator", "coach", "guardrail", "summarizer"}
    assert tasks <= models.keys() and {"embeddings", "stt", "tts"} <= models.keys()
    assert not any(k.startswith("_") for k in models)
    if profile == "models.free.yaml":
        assert all(models[t]["model"].startswith("groq/") for t in tasks)  # one free key covers everything
        assert all(models[t]["input_usd_per_mtok"] == 0 for t in tasks)


async def test_provider_schema_rejection_is_retried_with_the_error(monkeypatch):
    calls = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RuntimeError('{"error":{"message":"Generated JSON does not match the expected schema: missing properties: \'reason\'","code":"json_validate_failed"}}')
        return _resp(VALID)

    records = []
    monkeypatch.setattr(client_mod, "acompletion", fake_acompletion)
    result = await LLMClient(recorder=records.append).structured("interviewer", [{"role": "user", "content": "hi"}], InterviewerAction)
    assert result.action == "next_question" and len(calls) == 2
    assert "missing properties" in calls[1]["messages"][-1]["content"]
    assert [r.json_valid for r in records] == [False, True]


def test_planner_schema_never_asks_the_model_for_ids():
    from app.llm.json_schema import structured_output_schema
    from app.llm.schemas import InterviewPlan

    assert '"id"' not in str(structured_output_schema(InterviewPlan)).replace("'", '"')
