"""GET /users/me/progress: scores over time and weakest topics across a user's finished interviews (plan 13, 12)."""

import uuid
from collections import defaultdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_active_user
from app.db.models import InterviewSession, Report, User
from app.db.session import get_db
from app.services.report import is_scored

router = APIRouter(tags=["users"])
WEAKEST_TOPICS = 5


class ProgressPoint(BaseModel):
    session_id: uuid.UUID
    created_at: datetime
    role: str
    interview_type: str
    overall_score: int
    hiring_signal: str


class TopicScore(BaseModel):
    topic: str
    avg_score: int  # 0-100
    questions: int


class Progress(BaseModel):
    interviews: int  # finished interviews with a report
    avg_score: int | None
    best_score: int | None
    last_score: int | None
    change_vs_previous: int | None  # last minus the one before it
    points: list[ProgressPoint]  # oldest first
    weakest_topics: list[TopicScore]  # lowest average first
    dimension_averages: dict[str, float]  # rubric dimension -> average 1-5 across interviews


@router.get("/users/me/progress", response_model=Progress)
async def my_progress(
    user: Annotated[User, Depends(current_active_user)], db: Annotated[AsyncSession, Depends(get_db)]
) -> Progress:
    rows = (await db.execute(
        select(InterviewSession, Report)
        .join(Report, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.created_at)
    )).all()
    # Interviews with nothing scored (ended before answering, or scoring failed) carry no signal about skill
    rows = [(s, r) for s, r in rows if is_scored(r.report)]

    points = [
        ProgressPoint(session_id=s.id, created_at=s.created_at, role=s.role, interview_type=s.interview_type,
                      overall_score=r.overall_score, hiring_signal=r.hiring_signal)
        for s, r in rows
    ]
    topic_scores: dict[str, list[int]] = defaultdict(list)
    dims: dict[str, list[float]] = defaultdict(list)
    for _, r in rows:
        for q in r.report.get("questions", []):
            if q.get("score") is not None:
                topic_scores[q["topic"]].append(q["score"])
        for dim, value in r.report.get("dimension_scores", {}).items():
            dims[dim].append(value)

    topics = sorted(
        (TopicScore(topic=t, avg_score=round(sum(v) / len(v)), questions=len(v)) for t, v in topic_scores.items()),
        key=lambda t: (t.avg_score, -t.questions),
    )
    scores = [p.overall_score for p in points]
    return Progress(
        interviews=len(points),
        avg_score=round(sum(scores) / len(scores)) if scores else None,
        best_score=max(scores, default=None),
        last_score=scores[-1] if scores else None,
        change_vs_previous=scores[-1] - scores[-2] if len(scores) >= 2 else None,
        points=points,
        weakest_topics=topics[:WEAKEST_TOPICS],
        dimension_averages={d: round(sum(v) / len(v), 2) for d, v in dims.items()},
    )
