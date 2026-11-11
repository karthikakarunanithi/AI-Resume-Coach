import csv
import re
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import ROOT_DIR

QUESTION_BANK_CSV = ROOT_DIR / "data" / "question_bank.csv"
KEY_POINT_SEP = " | "
# Stable namespace so the same question text always maps to the same id (idempotent re-ingest)
_NAMESPACE = uuid.UUID("6f1c2a9e-7b1d-4c55-9a43-2f6f0f5b8d11")

Track = Literal["genai", "ml", "backend", "data", "general"]
QuestionType = Literal["technical", "behavioral", "hr", "system_design"]


class QuestionRow(BaseModel):
    text: str = Field(min_length=10)
    role: Track  # the bank "track"; an interview for a job role draws from several tracks
    topic: str = Field(pattern=r"^[a-z0-9_]+$")
    type: QuestionType
    difficulty: int = Field(ge=1, le=5)
    ideal_key_points: list[str] = Field(min_length=2, max_length=6)

    @field_validator("ideal_key_points", mode="before")
    @classmethod
    def _split_points(cls, v: object) -> object:
        if isinstance(v, str):
            return [p.strip() for p in v.split("|") if p.strip()]
        return v

    @property
    def id(self) -> uuid.UUID:
        return uuid.uuid5(_NAMESPACE, normalize(self.text))

    @property
    def embedding_text(self) -> str:
        # Plan 9.1: embed text + topic
        return f"{self.topic.replace('_', ' ')}: {self.text}"


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def load_question_bank(path: Path = QUESTION_BANK_CSV) -> list[QuestionRow]:
    """Parse and validate the CSV; raises ValueError listing every bad row or duplicate."""
    rows: list[QuestionRow] = []
    errors: list[str] = []
    seen: dict[str, int] = {}
    with open(path, encoding="utf-8", newline="") as f:
        for line_no, raw in enumerate(csv.DictReader(f), start=2):
            try:
                row = QuestionRow.model_validate(raw)
            except ValueError as e:
                errors.append(f"line {line_no}: {e}")
                continue
            key = normalize(row.text)
            if key in seen:
                errors.append(f"line {line_no}: duplicate of line {seen[key]}")
                continue
            seen[key] = line_no
            rows.append(row)
    if errors:
        raise ValueError(f"{len(errors)} invalid rows in {path}:\n" + "\n".join(errors[:50]))
    return rows
