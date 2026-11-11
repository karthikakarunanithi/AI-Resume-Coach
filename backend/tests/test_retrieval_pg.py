"""Integration tests against a real Postgres + pgvector (embedded via pgserver; skipped if unavailable)."""

import asyncio

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import ROOT_DIR
from app.db.models import Question
from app.rag.question_bank import QuestionRow
from app.rag.retriever import (
    HybridRetriever,
    QuestionFilters,
    RetrievalQuery,
    build_query,
    keyword_search_stmt,
)
from scripts.ingest_questions import ingest
from tests.fakes import HashingEmbedder

pgserver = pytest.importorskip("pgserver")


def _row(text: str, role: str, topic: str, difficulty: int = 2, type_: str = "technical") -> QuestionRow:
    return QuestionRow(
        text=text, role=role, topic=topic, type=type_, difficulty=difficulty,
        ideal_key_points=["point one", "point two", "point three"],
    )


ROWS = [
    _row("How would you choose a chunk size for a RAG pipeline?", "genai", "rag", 3),
    _row("What is retrieval augmented generation and why does it reduce hallucination?", "genai", "rag", 1),
    _row("Compare HNSW and IVF indexes for vector search.", "genai", "embeddings_vector_db", 4),
    _row("How does LoRA reduce the cost of fine-tuning an LLM?", "genai", "fine_tuning", 3),
    _row("Explain the bias variance trade-off.", "ml", "ml_fundamentals", 2),
    _row("How do LSTMs mitigate vanishing gradients?", "ml", "deep_learning", 3),
    _row("How does FastAPI dependency injection work?", "backend", "apis_fastapi", 2),
    _row("What happens when you run docker build with a multi-stage Dockerfile?", "backend", "docker_devops", 3),
    _row("Tell me about a time you disagreed with a teammate.", "general", "conflict", 2, "behavioral"),
    _row("Design a rate limiter for a public API.", "backend", "system_design", 4, "system_design"),
]


@pytest.fixture(scope="module")
def pg_url(tmp_path_factory):
    srv = pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")
    base = srv.get_uri().replace("postgresql://", "postgresql+asyncpg://")

    async def create_db():
        conn = await asyncpg.connect(srv.get_uri())
        await conn.execute("DROP DATABASE IF EXISTS coach_test")
        await conn.execute("CREATE DATABASE coach_test")
        await conn.close()

    asyncio.run(create_db())
    url = base.rsplit("/", 1)[0] + "/coach_test"

    cfg = Config(str(ROOT_DIR / "backend" / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    command.check(cfg)  # models and migrations agree
    yield url


@pytest.fixture
async def pg_sessionmaker(pg_url):
    engine = create_async_engine(pg_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    await ingest(ROWS, HashingEmbedder(), factory)
    yield factory
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE questions CASCADE"))
    await engine.dispose()


async def test_ingest_is_idempotent(pg_sessionmaker):
    await ingest(ROWS, HashingEmbedder(), pg_sessionmaker)
    async with pg_sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Question)) == len(ROWS)
        q = await db.scalar(select(Question).where(Question.id == ROWS[0].id))
        assert q.ideal_key_points == ["point one", "point two", "point three"]
        assert len(q.embedding) == 1024


async def test_hybrid_search_ranks_relevant_questions_first(pg_sessionmaker):
    async with pg_sessionmaker() as db:
        retriever = HybridRetriever(db, HashingEmbedder())
        results = await retriever.search(RetrievalQuery(text="RAG retrieval chunk size", keywords=["RAG", "chunk"]))
    assert results[0].text == ROWS[0].text
    assert set(results[0].matched_by) == {"vector", "keyword"}
    assert [r.score for r in results] == sorted([r.score for r in results], reverse=True)


async def test_filters_apply_to_both_sources(pg_sessionmaker):
    filters = QuestionFilters(roles=["genai"], types=["technical"], min_difficulty=3, exclude_ids=[ROWS[0].id])
    async with pg_sessionmaker() as db:
        results = await HybridRetriever(db, HashingEmbedder()).search(build_query("GenAI Developer"), filters)
    assert results
    assert all(r.role == "genai" and r.difficulty >= 3 and r.id != ROWS[0].id for r in results)


async def test_keyword_search_handles_odd_input(pg_sessionmaker):
    async with pg_sessionmaker() as db:
        ids = list(await db.scalars(keyword_search_stmt(['C++', '"unbalanced', "-", "FastAPI"], QuestionFilters())))
    assert ids == [ROWS[6].id]


async def test_keyword_search_can_use_fulltext_index(pg_sessionmaker):
    stmt = keyword_search_stmt(["docker"], QuestionFilters())
    async with pg_sessionmaker() as db:
        await db.execute(text("SET enable_seqscan = off"))
        compiled = stmt.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": True})
        plan = "\n".join(r[0] for r in await db.execute(text(f"EXPLAIN {compiled}")))
    assert "ix_questions_text_fts" in plan
