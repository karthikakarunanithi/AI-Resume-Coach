"""Final report (plan 10.2): numbers are computed in code; the coach LLM writes the narrative."""

import json
import logging
from datetime import UTC, datetime

from pydantic import BaseModel

from app.llm.client import LLMClient
from app.llm.schemas import AnswerEvaluation, CandidateProfile, CoachNarrative, PracticeDay
from app.prompts import render_prompt
from app.services.evaluator import question_turns
from app.voice.speech_metrics import SpeechSummary

logger = logging.getLogger("coach.report")

COACH_PROMPT = "coach_v1"
HIRING_SIGNALS = [(80, "Strong"), (65, "Lean yes"), (45, "Lean no"), (0, "Not yet")]
ANSWER_CHARS_FOR_COACH = 800


class TranscriptLine(BaseModel):
    speaker: str
    text: str


class QuestionReport(BaseModel):
    question_id: str
    text: str
    topic: str
    transcript: list[TranscriptLine]
    evaluated: bool
    scores: dict[str, int] = {}
    evidence: dict[str, str] = {}
    strengths: list[str] = []
    improvements: list[str] = []
    missed_key_points: list[str] = []
    score: int | None = None  # 0-100
    sample_answer: str | None = None


class FinalReport(BaseModel):
    session_id: str
    role: str
    interview_type: str
    difficulty: str
    generated_at: datetime
    overall_score: int  # 0-100
    hiring_signal: str
    questions_planned: int
    questions_answered: int
    questions_scored: int = -1  # -1: report from before this field existed (then read the question scores)
    dimension_scores: dict[str, float]  # rubric dimension -> average 1-5, for the radar chart
    summary: str
    strengths: list[str]
    improvements: list[str]
    practice_plan: list[PracticeDay]
    questions: list[QuestionReport]
    speech: SpeechSummary | None = None  # voice interviews only
    coach_generated: bool  # False if the coach LLM failed and the narrative is a fallback


def is_scored(report: dict) -> bool:
    """False when answers exist but none could be scored: that must not show up as a score of 0."""
    if report.get("questions_answered", 0) == 0:
        return False
    if report.get("questions_scored", -1) >= 0:
        return report["questions_scored"] > 0
    return any(q.get("score") is not None for q in report.get("questions", []))


def to_100(overall_1_to_5: float) -> int:
    return round((overall_1_to_5 - 1) / 4 * 100)


def hiring_signal(score: int) -> str:
    return next(label for threshold, label in HIRING_SIGNALS if score >= threshold)


async def build_report(
    llm: LLMClient, state: dict, evaluations: dict[str, AnswerEvaluation | None], speech: SpeechSummary | None = None
) -> FinalReport:
    cfg = state["config"]
    asked = [q for q in state["plan"] if q["id"] in state.get("finished_questions", [])]
    scored = [e for q in asked if (e := evaluations.get(q["id"]))]

    overall = to_100(sum(e.overall for e in scored) / len(scored)) if scored else 0
    dims = {d: round(sum(e.scores[d] for e in scored) / len(scored), 2) for d in scored[0].scores} if scored else {}

    questions = [_question_report(q, state["turns"], evaluations.get(q["id"])) for q in asked]
    report = FinalReport(
        session_id=state["session_id"], role=cfg["role"], interview_type=cfg["interview_type"],
        difficulty=cfg["difficulty"], generated_at=datetime.now(UTC), overall_score=overall,
        hiring_signal=hiring_signal(overall), questions_planned=len(state["plan"]), questions_answered=len(asked),
        questions_scored=len(scored),
        dimension_scores=dims, questions=questions, coach_generated=False, speech=speech,
        **_fallback_narrative(scored, overall, len(asked)),
    )
    if not scored:
        return report

    try:
        narrative = await _coach(llm, state, report, scored)
    except Exception:
        logger.exception("Coach LLM failed; using fallback narrative")
        return report

    samples = {s.question_id: s.answer for s in narrative.sample_answers}
    for q in report.questions:
        q.sample_answer = samples.get(q.question_id)
    report.summary = narrative.summary
    report.strengths, report.improvements = narrative.strengths[:3], narrative.improvements[:3]
    report.practice_plan = sorted(narrative.practice_plan, key=lambda d: d.day)[:7]
    report.coach_generated = True
    return report


