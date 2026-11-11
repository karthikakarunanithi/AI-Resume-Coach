from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import InterviewSession, Report, User


def _report(score: int, answered: int, questions: list[tuple[str, int]], dims: dict) -> dict:
    return {
        "overall_score": score, "questions_answered": answered, "dimension_scores": dims,
        "questions": [{"topic": t, "score": s} for t, s in questions],
    }


async def test_progress_aggregates_finished_interviews(client, make_user, db_sessionmaker):
    headers = await make_user()
    async with db_sessionmaker() as db:
        user = await db.scalar(select(User))
        t0 = datetime(2026, 10, 1, tzinfo=UTC)
        data = [
            (55, "Lean no", 2, [("rag", 40), ("llm_evaluation", 70)], {"depth": 2.0}),
            (0, "Not yet", 0, [], {}),  # ended before answering: ignored
            (72, "Lean yes", 3, [("rag", 60), ("agents_tool_use", 85), ("llm_evaluation", 70)], {"depth": 3.0}),
        ]
        for i, (score, signal, answered, qs, dims) in enumerate(data):
            s = InterviewSession(user_id=user.id, role="GenAI Developer", interview_type="technical",
                                 difficulty="medium", duration_s=600, status="done", created_at=t0 + timedelta(days=i))
            db.add(s)
            await db.flush()
            db.add(Report(session_id=s.id, overall_score=score, hiring_signal=signal,
                          report=_report(score, answered, qs, dims)))
        # a second user's data must not leak in
        other = User(email="other@example.com", hashed_password="x")
        db.add(other)
        await db.flush()
        s = InterviewSession(user_id=other.id, role="x", interview_type="hr", difficulty="easy", duration_s=600,
                             status="done")
        db.add(s)
        await db.flush()
        db.add(Report(session_id=s.id, overall_score=99, hiring_signal="Strong", report=_report(99, 1, [], {})))
        await db.commit()

    p = (await client.get("/users/me/progress", headers=headers)).json()
    assert (p["interviews"], p["avg_score"], p["best_score"], p["last_score"], p["change_vs_previous"]) == (
        2, 64, 72, 72, 17)
    assert [pt["overall_score"] for pt in p["points"]] == [55, 72]
    assert p["weakest_topics"][0] == {"topic": "rag", "avg_score": 50, "questions": 2}
    assert [t["topic"] for t in p["weakest_topics"]] == ["rag", "llm_evaluation", "agents_tool_use"]
    assert p["dimension_averages"] == {"depth": 2.5}


async def test_progress_empty(client, make_user):
    p = (await client.get("/users/me/progress", headers=await make_user())).json()
    assert (p["interviews"], p["avg_score"], p["change_vs_previous"], p["points"]) == (0, None, None, [])


async def test_progress_requires_auth(client):
    assert (await client.get("/users/me/progress")).status_code == 401
