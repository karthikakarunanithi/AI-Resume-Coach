import uuid
from datetime import datetime
from typing import Any

from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base

# JSONB on Postgres, plain JSON elsewhere (e.g. SQLite in tests)
JSONType = JSON().with_variant(JSONB(), "postgresql")
EMBEDDING_DIM = 1024  # bge-m3


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _fk(target: str, nullable: bool = False) -> Mapped[Any]:
    return mapped_column(Uuid, ForeignKey(target, ondelete="CASCADE"), index=True, nullable=nullable)


class User(SQLAlchemyBaseUserTableUUID, Base):
    """FastAPI-Users provides id, email, hashed_password, is_active, is_superuser, is_verified."""

    __tablename__ = "users"

    name: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created_at()


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    file_url: Mapped[str] = mapped_column(String(1024))
    parsed_profile: Mapped[dict | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created_at()


class JobDescription(Base):
    __tablename__ = "job_descriptions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    raw_text: Mapped[str] = mapped_column(Text)
    skills: Mapped[list | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created_at()


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = _pk()
    text: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(100), index=True)
    topic: Mapped[str] = mapped_column(String(100))
    type: Mapped[str] = mapped_column(String(50))  # technical | hr | behavioral | system_design
    difficulty: Mapped[int] = mapped_column(Integer)  # 1..5
    ideal_key_points: Mapped[list] = mapped_column(JSONType, default=list)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))

    # Hybrid retrieval indexes (plan 9.2); Postgres-only, so SQLite test databases skip them
    __table_args__ = (
        Index(
            "ix_questions_embedding_hnsw", "embedding",
            postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"},
        ).ddl_if(dialect="postgresql"),
        Index(
            # Written exactly as Postgres reflects it, so `alembic check` sees no drift
            "ix_questions_text_fts",
            sql_text("to_tsvector('english'::regconfig, (text || ' '::text) || topic::text)"),
            postgresql_using="gin",
        ).ddl_if(dialect="postgresql"),
    )


class InterviewSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = _fk("users.id")
    resume_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("resumes.id", ondelete="SET NULL"))
    jd_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("job_descriptions.id", ondelete="SET NULL")
    )
    role: Mapped[str] = mapped_column(String(100))
    interview_type: Mapped[str] = mapped_column(String(50))
    difficulty: Mapped[str] = mapped_column(String(20))
    duration_s: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="planning")
    plan: Mapped[dict | None] = mapped_column(JSONType)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    turns: Mapped[list["Turn"]] = relationship(back_populates="session", order_by="Turn.created_at")


class Turn(Base):
    __tablename__ = "turns"

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = _fk("sessions.id")
    speaker: Mapped[str] = mapped_column(String(20))  # interviewer | candidate
    text: Mapped[str] = mapped_column(Text)
    question_id: Mapped[str | None] = mapped_column(String(50))  # id within the session plan
    audio_ms: Mapped[int | None] = mapped_column(Integer)
    word_timestamps: Mapped[list | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created_at()

    session: Mapped[InterviewSession] = relationship(back_populates="turns")


class Evaluation(Base):
    __tablename__ = "evaluations"

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = _fk("sessions.id")
    question_id: Mapped[str] = mapped_column(String(50))
    scores: Mapped[dict] = mapped_column(JSONType)
    evidence: Mapped[dict] = mapped_column(JSONType)
    strengths: Mapped[list] = mapped_column(JSONType)
    improvements: Mapped[list] = mapped_column(JSONType)
    missed_key_points: Mapped[list] = mapped_column(JSONType, default=list)
    overall: Mapped[float] = mapped_column(Numeric(4, 2))
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = _created_at()


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sessions.id", ondelete="CASCADE"), unique=True
    )
    overall_score: Mapped[int] = mapped_column(Integer)  # 0..100
    hiring_signal: Mapped[str] = mapped_column(String(20))
    report: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created_at()


class LLMCall(Base):
    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID | None] = _fk("sessions.id", nullable=True)
    task: Mapped[str] = mapped_column(String(50), index=True)
    model: Mapped[str] = mapped_column(String(100))  # model that answered
    configured_model: Mapped[str | None] = mapped_column(String(100))  # differs from model => fallback used
    prompt_version: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[float] = mapped_column(Float)
    ttft_ms: Mapped[float | None] = mapped_column(Float)  # time to first token, streaming calls
    cost_usd: Mapped[float | None] = mapped_column(Numeric(10, 6))  # None = price unknown
    success: Mapped[bool] = mapped_column(default=True)
    json_valid: Mapped[bool | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = _created_at()


class TurnTiming(Base):
    """Server-side latency of one interview turn (plan 8.4 budget, NFR-1)."""

    __tablename__ = "turn_timings"

    id: Mapped[uuid.UUID] = _pk()
    session_id: Mapped[uuid.UUID] = _fk("sessions.id")
    question_id: Mapped[str | None] = mapped_column(String(50))
    mode: Mapped[str] = mapped_column(String(10))  # voice | text
    stt_ms: Mapped[float | None] = mapped_column(Float)
    first_sentence_ms: Mapped[float | None] = mapped_column(Float)  # answer received -> first sentence sent
    first_audio_ms: Mapped[float | None] = mapped_column(Float)  # answer received -> first TTS audio sent
    turn_ms: Mapped[float] = mapped_column(Float)  # answer received -> turn_end
    created_at: Mapped[datetime] = _created_at()


class HumanRating(Base):
    __tablename__ = "human_ratings"

    id: Mapped[uuid.UUID] = _pk()
    evaluation_id: Mapped[uuid.UUID] = _fk("evaluations.id")
    rater: Mapped[str] = mapped_column(String(100))
    scores: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = _created_at()
