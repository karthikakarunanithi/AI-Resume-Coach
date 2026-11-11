from typing import Literal

from pydantic import BaseModel, Field


class Project(BaseModel):
    title: str
    tech_stack: list[str] = Field(default_factory=list)
    summary: str = ""


class Experience(BaseModel):
    company: str
    role: str
    highlights: list[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    name: str | None = None
    years_experience: float = 0.0
    skills: list[str] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: str = ""

    def summary(self) -> str:
        """Compact text form for prompts."""
        lines = [f"Name: {self.name or 'unknown'}; experience: {self.years_experience:g} years"]
        if self.skills:
            lines.append(f"Skills: {', '.join(self.skills[:15])}")
        lines += [f"Project: {p.title} ({', '.join(p.tech_stack)}) - {p.summary}" for p in self.projects[:4]]
        lines += [f"Role: {e.role} at {e.company}" for e in self.experience[:3]]
        if self.education:
            lines.append(f"Education: {self.education}")
        return "\n".join(lines)


class JDAnalysis(BaseModel):
    title: str | None = None
    seniority: Literal["intern", "fresher", "junior", "mid", "senior", "lead"] | None = None
    required_skills: list[str] = Field(default_factory=list)
    nice_to_have_skills: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)


class QuestionDraft(BaseModel):
    """A question as the planner LLM writes it."""

    text: str
    topic: str
    difficulty: int = Field(ge=1, le=5)
    source: Literal["resume", "jd", "bank"]
    ideal_key_points: list[str] = Field(min_length=1)


class PlannedQuestion(QuestionDraft):
    id: str  # assigned in code after planning (q1, q2, ...): never asked of the model


class InterviewPlan(BaseModel):
    questions: list[QuestionDraft] = Field(min_length=1)


class InterviewerAction(BaseModel):
    action: Literal["follow_up", "next_question", "clarify", "wrap_up"]
    spoken_text: str  # what the TTS will say
    question_id: str | None = None
    reason: str  # internal, not spoken (for tracing/debug)


class DimensionScore(BaseModel):
    dimension: str  # rubric dimension name, e.g. "correctness"
    score: int  # 1..5 (range enforced in code: structured outputs can't express it)
    evidence: str  # exact quote from the candidate, or ""


class EvaluationDraft(BaseModel):
    """What the evaluator LLM returns; scores are checked and `overall` computed in code.

    A list, not a dimension -> score map: structured outputs require every object to have fixed keys."""

    dimension_scores: list[DimensionScore]
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    missed_key_points: list[str] = Field(default_factory=list)


class AnswerEvaluation(BaseModel):
    question_id: str
    scores: dict[str, int]  # rubric dimension -> 1..5
    evidence: dict[str, str]  # rubric dimension -> quote from transcript ("" = none found)
    strengths: list[str]
    improvements: list[str]
    missed_key_points: list[str]
    overall: float  # weighted average of scores, 1..5


class PracticeDay(BaseModel):
    day: int = Field(ge=1, le=7)
    focus: str
    tasks: list[str]


class SampleAnswer(BaseModel):
    question_id: str
    answer: str


class CoachNarrative(BaseModel):
    """What the coach LLM writes; all numbers in the report are computed in code.
    List lengths (3 strengths, 7 days, ...) are asked for in the prompt and trimmed in code, not validated:
    one extra item shouldn't throw away the whole narrative."""

    summary: str
    strengths: list[str]
    improvements: list[str]
    practice_plan: list[PracticeDay]
    sample_answers: list[SampleAnswer]
