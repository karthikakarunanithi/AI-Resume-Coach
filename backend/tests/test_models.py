from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models import Evaluation, InterviewSession, Resume, Turn, User


async def test_session_with_turns_and_evaluation_roundtrip(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(email="a@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        resume = Resume(user_id=user.id, file_url="s3://r.pdf", parsed_profile={"skills": ["FastAPI"]})
        db.add(resume)
        await db.flush()
        session = InterviewSession(
            user_id=user.id, resume_id=resume.id, role="ML Engineer",
            interview_type="technical", difficulty="medium", duration_s=1200,
        )
        db.add(session)
        await db.flush()
        db.add_all([
            Turn(session_id=session.id, speaker="interviewer", text="Tell me about FastAPI.", question_id="q1"),
            Turn(session_id=session.id, speaker="candidate", text="It's an async web framework."),
            Evaluation(
                session_id=session.id, question_id="q1", scores={"correctness": 4},
                evidence={"correctness": "async web framework"}, strengths=[], improvements=[],
                overall=4.0, model="test-model", prompt_version="evaluator_v1",
            ),
        ])
        await db.commit()

    async with db_sessionmaker() as db:
        loaded = await db.scalar(
            select(InterviewSession).options(selectinload(InterviewSession.turns))
        )
        assert loaded.status == "planning"
        assert loaded.created_at is not None
        assert [t.speaker for t in loaded.turns] == ["interviewer", "candidate"]
        ev = await db.scalar(select(Evaluation))
        assert ev.scores == {"correctness": 4}
        assert ev.missed_key_points == []