async def _coach(llm: LLMClient, state: dict, report: FinalReport, scored: list[AnswerEvaluation]) -> CoachNarrative:
    by_id = {q.question_id: q for q in report.questions}
    weakest_first = sorted(scored, key=lambda e: e.overall)
    evaluations_json = json.dumps([
        {
            "question_id": e.question_id, "question": by_id[e.question_id].text, "score_100": to_100(e.overall),
            "candidate_answer": " ".join(
                t.text for t in by_id[e.question_id].transcript if t.speaker == "candidate"
            )[:ANSWER_CHARS_FOR_COACH],
            "scores": e.scores, "missed_key_points": e.missed_key_points,
            "strengths": e.strengths, "improvements": e.improvements,
        }
        for e in weakest_first
    ])
    prompt = render_prompt(
        COACH_PROMPT,
        interview_type=report.interview_type, role=report.role, difficulty=report.difficulty,
        overall_score=report.overall_score, hiring_signal=report.hiring_signal,
        dimension_scores=json.dumps(report.dimension_scores), answered=report.questions_answered,
        planned=report.questions_planned,
        profile_summary=CandidateProfile.model_validate(state.get("profile") or {}).summary(),
        evaluations_json=evaluations_json, speech_summary=_speech_for_coach(report.speech),
    )
    return await llm.structured("coach", [{"role": "user", "content": prompt}], CoachNarrative, prompt_version=COACH_PROMPT)


def _speech_for_coach(speech: SpeechSummary | None) -> str:
    if speech is None:
        return "Not recorded (text interview)."
    return json.dumps({
        "avg_wpm": speech.avg_wpm, "pace": speech.pace, "fillers_per_100_words": speech.fillers_per_100_words,
        "filler_counts": speech.filler_counts, "hedges": speech.hedges, "long_pauses": speech.long_pauses,
        "flags": speech.flags,
    })


def _question_report(question: dict, turns: list[dict], evaluation: AnswerEvaluation | None) -> QuestionReport:
    base = QuestionReport(
        question_id=question["id"], text=question["text"], topic=question["topic"],
        transcript=[TranscriptLine(speaker=t["speaker"], text=t["text"]) for t in question_turns(turns, question["id"])],
        evaluated=evaluation is not None,
    )
    if evaluation:
        base = base.model_copy(update={
            "scores": evaluation.scores, "evidence": evaluation.evidence, "strengths": evaluation.strengths,
            "improvements": evaluation.improvements, "missed_key_points": evaluation.missed_key_points,
            "score": to_100(evaluation.overall),
        })
    return base


def _fallback_narrative(scored: list[AnswerEvaluation], overall: int, answered: int = 0) -> dict:
    if not scored and answered:
        return {
            "summary": "Your answers were saved, but they couldn't be scored this time because the AI provider was "
                       "busy. Please try another interview in a few minutes.",
            "strengths": [], "improvements": [], "practice_plan": [],
        }
    if not scored:
        return {
            "summary": "The interview ended before any answer could be scored. Try a full session to get feedback.",
            "strengths": [], "improvements": [], "practice_plan": [],
        }
    best_first = sorted(scored, key=lambda e: e.overall, reverse=True)
    return {
        "summary": f"You scored {overall}/100 across {len(scored)} answered questions.",
        "strengths": [s for e in best_first for s in e.strengths][:3],
        "improvements": [s for e in reversed(best_first) for s in e.improvements][:3],
        "practice_plan": [],
    }
