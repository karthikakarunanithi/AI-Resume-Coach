"""Hybrid question retrieval (plan 9.2): pgvector cosine + Postgres full-text, merged with RRF."""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Question
from app.llm.schemas import CandidateProfile, JDAnalysis
from app.rag.embeddings import Embedder

RRF_K = 60  # standard constant from the RRF paper; dampens the weight of top ranks
CANDIDATES_PER_SOURCE = 50
MAX_RESUME_SKILLS = 8

# Must match the expression of ix_questions_text_fts exactly, or Postgres won't use the index
_WEBSEARCH_SYNTAX = re.compile(r"[^\w\s+#.]")
TSVECTOR = literal_column("to_tsvector('english', questions.text || ' ' || questions.topic)")


@dataclass
class RetrievalQuery:
    text: str  # natural-language query for the embedding search
    keywords: list[str]  # OR-ed together for the full-text search


@dataclass
class QuestionFilters:
    roles: Sequence[str] | None = None  # bank tracks, e.g. ["genai", "ml", "general"]
    types: Sequence[str] | None = None  # technical | behavioral | hr | system_design
    min_difficulty: int = 1
    max_difficulty: int = 5
    exclude_ids: Sequence[uuid.UUID] = field(default_factory=list)


class RetrievedQuestion(BaseModel):
    id: uuid.UUID
    text: str
    role: str
    topic: str
    type: str
    difficulty: int
    ideal_key_points: list[str]
    score: float
    matched_by: list[str]  # "vector" and/or "keyword"


def build_query(role: str, jd: JDAnalysis | None = None, profile: CandidateProfile | None = None) -> RetrievalQuery:
    """Query = role + JD skills + top resume skills (plan 9.2)."""
    skills: list[str] = []
    if jd:
        skills += jd.required_skills + jd.nice_to_have_skills
    if profile:
        skills += profile.skills[:MAX_RESUME_SKILLS]
    keywords = _dedupe([role, *skills])

    parts = [f"Interview questions for a {role}."]
    if jd and jd.required_skills:
        parts.append(f"Required skills: {', '.join(jd.required_skills)}.")
    if jd and jd.responsibilities:
        parts.append(f"Responsibilities: {'; '.join(jd.responsibilities)}.")
    if profile and profile.skills:
        parts.append(f"Candidate skills: {', '.join(profile.skills[:MAX_RESUME_SKILLS])}.")
    return RetrievalQuery(text=" ".join(parts), keywords=keywords)


def rrf_fuse(rankings: dict[str, list[uuid.UUID]], k: int = RRF_K) -> list[tuple[uuid.UUID, float, list[str]]]:
    """Reciprocal Rank Fusion: score(d) = sum over sources of 1 / (k + rank)."""
    scores: dict[uuid.UUID, float] = {}
    sources: dict[uuid.UUID, list[str]] = {}
    for source, ids in rankings.items():
        for rank, qid in enumerate(ids, start=1):
            scores[qid] = scores.get(qid, 0.0) + 1.0 / (k + rank)
            sources.setdefault(qid, []).append(source)
    ordered = sorted(scores, key=lambda q: scores[q], reverse=True)
    return [(qid, scores[qid], sources[qid]) for qid in ordered]


class HybridRetriever:
    """embedder=None runs keyword search only (no embedding model installed); results are still RRF-ranked."""

    def __init__(self, db: AsyncSession, embedder: Embedder | None):
        self.db = db
        self.embedder = embedder

    async def search(
        self, query: RetrievalQuery, filters: QuestionFilters | None = None, k: int = 20
    ) -> list[RetrievedQuestion]:
        filters = filters or QuestionFilters()
        vector_ids = []
        if self.embedder is not None:
            [query_vec] = await self.embedder.embed([query.text])
            vector_ids = list(await self.db.scalars(vector_search_stmt(query_vec, filters)))
        keyword_ids = list(await self.db.scalars(keyword_search_stmt(query.keywords, filters)))

        fused = rrf_fuse({"vector": vector_ids, "keyword": keyword_ids})[:k]
        rows = {q.id: q for q in await self.db.scalars(select(Question).where(Question.id.in_([f[0] for f in fused])))}
        return [
            RetrievedQuestion(
                id=qid, text=rows[qid].text, role=rows[qid].role, topic=rows[qid].topic, type=rows[qid].type,
                difficulty=rows[qid].difficulty, ideal_key_points=rows[qid].ideal_key_points,
                score=score, matched_by=matched,
            )
            for qid, score, matched in fused
        ]


def _filter_clauses(f: QuestionFilters) -> list[ColumnElement[bool]]:
    clauses = [Question.difficulty.between(f.min_difficulty, f.max_difficulty)]
    if f.roles:
        clauses.append(Question.role.in_(f.roles))
    if f.types:
        clauses.append(Question.type.in_(f.types))
    if f.exclude_ids:
        clauses.append(Question.id.not_in(f.exclude_ids))
    return clauses


def vector_search_stmt(query_vec: list[float], f: QuestionFilters) -> Select[tuple[uuid.UUID]]:
    return (
        select(Question.id)
        .where(Question.embedding.is_not(None), *_filter_clauses(f))
        .order_by(Question.embedding.cosine_distance(query_vec))
        .limit(CANDIDATES_PER_SOURCE)
    )


def keyword_search_stmt(keywords: list[str], f: QuestionFilters) -> Select[tuple[uuid.UUID]]:
    # "a or b or c" matches any keyword. Quotes and leading "-" are websearch syntax (phrase / negation),
    # so strip them: skill names come from LLM output and must not change the query's meaning.
    terms = [t for k in keywords if (t := _WEBSEARCH_SYNTAX.sub(" ", k).strip())]
    tsquery = func.websearch_to_tsquery(literal_column("'english'"), " or ".join(terms))
    return (
        select(Question.id)
        .where(TSVECTOR.op("@@")(tsquery), *_filter_clauses(f))
        .order_by(func.ts_rank_cd(TSVECTOR, tsquery).desc(), Question.id)
        .limit(CANDIDATES_PER_SOURCE)
    )


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item.strip())
    return out
