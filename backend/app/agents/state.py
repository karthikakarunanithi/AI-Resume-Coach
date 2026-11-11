import operator
from typing import Annotated, Literal, TypedDict

Status = Literal["planning", "in_progress", "wrap_up", "done"]
MAX_FOLLOW_UPS = 2
WRAP_UP_MARGIN_S = 60  # start wrapping up when less than this much time is left
RECENT_TURNS = 4  # turns sent verbatim to the interviewer; older ones go into running_summary
SUMMARIZE_EVERY = 5  # summarize once this many turns have fallen out of the recent window


class Turn(TypedDict):
    speaker: Literal["interviewer", "candidate"]
    text: str
    question_id: str | None
    at_s: float  # seconds since the interview started


class InterviewConfig(TypedDict):
    role: str
    interview_type: Literal["technical", "behavioral", "hr", "system_design"]
    difficulty: Literal["easy", "medium", "hard"]
    duration_min: int
    company_type: str


class InterviewState(TypedDict, total=False):
    session_id: str
    config: InterviewConfig
    profile: dict  # CandidateProfile
    jd: dict | None  # JDAnalysis
    plan: list[dict]  # PlannedQuestion
    current_q_index: int
    follow_ups_on_current: int
    turns: Annotated[list[Turn], operator.add]
    running_summary: str
    summarized_turns: int  # how many turns running_summary already covers
    finished_questions: Annotated[list[str], operator.add]  # ids ready for the evaluator (week 4)
    started_at: float
    time_budget_s: int
    status: Status
    end_requested: bool
    last_answer_safe: bool
