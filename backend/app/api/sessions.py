import logging
import uuid
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.users import current_active_user
from app.db.models import InterviewSession, Report, User
from app.db.session import SessionLocal, get_db
from app.llm.deps import get_llm
from app.llm.errors import user_message
from app.services.interviews import (
    InterviewManager,
    InterviewNotActiveError,
    InterviewNotFoundError,
    default_retriever_factory,
)
from app.services.report import FinalReport, is_scored

logger = logging.getLogger("coach.api")
router = APIRouter(prefix="/sessions", tags=["sessions"])


@lru_cache
def get_interview_manager() -> InterviewManager:
    return InterviewManager(get_llm(), SessionLocal, default_retriever_factory)


DB = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(current_active_user)]
Manager = Annotated[InterviewManager, Depends(get_interview_manager)]


class SessionCreate(BaseModel):
    role: str = Field(min_length=2, max_length=100)
    interview_type: Literal["technical", "behavioral", "hr", "system_design"] = "technical"
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    duration_min: int = Field(default=20, ge=5, le=60)
    company_type: str = Field(default="product company", max_length=100)
    resume_id: uuid.UUID | None = None
    jd_id: uuid.UUID | None = None


class AnswerIn(BaseModel):
    text: str = Field(default="", max_length=10_000)


class TurnOut(BaseModel):
    session_id: uuid.UUID
    spoken: list[str]
    question_id: str | None
    done: bool
    question_number: int | None = None
    total_questions: int | None = None
    time_left_s: int | None = None


class SessionSummary(BaseModel):
    id: uuid.UUID
    role: str
    interview_type: str
    difficulty: str
    status: str
    created_at: datetime
    overall_score: int | None
    hiring_signal: str | None


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TurnOut)
async def create_session(body: SessionCreate, user: CurrentUser, db: DB, manager: Manager) -> TurnOut:
    config = body.model_dump(include={"role", "interview_type", "difficulty", "duration_min", "company_type"})
    try:
        session_id, result = await manager.start(db, user.id, config, body.resume_id, body.jd_id)
    except InterviewNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except Exception as e:  # planner and provider errors
        logger.exception("Starting interview failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, user_message(e, "Planning the interview")) from e
    return TurnOut(session_id=session_id, **vars(result))


async def _turn(manager: InterviewManager, user: User, session_id: uuid.UUID, text: str, end: bool) -> TurnOut:
    try:
        result = await manager.answer(user.id, session_id, text, end=end)
    except InterviewNotActiveError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, "This interview is not in progress") from e
    return TurnOut(session_id=session_id, **vars(result))


@router.post("/{session_id}/answers", response_model=TurnOut)
async def answer(session_id: uuid.UUID, body: AnswerIn, user: CurrentUser, manager: Manager) -> TurnOut:
    """Text answers (FR-7 fallback); the voice WebSocket in week 5 drives the same runner."""
    return await _turn(manager, user, session_id, body.text, end=False)


@router.post("/{session_id}/end", response_model=TurnOut)
async def end_session(session_id: uuid.UUID, user: CurrentUser, manager: Manager) -> TurnOut:
    return await _turn(manager, user, session_id, "", end=True)


@router.get("", response_model=list[SessionSummary])
async def list_sessions(user: CurrentUser, db: DB) -> list[SessionSummary]:
    rows = await db.execute(
        select(InterviewSession, Report.overall_score, Report.hiring_signal, Report.report)
        .outerjoin(Report, Report.session_id == InterviewSession.id)
        .where(InterviewSession.user_id == user.id)
        .order_by(InterviewSession.created_at.desc())
    )
    return [
        SessionSummary(
            id=s.id, role=s.role, interview_type=s.interview_type, difficulty=s.difficulty, status=s.status,
            created_at=s.created_at,
            # An unscored report has a placeholder 0 in the table: show it as "not scored", never as a score
            overall_score=score if report and is_scored(report) else None,
            hiring_signal=signal if report and is_scored(report) else None,
        )
        for s, score, signal, report in rows
    ]


@router.get(
    "/{session_id}/report",
    response_model=FinalReport,
    responses={202: {"description": "Interview still running or report being generated"}},
)
async def get_report(session_id: uuid.UUID, user: CurrentUser, db: DB):
    session = await db.get(InterviewSession, session_id)
    if session is None or session.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
    report = await db.scalar(select(Report).where(Report.session_id == session_id))
    if report:
        return FinalReport.model_validate(report.report)
    if session.status == "failed":
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Report generation failed")
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"status": session.status})
