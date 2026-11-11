"""Answer evaluation (plan 5.3.9, 10, 16): the LLM proposes scores with evidence; code enforces the rules."""

import asyncio
import logging
import re
from typing import Any

from app.config import load_rubric
from app.llm.client import LLMClient
from app.llm.schemas import AnswerEvaluation, EvaluationDraft
from app.prompts import render_prompt

logger = logging.getLogger("coach.evaluator")

EVALUATOR_PROMPT = "evaluator_v1"
MAX_SCORE_WITHOUT_EVIDENCE = 2
QUOTE_WORD_OVERLAP = 0.85  # tolerate small transcription/ellipsis differences in quotes

Rubric = dict[str, dict[str, Any]]  # dimension -> {weight, description}


def question_turns(turns: list[dict], question_id: str) -> list[dict]:
    return [t for t in turns if t["question_id"] == question_id]


def _norm_words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).split()


def quote_is_verified(quote: str, candidate_text: str) -> bool:
    """True if the quote really comes from the candidate (stops the LLM inventing evidence)."""
    words = _norm_words(quote)
    if not words:
        return False
    answer = _norm_words(candidate_text)
    if " ".join(words) in " ".join(answer):
        return True
    answer_vocab = set(answer)
    return len(words) >= 4 and sum(w in answer_vocab for w in words) / len(words) >= QUOTE_WORD_OVERLAP


def apply_rubric(question_id: str, draft: EvaluationDraft, rubric: Rubric, candidate_text: str) -> AnswerEvaluation:
    by_dim = {d.dimension.strip().lower(): d for d in draft.dimension_scores}
    scores: dict[str, int] = {}
    evidence: dict[str, str] = {}
    for dim in rubric:
        given = by_dim.get(dim)  # a dimension the model skipped scores the minimum
        score = min(5, max(1, given.score)) if given else 1
        quote = given.evidence.strip() if given else ""
        if not quote_is_verified(quote, candidate_text):
            if quote:
                logger.info("Unverified evidence for %s/%s dropped: %r", question_id, dim, quote)
            quote = ""
            score = min(score, MAX_SCORE_WITHOUT_EVIDENCE)
        scores[dim], evidence[dim] = score, quote
    overall = sum(scores[d] * rubric[d]["weight"] for d in rubric)
    return AnswerEvaluation(
        question_id=question_id, scores=scores, evidence=evidence,
        strengths=draft.strengths[:2], improvements=draft.improvements[:2],
        missed_key_points=draft.missed_key_points, overall=round(overall, 2),
    )


def no_answer_evaluation(question_id: str, rubric: Rubric) -> AnswerEvaluation:
    return AnswerEvaluation(
        question_id=question_id, scores=dict.fromkeys(rubric, 1), evidence=dict.fromkeys(rubric, ""),
        strengths=[], improvements=["No answer was given. Even a partial answer that explains your reasoning scores higher."],
        missed_key_points=[], overall=1.0,
    )


def _format_rubric(rubric: Rubric) -> str:
    return "\n".join(f"- {dim} (weight {d['weight']:.0%}): {d['description']}" for dim, d in rubric.items())


async def evaluate_answer(
    llm: LLMClient, question: dict, turns: list[dict], interview_type: str, rubric: Rubric | None = None
) -> AnswerEvaluation:
    rubric = rubric or load_rubric()[interview_type]
    qa = question_turns(turns, question["id"])
    candidate_text = " ".join(t["text"] for t in qa if t["speaker"] == "candidate")
    if not candidate_text.strip():
        return no_answer_evaluation(question["id"], rubric)

    prompt = render_prompt(
        EVALUATOR_PROMPT,
        interview_type=interview_type, question=question["text"],
        key_points="; ".join(question["ideal_key_points"]),
        qa_transcript="\n".join(f"{t['speaker'].capitalize()}: {t['text']}" for t in qa),
        rubric=_format_rubric(rubric),
    )
    draft = await llm.structured(
        "evaluator", [{"role": "user", "content": prompt}], EvaluationDraft, prompt_version=EVALUATOR_PROMPT
    )
    return apply_rubric(question["id"], draft, rubric, candidate_text)


class BackgroundEvaluator:
    """Scores each finished question in a background task so the conversation never waits (plan 3.1 step 6)."""

    def __init__(self, llm: LLMClient, interview_type: str):
        self.llm = llm
        self.interview_type = interview_type
        self._tasks: dict[str, asyncio.Task[AnswerEvaluation | None]] = {}

    def submit(self, question: dict, turns: list[dict]) -> None:
        if question["id"] not in self._tasks:
            self._tasks[question["id"]] = asyncio.create_task(self._run(question, list(turns)))

    async def _run(self, question: dict, turns: list[dict]) -> AnswerEvaluation | None:
        try:
            return await evaluate_answer(self.llm, question, turns, self.interview_type)
        except Exception:
            logger.exception("Evaluation failed for %s", question["id"])
            return None

    async def results(self) -> dict[str, AnswerEvaluation | None]:
        """Wait for every submitted evaluation; None marks one that failed."""
        done = await asyncio.gather(*self._tasks.values())
        return dict(zip(self._tasks, done, strict=True))

    async def retry_failed(
        self, results: dict[str, AnswerEvaluation | None], questions: dict[str, dict], turns: list[dict],
        wait_s: float = 30.0, rounds: int = 2,
    ) -> dict[str, AnswerEvaluation | None]:
        """Re-score answers whose evaluation failed (usually a provider rate limit, which clears within a
        minute or two), one at a time, so a busy provider doesn't leave the report unscored."""
        for _ in range(rounds):
            failed = [qid for qid, e in results.items() if e is None and qid in questions]
            if not failed:
                break
            await asyncio.sleep(wait_s)
            for qid in failed:
                results[qid] = await self._run(questions[qid], turns)
        return results
