"""Evaluation cases: one answered interview question, optional human ratings, optional expectations.

Stored as JSONL (one case per line) so ratings can be added incrementally and diffs stay readable.
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.config import load_rubric

DATASETS = Path(__file__).parent / "datasets"
ROBUSTNESS = DATASETS / "robustness.jsonl"
ANSWERS = DATASETS / "answers.jsonl"  # exported real answers + human ratings (personal data: gitignored)


class Line(BaseModel):
    speaker: Literal["interviewer", "candidate"]
    text: str


class Expect(BaseModel):
    """Bounds for cases without human ratings (robustness): checked against the evaluator's output."""

    max_overall: float | None = None
    min_overall: float | None = None
    max_scores: dict[str, int] = Field(default_factory=dict)
    same_as: str | None = None  # id of a case whose overall this one must match (e.g. padded copy)
    tolerance: float = 0.5


class EvalCase(BaseModel):
    id: str
    source: Literal["robustness", "interview"]
    interview_type: Literal["technical", "behavioral", "hr", "system_design"]
    question: str
    ideal_key_points: list[str]
    transcript: list[Line]
    ratings: dict[str, dict[str, int]] = Field(default_factory=dict)  # rater -> dimension -> 1..5
    expect: Expect | None = None
    notes: str = ""

    def turns(self) -> list[dict]:
        """In the shape evaluate_answer expects."""
        return [{"speaker": t.speaker, "text": t.text, "question_id": self.id, "at_s": 0.0} for t in self.transcript]

    def question_dict(self) -> dict:
        return {"id": self.id, "text": self.question, "ideal_key_points": self.ideal_key_points}

    def human_overall(self, rater: str) -> float:
        rubric = load_rubric()[self.interview_type]
        scores = self.ratings[rater]
        return sum(scores[d] * rubric[d]["weight"] for d in rubric)

    def human_mean_overall(self) -> float | None:
        if not self.ratings:
            return None
        return sum(self.human_overall(r) for r in self.ratings) / len(self.ratings)


def load_cases(path: Path) -> list[EvalCase]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [EvalCase.model_validate_json(line) for line in f if line.strip()]


def save_cases(path: Path, cases: list[EvalCase]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(c.model_dump(exclude_defaults=True), ensure_ascii=False) + "\n" for c in cases)
    tmp.replace(path)  # atomic: a crash mid-rating never corrupts the file
