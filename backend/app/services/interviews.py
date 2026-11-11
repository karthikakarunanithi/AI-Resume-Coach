"""Keeps live interviews in memory and saves finished ones (turns, evaluations, report) to the database.

Live state uses an in-process checkpointer: one server process, and interviews in progress are lost on restart.
Swap in langgraph's Postgres checkpointer when deploying more than one worker.
"""

import asyncio
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.graph import build_interview_graph
from app.agents.planning import QuestionRetriever
from app.agents.runner import InterviewRunner, OnEvent, TurnResult
from app.agents.state import InterviewConfig
from app.config import load_models
from app.db.models import Evaluation, InterviewSession, JobDescription, Report, Resume, Turn, TurnTiming
from app.llm.client import LLMClient
from app.llm.usage import current_session_id
from app.services.evaluator import EVALUATOR_PROMPT, BackgroundEvaluator
from app.services.report import build_report
from app.voice.speech_metrics import UtteranceMetrics, summarize_speech

logger = logging.getLogger("coach.interviews")

RetrieverFactory = Callable[[AsyncSession], QuestionRetriever | None]


class InterviewNotFoundError(LookupError):
    pass


class InterviewNotActiveError(RuntimeError):
    pass


@dataclass
class _Active:
    runner: InterviewRunner
    user_id: uuid.UUID
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    speech: list[UtteranceMetrics] = field(default_factory=list)  # voice answers only
    timings: list[dict] = field(default_factory=list)  # per-turn latency, filled in by the voice session


