import asyncio

import pytest

from app.config import load_rubric
from app.llm.schemas import DimensionScore, EvaluationDraft
from app.services.evaluator import BackgroundEvaluator, apply_rubric, evaluate_answer, quote_is_verified

RUBRIC = load_rubric()["technical"]
ANSWER = "I chose 512-token chunks with 50 tokens of overlap because recall@5 was highest on our eval set."
QUESTION = {"id": "q1", "text": "How did you pick a chunk size?", "ideal_key_points": ["recall", "overlap"]}
TURNS = [
    {"speaker": "interviewer", "text": QUESTION["text"], "question_id": "q1", "at_s": 0},
    {"speaker": "candidate", "text": ANSWER, "question_id": "q1", "at_s": 5},
    {"speaker": "interviewer", "text": "What is RAG?", "question_id": "q2", "at_s": 30},
    {"speaker": "candidate", "text": "Retrieval augmented generation.", "question_id": "q2", "at_s": 35},
]


def draft(scores: dict, evidence: dict) -> EvaluationDraft:
    dims = [DimensionScore(dimension=d, score=s, evidence=evidence.get(d, "")) for d, s in scores.items()]
    return EvaluationDraft(dimension_scores=dims, strengths=["s1", "s2", "s3"], improvements=["i1"])


@pytest.mark.parametrize(
    ("quote", "ok"),
    [
        ("512-token chunks with 50 tokens of overlap", True),
        ("I CHOSE 512 token chunks, with 50 tokens of overlap", True),  # case/punctuation
        ("chose 512-token chunks with 50 token overlap because", True),  # near-verbatim (>= 85% of words)
        ("I benchmarked HNSW against IVF on a million vectors", False),  # invented
        ("recall", True),
        ("", False),
    ],
)
def test_quote_verification(quote, ok):
    assert quote_is_verified(quote, ANSWER) is ok


def test_apply_rubric_enforces_evidence_and_computes_overall():
    ev = apply_rubric(
        "q1",
        draft(
            scores={"correctness": 5, "depth": 4, "specificity": 7, "structure": 3, "made_up_dim": 5},
            evidence={
                "correctness": "512-token chunks with 50 tokens of overlap",
                "depth": "we compared five chunking strategies",  # not said -> capped at 2
                "specificity": "recall@5 was highest on our eval set",
                "structure": "",  # no evidence -> capped at 2
            },
        ),
        RUBRIC,
        ANSWER,
    )
    assert ev.scores == {"correctness": 5, "depth": 2, "specificity": 5, "structure": 2, "communication": 1}
    assert ev.evidence["depth"] == "" and ev.evidence["correctness"]
    assert ev.overall == pytest.approx(5 * 0.35 + 2 * 0.25 + 5 * 0.15 + 2 * 0.10 + 1 * 0.15)
    assert ev.strengths == ["s1", "s2"]


class FakeLLM:
    def __init__(self, result=None, gate: asyncio.Event | None = None):
        self.result = result
        self.gate = gate
        self.prompts: list[str] = []

    async def structured(self, task, messages, response_model, **kwargs):
        assert task == "evaluator"
        self.prompts.append(messages[-1]["content"])
        if self.gate:
            await self.gate.wait()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_evaluate_answer_uses_only_that_questions_turns():
    llm = FakeLLM(draft({"correctness": 4}, {"correctness": "512-token chunks"}))
    ev = await evaluate_answer(llm, QUESTION, TURNS, "technical")
    prompt = llm.prompts[0]
    assert "Candidate: " + ANSWER in prompt
    assert "Retrieval augmented generation" not in prompt
    assert "- correctness (weight 35%)" in prompt
    assert ev.scores["correctness"] == 4


async def test_unanswered_question_scores_minimum_without_llm():
    llm = FakeLLM()
    ev = await evaluate_answer(llm, QUESTION, TURNS[:1], "technical")
    assert set(ev.scores.values()) == {1} and ev.overall == 1.0
    assert llm.prompts == []


async def test_background_evaluator_does_not_block_and_dedupes():
    gate = asyncio.Event()
    llm = FakeLLM(draft({"correctness": 3}, {}), gate)
    bg = BackgroundEvaluator(llm, "technical")
    bg.submit(QUESTION, TURNS)  # returns immediately although the LLM is still "thinking"
    bg.submit(QUESTION, TURNS)
    await asyncio.sleep(0)
    assert len(llm.prompts) == 1
    gate.set()
    results = await bg.results()
    assert results["q1"].scores["correctness"] == 2  # no evidence -> capped


async def test_background_evaluator_failure_is_none():
    bg = BackgroundEvaluator(FakeLLM(RuntimeError("provider down")), "technical")
    bg.submit(QUESTION, TURNS)
    assert await bg.results() == {"q1": None}
