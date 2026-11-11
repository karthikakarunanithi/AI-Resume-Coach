import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from app.db.models import InterviewSession, Report, TurnTiming, User
from app.main import app
from app.services.interviews import InterviewManager, InterviewNotActiveError
from app.voice.session import VoiceSession
from app.voice.speech_metrics import Transcript, Word
from tests.test_sessions_api import START, FakeLLM

ANSWER = "Um, I used FastAPI with Redis caching and the p95 latency dropped to 200 ms."


class FakeSocket:
    def __init__(self):
        self.messages: list[dict | bytes] = []

    async def send_json(self, data):
        self.messages.append(data)

    async def send_bytes(self, data):
        self.messages.append(data)

    def types(self) -> list[str]:
        return [m["type"] if isinstance(m, dict) else "<bytes>" for m in self.messages]

    def of(self, kind: str) -> list[dict]:
        return [m for m in self.messages if isinstance(m, dict) and m["type"] == kind]


class FakeSTT:
    def __init__(self, text=ANSWER, fail=False):
        self.text, self.fail, self.prompts = text, fail, []

    async def transcribe(self, audio, prompt=""):
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("stt down")
        words = [Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(self.text.split())]
        return Transcript(self.text, words, duration_s=len(words) * 0.4)


class FakeTTS:
    mode, mime = "server", "audio/mpeg"

    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on

    async def synthesize(self, text):
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("tts down")
        return f"AUDIO:{text}".encode()


@pytest.fixture
async def started(db_sessionmaker):
    """A running interview owned by a fresh user, plus its manager."""
    manager = InterviewManager(FakeLLM(), db_sessionmaker, lambda db: None)
    async with db_sessionmaker() as db:
        user = User(email="v@example.com", hashed_password="x")
        db.add(user)
        await db.commit()
        sid, _ = await manager.start(db, user.id, {**START, "company_type": "startup"})
    return manager, user.id, sid


async def test_voice_turn_streams_captions_sentences_and_audio(started, db_sessionmaker):
    manager, user_id, sid = started
    ws, stt = FakeSocket(), FakeSTT()
    session = VoiceSession(ws, manager, user_id, sid, stt, FakeTTS())

    await session.open()
    ready = ws.messages[0]
    assert {k: ready[k] for k in ("type", "tts", "question_id", "question_number", "total_questions")} == {
        "type": "ready", "tts": "server", "question_id": "q1", "question_number": 1, "total_questions": 3}
    assert 0 < ready["time_left_s"] <= 600
    assert ws.of("ai_sentence")[0] == {"type": "ai_sentence", "seq": 0, "text": "Next one."}  # opening replayed
    assert ws.messages[-1]["type"] == "turn_end" and ws.messages[-1]["question_id"] == "q1"  # client may listen now

    ws.messages.clear()
    await session.handle_audio(b"RIFF-fake-wav")
    assert ws.types()[:3] == ["status", "transcript_final", "status"]
    assert ws.of("transcript_final")[0]["text"] == ANSWER
    assert "".join(m["text"] for m in ws.of("ai_text_delta")) == "Next one."
    sentence = ws.of("ai_sentence")[0]
    assert sentence["seq"] == 1  # numbering continues across turns
    i = ws.messages.index(sentence)
    assert ws.messages[i + 1] == {"type": "ai_audio", "seq": 1, "mime": "audio/mpeg"}
    assert ws.messages[i + 2] == b"AUDIO:Next one."
    turn_end = ws.messages[-1]
    assert (turn_end["type"], turn_end["question_id"], turn_end["done"], turn_end["question_number"]) == (
        "turn_end", "q2", False, 2)
    assert stt.prompts[0].startswith("Um, so")

    # finish: two more answers end the 3-question interview
    await session.handle_text("Second answer.")
    await session.handle_audio(b"RIFF")
    assert ws.of("interview_end") and session.done
    await manager.drain()

    async with db_sessionmaker() as db:
        report = await db.scalar(select(Report).where(Report.session_id == sid))
        speech = report.report["speech"]
        assert speech["filler_counts"] == {"um": 2} and speech["total_words"] == 30
        assert set(speech["answer_seconds"]) == {"q1", "q3"}  # q2 was typed
        assert (await db.get(InterviewSession, sid)).status == "done"
        timings = list(await db.scalars(select(TurnTiming).order_by(TurnTiming.created_at)))
        assert sorted(t.mode for t in timings) == ["text", "voice", "voice"]
        voice = next(t for t in timings if t.mode == "voice")
        assert voice.stt_ms is not None and voice.first_audio_ms is not None and voice.turn_ms >= voice.first_sentence_ms


async def test_no_speech_and_stt_failure_do_not_advance(started):
    manager, user_id, sid = started
    ws = FakeSocket()
    session = VoiceSession(ws, manager, user_id, sid, FakeSTT(text="  "), FakeTTS())
    await session.handle_audio(b"RIFF")
    assert ws.types()[-1] == "no_speech"

    session.stt = FakeSTT(fail=True)
    await session.handle_audio(b"RIFF")
    assert ws.types()[-1] == "error"
    assert (await manager.active_state(user_id, sid))["current_q_index"] == 0


