import pytest
from sqlalchemy import func, select

from app.api.sessions import get_interview_manager
from app.db.models import Evaluation, Resume, Turn
from app.llm.schemas import (
    CoachNarrative,
    DimensionScore,
    EvaluationDraft,
    InterviewerAction,
    InterviewPlan,
    QuestionDraft,
)
from app.main import app
from app.services.interviews import InterviewManager
from tests.fakes import render_action, stream_text

START = {"role": "GenAI Developer", "interview_type": "technical", "difficulty": "medium", "duration_min": 10}


class FakeLLM:
    def __init__(self):
        self.tasks: list[str] = []

    async def structured(self, task, messages, response_model, **kwargs):
        self.tasks.append(task)
        if task == "planner":
            return InterviewPlan(questions=[
                QuestionDraft(text=f"Question {i}?", topic="rag", difficulty=2, source="bank", ideal_key_points=["kp"])
                for i in (1, 2, 3)
            ])
        if task == "evaluator":
            return EvaluationDraft(
                dimension_scores=[
                    DimensionScore(dimension=d, score=4, evidence="my detailed answer")
                    for d in ["correctness", "depth", "specificity", "structure", "communication"]
                ],
                strengths=["clear"], improvements=["add numbers"],
            )
        if task == "coach":
            return CoachNarrative(summary="Good job.", strengths=["a"], improvements=["b"],
                                  practice_plan=[], sample_answers=[])
        raise AssertionError(task)

    async def chat(self, task, messages, stream=False, **kwargs):
        self.tasks.append(task)
        assert task == "interviewer" and stream
        return stream_text(render_action(InterviewerAction(action="next_question", spoken_text="Next one.", reason="t")))


@pytest.fixture
def manager(db_sessionmaker):
    m = InterviewManager(FakeLLM(), db_sessionmaker, lambda db: None)
    app.dependency_overrides[get_interview_manager] = lambda: m
    return m


async def test_full_text_interview_produces_report(client, make_user, manager, db_sessionmaker):
    headers = await make_user()
    resp = await client.post("/sessions", json=START, headers=headers)
    assert resp.status_code == 201, resp.text
    sid = resp.json()["session_id"]
    assert resp.json()["question_id"] == "q1"

    assert (await client.get(f"/sessions/{sid}/report", headers=headers)).status_code == 202
    for _ in range(3):
        turn = (await client.post(f"/sessions/{sid}/answers", json={"text": "my detailed answer"}, headers=headers)).json()
    assert turn["done"]

    await manager.drain()
    resp = await client.get(f"/sessions/{sid}/report", headers=headers)
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["overall_score"] == 75 and report["hiring_signal"] == "Lean yes"
    assert report["questions_answered"] == 3 and report["coach_generated"]
    assert report["questions"][0]["evidence"]["correctness"] == "my detailed answer"

    listed = (await client.get("/sessions", headers=headers)).json()
    assert listed[0]["status"] == "done" and listed[0]["overall_score"] == 75

    async with db_sessionmaker() as db:
        assert await db.scalar(select(func.count()).select_from(Evaluation)) == 3
        speakers = list(await db.scalars(select(Turn.speaker).order_by(Turn.created_at)))
        assert speakers[:2] == ["interviewer", "candidate"] and speakers[-1] == "interviewer"


async def test_end_early_and_answer_after_end(client, make_user, manager):
    headers = await make_user()
    sid = (await client.post("/sessions", json=START, headers=headers)).json()["session_id"]
    assert (await client.post(f"/sessions/{sid}/end", headers=headers)).json()["done"]
    assert (await client.post(f"/sessions/{sid}/answers", json={"text": "late"}, headers=headers)).status_code == 409

    await manager.drain()
    report = (await client.get(f"/sessions/{sid}/report", headers=headers)).json()
    assert report["questions_answered"] == 0 and report["hiring_signal"] == "Not yet"


async def test_sessions_are_private(client, make_user, manager):
    owner = await make_user("a@example.com")
    sid = (await client.post("/sessions", json=START, headers=owner)).json()["session_id"]
    other = await make_user("b@example.com")
    assert (await client.get(f"/sessions/{sid}/report", headers=other)).status_code == 404
    assert (await client.post(f"/sessions/{sid}/answers", json={"text": "x"}, headers=other)).status_code == 409
    assert (await client.get("/sessions", headers=other)).json() == []


async def test_cannot_use_someone_elses_resume(client, make_user, manager, db_sessionmaker):
    await make_user("a@example.com")
    async with db_sessionmaker() as db:
        from app.db.models import User

        owner = await db.scalar(select(User).where(User.email == "a@example.com"))
        resume = Resume(user_id=owner.id, file_url="file:///r.pdf", parsed_profile={"skills": ["Python"]})
        db.add(resume)
        await db.commit()
    other = await make_user("b@example.com")
    resp = await client.post("/sessions", json={**START, "resume_id": str(resume.id)}, headers=other)
    assert resp.status_code == 404


class FlakyEvaluatorLLM(FakeLLM):
    """The first `failures` evaluator calls hit a rate limit, like a busy free tier."""

    def __init__(self, failures: int):
        super().__init__()
        self.failures = failures

    async def structured(self, task, messages, response_model, **kwargs):
        if task == "evaluator" and self.failures > 0:
            self.failures -= 1
            raise RuntimeError("Rate limit reached for model `openai/gpt-oss-120b`")
        return await super().structured(task, messages, response_model, **kwargs)


async def _run_interview(client, headers, answers=3):
    sid = (await client.post("/sessions", json=START, headers=headers)).json()["session_id"]
    for _ in range(answers):
        await client.post(f"/sessions/{sid}/answers", json={"text": "my detailed answer"}, headers=headers)
    return sid


async def test_failed_evaluations_are_retried_before_the_report(client, make_user, db_sessionmaker):
    m = InterviewManager(FlakyEvaluatorLLM(failures=2), db_sessionmaker, lambda db: None)
    m.evaluation_retry_wait_s = 0
    app.dependency_overrides[get_interview_manager] = lambda: m
    headers = await make_user()
    sid = await _run_interview(client, headers)
    await m.drain()
    report = (await client.get(f"/sessions/{sid}/report", headers=headers)).json()
    assert report["questions_scored"] == 3 and report["overall_score"] == 75


async def test_unscored_interview_is_never_shown_as_zero(client, make_user, db_sessionmaker):
    m = InterviewManager(FlakyEvaluatorLLM(failures=100), db_sessionmaker, lambda db: None)
    m.evaluation_retry_wait_s = 0
    app.dependency_overrides[get_interview_manager] = lambda: m
    headers = await make_user()
    sid = await _run_interview(client, headers)
    await m.drain()

    report = (await client.get(f"/sessions/{sid}/report", headers=headers)).json()
    assert report["questions_answered"] == 3 and report["questions_scored"] == 0
    assert "couldn't be scored" in report["summary"]
    listed = (await client.get("/sessions", headers=headers)).json()[0]
    assert listed["overall_score"] is None and listed["hiring_signal"] is None
    progress = (await client.get("/users/me/progress", headers=headers)).json()
    assert progress["interviews"] == 0 and progress["points"] == []
