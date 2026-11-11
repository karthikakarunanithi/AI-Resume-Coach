"""Validate data/question_bank.csv, embed every question and upsert it into Postgres.

Idempotent: question ids are derived from the text, so re-running updates rows in place.

Usage (from backend/, after `alembic upgrade head`):
    python -m scripts.ingest_questions                    # embed + upsert
    python -m scripts.ingest_questions --no-embeddings    # upsert text only (no 2 GB model; keyword search only)
    python -m scripts.ingest_questions --check            # validate the CSV only
"""

import asyncio
import sys
from collections import Counter

from sqlalchemy.dialects.postgresql import insert

from app.db.models import Question
from app.db.session import SessionLocal
from app.rag.embeddings import Embedder, get_embedder
from app.rag.question_bank import QuestionRow, load_question_bank

BATCH = 64


async def ingest(rows: list[QuestionRow], embedder: Embedder | None, session_factory=SessionLocal) -> int:
    """embedder=None stores questions without vectors; existing vectors are kept, never wiped."""
    async with session_factory() as db:
        for i in range(0, len(rows), BATCH):
            batch = rows[i : i + BATCH]
            vectors = await embedder.embed([r.embedding_text for r in batch]) if embedder else [None] * len(batch)
            values = [
                {
                    "id": r.id, "text": r.text, "role": r.role, "topic": r.topic, "type": r.type,
                    "difficulty": r.difficulty, "ideal_key_points": r.ideal_key_points, "embedding": v,
                }
                for r, v in zip(batch, vectors, strict=True)
            ]
            stmt = insert(Question).values(values)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Question.id],
                set_={c: stmt.excluded[c] for c in values[0] if c != "id" and (embedder or c != "embedding")},
            )
            await db.execute(stmt)
            print(f"  {min(i + BATCH, len(rows))}/{len(rows)}")
        await db.commit()
    return len(rows)


def summarize(rows: list[QuestionRow]) -> str:
    def by(attr: str) -> dict:
        return dict(sorted(Counter(getattr(r, attr) for r in rows).items()))

    return f"{len(rows)} questions\n  by track: {by('role')}\n  by type: {by('type')}\n  by difficulty: {by('difficulty')}"


async def main() -> None:
    rows = load_question_bank()
    print(summarize(rows))
    if "--check" in sys.argv:
        return
    if "--no-embeddings" in sys.argv:
        print("Upserting without embeddings (vector search skips these until you re-run with embeddings)...")
        await ingest(rows, None)
    else:
        print("Embedding and upserting...")
        await ingest(rows, get_embedder())
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
