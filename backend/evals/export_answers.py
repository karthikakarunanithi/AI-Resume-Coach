"""Export answered questions from finished interviews into evals/datasets/answers.jsonl for human rating.

Usage (from backend/):  python -m evals.export_answers [--limit 60]

Only new answers are appended; existing cases (and their ratings) are kept. The file contains real
candidates' answers, so it is gitignored. Get consent before rating friends' answers with others.
"""

import argparse
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import InterviewSession, Report
from evals.dataset import ANSWERS, EvalCase, Line, load_cases, save_cases


async def collect(db: AsyncSession, limit: int, existing: set[str]) -> list[EvalCase]:
    rows = await db.execute(
        select(InterviewSession, Report)
        .join(Report, Report.session_id == InterviewSession.id)
        .order_by(InterviewSession.created_at.desc())
    )
    out: list[EvalCase] = []
    for session, report in rows:
        key_points = {q["id"]: q["ideal_key_points"] for q in (session.plan or {}).get("questions", [])}
        for q in report.report.get("questions", []):
            case_id = f"{session.id}:{q['question_id']}"
            answered = any(t["speaker"] == "candidate" for t in q["transcript"])
            if case_id in existing or not answered or q["question_id"] not in key_points:
                continue
            out.append(EvalCase(
                id=case_id, source="interview", interview_type=session.interview_type, question=q["text"],
                ideal_key_points=key_points[q["question_id"]],
                transcript=[Line(speaker=t["speaker"], text=t["text"]) for t in q["transcript"]],
            ))
            if len(out) >= limit:
                return out
    return out


async def main() -> None:
    from app.db.session import SessionLocal

    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--limit", type=int, default=60)
    args = p.parse_args()

    cases = load_cases(ANSWERS)
    async with SessionLocal() as db:
        new = await collect(db, args.limit, {c.id for c in cases})
    save_cases(ANSWERS, cases + new)
    print(f"Added {len(new)} answers; {len(cases) + len(new)} in {ANSWERS}")


if __name__ == "__main__":
    asyncio.run(main())
