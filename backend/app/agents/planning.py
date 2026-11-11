"""Turns interview settings into retrieval filters and a validated question plan."""

from typing import Protocol

from app.agents.state import InterviewConfig
from app.llm.schemas import PlannedQuestion, QuestionDraft
from app.rag.retriever import QuestionFilters, RetrievalQuery, RetrievedQuestion

DIFFICULTY_RANGE = {"easy": (1, 3), "medium": (2, 4), "hard": (3, 5)}
ALL_TECH_TRACKS = ["genai", "ml", "backend", "data"]

# Matched in order against the lowercased role name
ROLE_TRACKS: list[tuple[tuple[str, ...], list[str]]] = [
    (("genai", "llm", "prompt", "ai engineer", "ai developer"), ["genai", "ml", "backend"]),
    (("data scien", "data analyst", "analytics"), ["data", "ml"]),
    (("machine learning", "ml ", "ml engineer", "deep learning", "computer vision", "nlp"), ["ml", "data", "genai"]),
    (("backend", "python developer", "software engineer", "sde", "api"), ["backend", "data"]),
]

MIX = {
    "technical": "about 40% resume deep-dive, 40% job-description skills, 20% fundamentals from the bank",
    "system_design": "mostly design problems from the bank, adapted to the candidate's domain; "
    "at least one should build on a system from the candidate's resume",
    "behavioral": "about 60% behavioral questions from the bank and 40% about specific situations "
    "in the candidate's own projects or jobs (STAR-style)",
    "hr": "HR questions from the bank, personalized with the candidate's background where natural",
}


class QuestionRetriever(Protocol):
    async def search(
        self, query: RetrievalQuery, filters: QuestionFilters | None = None, k: int = 20
    ) -> list[RetrievedQuestion]: ...


def tracks_for_role(role: str) -> list[str]:
    name = f"{role.lower()} "
    for needles, tracks in ROLE_TRACKS:
        if any(n in name for n in needles):
            return tracks
    return ALL_TECH_TRACKS


def filters_for(cfg: InterviewConfig) -> QuestionFilters:
    lo, hi = DIFFICULTY_RANGE[cfg["difficulty"]]
    kind = cfg["interview_type"]
    if kind in ("behavioral", "hr"):
        return QuestionFilters(roles=["general"], types=[kind], min_difficulty=lo, max_difficulty=hi)
    return QuestionFilters(roles=tracks_for_role(cfg["role"]), types=[kind], min_difficulty=lo, max_difficulty=hi)


def num_questions(duration_min: int) -> int:
    """Roughly 3 minutes per question including follow-ups; plan 6.2 asks for 6-10 in a full interview."""
    return max(3, min(10, round(duration_min / 3)))


def finalize_plan(questions: list[QuestionDraft], limit: int) -> list[dict]:
    """Trim to the requested size and assign stable ids q1..qn."""
    fields = QuestionDraft.model_fields
    return [
        PlannedQuestion(id=f"q{i}", **q.model_dump(include=set(fields))).model_dump()
        for i, q in enumerate(questions[:limit], start=1)
    ]


def plan_from_bank(bank: list[RetrievedQuestion], limit: int) -> list[dict]:
    """Fallback plan when the planner LLM fails: top retrieved questions, easiest first."""
    picked = sorted(bank[:limit], key=lambda q: q.difficulty)
    return finalize_plan(
        [
            QuestionDraft(
                text=q.text, topic=q.topic, difficulty=q.difficulty, source="bank", ideal_key_points=q.ideal_key_points
            )
            for q in picked
        ],
        limit,
    )