async def test_tts_failure_falls_back_to_text(started):
    manager, user_id, sid = started
    ws = FakeSocket()
    session = VoiceSession(ws, manager, user_id, sid, FakeSTT(), FakeTTS(fail_on="Next"))
    await session.handle_text("An answer.")
    assert {"type": "ai_audio_failed", "seq": 0} in ws.messages


async def test_end_early_over_voice(started):
    manager, user_id, sid = started
    ws = FakeSocket()
    session = VoiceSession(ws, manager, user_id, sid, FakeSTT(), FakeTTS())
    await session.handle_end()
    assert session.done and ws.of("interview_end")
    assert "stop here" in " ".join(m["text"] for m in ws.of("ai_sentence"))


async def test_open_rejects_other_users_session(started):
    manager, _, sid = started
    with pytest.raises(InterviewNotActiveError):
        await VoiceSession(FakeSocket(), manager, uuid.uuid4(), sid, FakeSTT(), FakeTTS()).open()


def test_websocket_rejects_bad_token():
    url = f"/ws/sessions/{uuid.uuid4()}?token=not-a-jwt"
    with TestClient(app) as client, pytest.raises(WebSocketDisconnect) as e, client.websocket_connect(url) as ws:
        ws.receive_json()
    assert e.value.code == 4401


class StubUserManager:
    def __init__(self, user):
        self.user = user

    def parse_id(self, value):
        return uuid.UUID(value)

    async def get(self, user_id):
        return self.user


class StubManager:
    """Just enough InterviewManager for the route loop: two questions, then done."""

    def __init__(self):
        self.answers: list[tuple[str, bool, bool]] = []
        self.timings: list[dict] = []

    async def active_state(self, user_id, session_id):
        speaker = {"speaker": "interviewer", "text": "Hi! First question?", "question_id": "q1", "at_s": 0}
        return {"profile": {}, "plan": [{"id": "q1"}, {"id": "q2"}], "current_q_index": 0, "turns": [speaker],
                "time_budget_s": 600, "started_at": __import__("time").time()}

    async def answer(self, user_id, session_id, text, end=False, on_event=None, speech=None, timing=None):
        from app.agents.runner import TurnResult

        self.answers.append((text, end, speech is not None))
        self.timings.append(timing)
        done = end or len(self.answers) == 2
        await on_event({"type": "say_delta", "text": "Thanks. " if done else "Next question?"})
        await on_event({"type": "say_end"})
        return TurnResult(spoken=[], done=done, question_id=None if done else "q2")


def test_websocket_route_end_to_end():
    from app.api.sessions import get_interview_manager
    from app.auth.users import get_jwt_strategy, get_user_manager
    from app.voice.stt import get_stt
    from app.voice.tts import BrowserTTS, get_tts

    user = User(id=uuid.uuid4(), email="ws@example.com", hashed_password="x", is_active=True)
    manager = StubManager()
    app.dependency_overrides.update({
        get_user_manager: lambda: StubUserManager(user), get_interview_manager: lambda: manager,
        get_stt: lambda: FakeSTT(), get_tts: lambda: BrowserTTS(),
    })
    try:
        import asyncio

        token = asyncio.run(get_jwt_strategy().write_token(user))
        with TestClient(app) as client, client.websocket_connect(f"/ws/sessions/{uuid.uuid4()}?token={token}") as ws:
            ready = ws.receive_json()
            assert (ready["type"], ready["tts"], ready["question_id"], ready["total_questions"]) == ("ready", "browser", "q1", 2)
            assert ws.receive_json()["type"] == "ai_text_delta"
            assert ws.receive_json() == {"type": "ai_sentence", "seq": 0, "text": "Hi!"}
            assert ws.receive_json() == {"type": "ai_sentence", "seq": 1, "text": "First question?"}
            assert ws.receive_json()["type"] == "turn_end"

            ws.send_text("not json")
            assert ws.receive_json() == {"type": "error", "message": "Invalid message"}
            ws.send_json({"type": "dance"})
            assert ws.receive_json()["message"] == "Unknown message type: dance"

            ws.send_bytes(b"RIFF-part-1")  # audio may arrive in several frames
            ws.send_bytes(b"-part-2")
            ws.send_json({"type": "audio_end"})
            seen = []
            while (msg := ws.receive_json())["type"] != "turn_end":
                seen.append(msg["type"])
            assert seen[:3] == ["status", "transcript_final", "status"] and msg["question_id"] == "q2"

            ws.send_json({"type": "text_answer", "text": "Typed answer."})
            while (msg := ws.receive_json())["type"] != "interview_end":
                pass
        assert manager.answers == [(ANSWER, False, True), ("Typed answer.", False, False)]
        voice, text = manager.timings
        assert voice["mode"] == "voice" and voice["stt_ms"] >= 0 and voice["first_sentence_ms"] <= voice["turn_ms"]
        assert text["mode"] == "text" and "stt_ms" not in text
    finally:
        app.dependency_overrides.clear()