class InterviewManager:
    def __init__(self, llm: LLMClient, session_factory: async_sessionmaker, retriever_factory: RetrieverFactory):
        self.llm = llm
        self.session_factory = session_factory
        self.retriever_factory = retriever_factory
        self.checkpointer = InMemorySaver()
        self._active: dict[uuid.UUID, _Active] = {}
        self.evaluation_retry_wait_s = 30.0  # before re-scoring answers whose evaluation failed
        self._finalizing: set[asyncio.Task] = set()

    async def start(
        self, db: AsyncSession, user_id: uuid.UUID, config: InterviewConfig,
        resume_id: uuid.UUID | None = None, jd_id: uuid.UUID | None = None,
    ) -> tuple[uuid.UUID, TurnResult]:
        profile = await self._owned(db, Resume, resume_id, user_id, "parsed_profile") if resume_id else {}
        jd = await self._owned(db, JobDescription, jd_id, user_id, "skills") if jd_id else None

        row = InterviewSession(
            user_id=user_id, resume_id=resume_id, jd_id=jd_id, role=config["role"],
            interview_type=config["interview_type"], difficulty=config["difficulty"],
            duration_s=config["duration_min"] * 60, status="planning",
        )
        db.add(row)
        await db.commit()

        graph = build_interview_graph(self.llm, self.retriever_factory(db), checkpointer=self.checkpointer)
        runner = InterviewRunner(graph, str(row.id), BackgroundEvaluator(self.llm, config["interview_type"]))
        token = current_session_id.set(str(row.id))  # tags this session's LLM calls in llm_calls
        try:
            result = await runner.start(config, profile, jd)
        except Exception:
            row.status = "failed"
            await db.commit()
            raise
        finally:
            current_session_id.reset(token)
        state = await runner.state()
        row.status, row.plan = "in_progress", {"questions": state["plan"]}
        row.started_at = datetime.fromtimestamp(state["started_at"], UTC)
        await db.commit()
        self._active[row.id] = _Active(runner, user_id)
        return row.id, result

    async def answer(
        self, user_id: uuid.UUID, session_id: uuid.UUID, text: str, end: bool = False,
        on_event: OnEvent | None = None, speech: UtteranceMetrics | None = None, timing: dict | None = None,
    ) -> TurnResult:
        """`timing` is a dict the caller keeps filling in after this returns (first audio sent, ...);
        it's registered now so the final turn's timing is saved even though the interview ends here."""
        active = self._get(user_id, session_id)
        async with active.lock:  # one turn at a time per interview
            if speech is not None:
                active.speech.append(speech)
            if timing is not None:
                active.timings.append(timing)
            token = current_session_id.set(str(session_id))  # evaluator/report tasks started below inherit it
            try:
                result = await active.runner.answer(text, end=end, on_event=on_event)
                if result.done and self._active.pop(session_id, None):
                    task = asyncio.create_task(self._finalize(session_id, active))
                    self._finalizing.add(task)
                    task.add_done_callback(self._finalizing.discard)
            finally:
                current_session_id.reset(token)
        return result

    def is_active(self, session_id: uuid.UUID) -> bool:
        return session_id in self._active

    async def active_state(self, user_id: uuid.UUID, session_id: uuid.UUID) -> dict:
        return await self._get(user_id, session_id).runner.state()

    def _get(self, user_id: uuid.UUID, session_id: uuid.UUID) -> _Active:
        active = self._active.get(session_id)
        if active is None or active.user_id != user_id:
            raise InterviewNotActiveError(str(session_id))
        return active

    async def drain(self) -> None:
        """Wait for reports still being generated (tests, graceful shutdown)."""
        if self._finalizing:
            await asyncio.gather(*self._finalizing, return_exceptions=True)

    async def _finalize(self, session_id: uuid.UUID, active: _Active) -> None:
        runner = active.runner
        async with self.session_factory() as db:
            row = await db.get(InterviewSession, session_id)
            row.status = "scoring"
            await db.commit()
            try:
                state = await runner.state()
                evaluations = await runner.evaluations()
                if runner.evaluator and any(e is None for e in evaluations.values()):
                    evaluations = await runner.evaluator.retry_failed(
                        evaluations, {q["id"]: q for q in state["plan"]}, state["turns"], self.evaluation_retry_wait_s,
                    )
                report = await build_report(self.llm, state, evaluations, summarize_speech(active.speech))
                self._save(db, row, state, evaluations, report, active.timings)
                row.status, row.ended_at = "done", datetime.now(UTC)
                await db.commit()
            except Exception:
                logger.exception("Finalizing interview %s failed", session_id)
                await db.rollback()
                row.status = "failed"
                await db.commit()

    def _save(
        self, db: AsyncSession, row: InterviewSession, state: dict, evaluations: dict, report,
        active_timings: list[dict],
    ) -> None:
        started = datetime.fromtimestamp(state["started_at"], UTC)
        db.add_all(
            Turn(
                session_id=row.id, speaker=t["speaker"], text=t["text"], question_id=t["question_id"],
                created_at=started + timedelta(seconds=t["at_s"]),  # explicit, so turn order survives bulk insert
            )
            for t in state["turns"]
        )
        model = load_models()["evaluator"]["model"]
        db.add_all(
            Evaluation(
                session_id=row.id, question_id=e.question_id, scores=e.scores, evidence=e.evidence,
                strengths=e.strengths, improvements=e.improvements, missed_key_points=e.missed_key_points,
                overall=e.overall, model=model, prompt_version=EVALUATOR_PROMPT,
            )
            for e in evaluations.values() if e
        )
        db.add_all(
            TurnTiming(
                session_id=row.id, question_id=t.get("question_id"), mode=t["mode"], stt_ms=t.get("stt_ms"),
                first_sentence_ms=t.get("first_sentence_ms"), first_audio_ms=t.get("first_audio_ms"),
                turn_ms=t["turn_ms"],
            )
            for t in active_timings if "turn_ms" in t
        )
        db.add(Report(
            session_id=row.id, overall_score=report.overall_score, hiring_signal=report.hiring_signal,
            report=report.model_dump(mode="json"),
        ))

    @staticmethod
    async def _owned(db: AsyncSession, model, obj_id: uuid.UUID, user_id: uuid.UUID, attr: str):
        obj = await db.get(model, obj_id)
        if obj is None or obj.user_id != user_id:
            raise InterviewNotFoundError(f"{model.__tablename__} {obj_id} not found")
        return getattr(obj, attr)


def default_retriever_factory(db: AsyncSession) -> QuestionRetriever | None:
    from app.rag.embeddings import get_embedder
    from app.rag.retriever import HybridRetriever

    try:
        return HybridRetriever(db, get_embedder())
    except ImportError:
        # Questions loaded with `ingest_questions --no-embeddings` are still found by keyword
        logger.warning("Embedding model not installed (pip install -e '.[embeddings]'); question bank: keyword search only")
        return HybridRetriever(db, None)
