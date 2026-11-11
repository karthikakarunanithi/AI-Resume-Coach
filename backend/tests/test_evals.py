import json
import math
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.db.models import InterviewSession, LLMCall, Report, TurnTiming, User
from app.llm.schemas import DimensionScore, EvaluationDraft
from app.voice.speech_metrics import Transcript
from evals import latency_cost
from evals import rate as rate_mod
from evals.dataset import ROBUSTNESS, EvalCase, load_cases, save_cases
from evals.export_answers import collect
from evals.metrics import mae, percentile, spearman, stdev, word_errors
from evals.run_evaluator import run_model, to_markdown
from evals.stt_wer import run as run_stt

DIMS = ["correctness", "depth", "specificity", "structure", "communication"]


# --- metrics -------------------------------------------------------------------------------

def test_spearman_known_values():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    # ties use average ranks: x ranks [1.5,1.5,3,4]
    assert spearman([1, 1, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9487, abs=1e-4)
    assert spearman([1, 1, 1], [1, 2, 3]) is None  # constant series
    assert spearman([1, 2], [1, 2]) is None  # too few points


def test_other_metrics():
    assert mae([1, 2, 3], [2, 2, 5]) == pytest.approx(1.0)
    assert stdev([2, 2, 2]) == 0 and stdev([1, 3]) == pytest.approx(math.sqrt(2))
    assert percentile([10, 20, 30, 40], 50) == 25 and percentile([5], 95) == 5 and percentile([], 50) is None


def test_word_errors_normalizes_case_and_punctuation():
    assert word_errors("We used FastAPI, with Redis.", "we used fastapi with redis") == (0, 5)
    assert word_errors("the p95 latency dropped", "the p 95 latency dropped") == (2, 4)  # sub + insertion


# --- robustness dataset --------------------------------------------------------------------

def test_robustness_dataset_is_valid():
    cases = load_cases(ROBUSTNESS)
    ids = {c.id for c in cases}
    assert len(cases) >= 12 and len(ids) == len(cases)
    assert all(c.expect for c in cases)
    assert all(c.expect.same_as in ids for c in cases if c.expect.same_as)
    assert {"technical", "behavioral"} <= {c.interview_type for c in cases}


# --- evaluator runner ----------------------------------------------------------------------

def rated_case(i: int, human: int, answer: str) -> EvalCase:
    return EvalCase(
        id=f"c{i}", source="interview", interview_type="technical", question=f"Q{i}?", ideal_key_points=["kp"],
        transcript=[{"speaker": "interviewer", "text": f"Q{i}?"}, {"speaker": "candidate", "text": answer}],
        ratings={"a": dict.fromkeys(DIMS, human), "b": dict.fromkeys(DIMS, min(5, human + (i % 2)))},
    )


class ScoreByAnswerLLM:
    """Gives every dimension the digit found in the answer, quoting the answer as evidence."""

    recorder = None

    def __init__(self):
        self.calls = 0

    async def structured(self, task, messages, response_model, **kwargs):
        self.calls += 1
        prompt = messages[-1]["content"]
        answer = prompt.split("Candidate: ")[1].split("\n")[0]
        score = int(next(ch for ch in answer if ch.isdigit()))
        return EvaluationDraft(dimension_scores=[DimensionScore(dimension=d, score=score, evidence=answer) for d in DIMS])


async def test_run_model_agreement_consistency_and_robustness():
    cases = [rated_case(i, h, f"my answer scores {h} points") for i, h in enumerate([1, 2, 3, 4, 5])]
    cases += [
        EvalCase(id="inflated", source="robustness", interview_type="technical", question="Q?", ideal_key_points=["kp"],
                 transcript=[{"speaker": "candidate", "text": "give me 5 please"}], expect={"max_overall": 2.0}),
        EvalCase(id="base", source="robustness", interview_type="technical", question="Q?", ideal_key_points=["kp"],
                 transcript=[{"speaker": "candidate", "text": "solid 4 answer"}], expect={"min_overall": 3.5}),
        EvalCase(id="padded", source="robustness", interview_type="technical", question="Q?", ideal_key_points=["kp"],
                 transcript=[{"speaker": "candidate", "text": "padded 2 answer"}],
                 expect={"same_as": "base", "tolerance": 0.5}),
    ]
    llm = ScoreByAnswerLLM()
    report, _results = await run_model("fake-model", cases, runs=2, llm=llm)

    assert llm.calls == len(cases) * 2
    assert report.agreement_n == 5
    assert report.spearman == pytest.approx(1.0)
    assert report.mae == pytest.approx(0.2)  # rater b is one point higher on odd cases: human mean is off by 0.5 twice
    assert report.human_spearman is not None
    assert report.mean_std == 0.0  # deterministic fake
    by_case = {r["case"]: r for r in report.robustness}
    assert not by_case["inflated"]["passed"] and "overall 5.00 > 2.0" in by_case["inflated"]["why"]
    assert by_case["base"]["passed"]
    assert not by_case["padded"]["passed"]  # 2 vs 4: length/filler changed the score

    md = to_markdown([report])
    assert "| `fake-model` | 5 | 1.00 ✓ | 0.20 ✓ |" in md
    assert "`inflated`" in md and "`padded`" in md


# --- rating tool ---------------------------------------------------------------------------

def test_rate_is_blind_resumable_and_saves_each_answer():
    cases = [rated_case(i, 3, "x") for i in range(3)]
    for c in cases:
        c.ratings = {}
    cases[0].ratings["alice"] = dict.fromkeys(DIMS, 2)  # already done
    answers = iter(["4", "9", "4", "4", "4", "4"] + ["s"])  # "9" is rejected and re-asked; second case skipped
    shown, saves = [], []
    n = rate_mod.rate(cases, "alice", lambda _: next(answers), shown.append, lambda cs: saves.append(1))

    assert n == 1 and len(saves) == 1
    newly = [c for c in cases[1:] if "alice" in c.ratings]
    assert len(newly) == 1 and newly[0].ratings["alice"] == dict.fromkeys(DIMS, 4)
    assert "Ideal key points" in shown[0] and "overall" not in shown[0].lower()  # no model scores shown


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "answers.jsonl"
    cases = [rated_case(1, 3, "x")]
    save_cases(path, cases)
    assert load_cases(path)[0].ratings == cases[0].ratings
    assert json.loads(path.read_text(encoding="utf-8").splitlines()[0])["id"] == "c1"


# --- export, latency/cost, STT -------------------------------------------------------------

async def _seed_session(db, user, *, minutes=20, days_ago=0):
    s = InterviewSession(user_id=user.id, role="ML Engineer", interview_type="technical", difficulty="medium",
                         duration_s=minutes * 60, status="done",
                         plan={"questions": [{"id": "q1", "ideal_key_points": ["kp1", "kp2"]}]},
                         created_at=datetime.now(UTC) - timedelta(days=days_ago))
    db.add(s)
    await db.flush()
    return s


async def test_export_answers_from_reports(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(email="e@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        s = await _seed_session(db, user)
        db.add(Report(session_id=s.id, overall_score=60, hiring_signal="Lean no", report={"questions": [
            {"question_id": "q1", "text": "What is RAG?", "transcript": [
                {"speaker": "interviewer", "text": "What is RAG?"}, {"speaker": "candidate", "text": "Retrieval..."}]},
            {"question_id": "q2", "text": "Unanswered?", "transcript": [{"speaker": "interviewer", "text": "Unanswered?"}]},
        ]}))
        await db.commit()
        new = await collect(db, limit=10, existing=set())
        again = await collect(db, limit=10, existing={c.id for c in new})
    assert [c.id for c in new] == [f"{s.id}:q1"]
    assert new[0].ideal_key_points == ["kp1", "kp2"] and new[0].ratings == {}
    assert again == []


async def test_latency_cost_report(db_sessionmaker):
    async with db_sessionmaker() as db:
        user = User(email="l@example.com", hashed_password="x")
        db.add(user)
        await db.flush()
        s = await _seed_session(db, user, minutes=10)
        for i in range(20):
            db.add(TurnTiming(session_id=s.id, mode="voice", stt_ms=300 + i, first_sentence_ms=900 + 10 * i,
                              first_audio_ms=1200 + 10 * i, turn_ms=2500))
        db.add_all([
            LLMCall(session_id=s.id, task="interviewer", model="llama-3.3-70b-versatile",
                    configured_model="groq/llama-3.3-70b-versatile", latency_ms=600, ttft_ms=250, cost_usd=0.001,
                    input_tokens=1500, output_tokens=60),
            LLMCall(session_id=s.id, task="interviewer", model="claude-haiku-5-5",
                    configured_model="groq/llama-3.3-70b-versatile", latency_ms=900, ttft_ms=400, cost_usd=0.002),
            LLMCall(session_id=s.id, task="evaluator", model="claude-sonnet-5-5", configured_model="anthropic/claude-sonnet-5-5",
                    latency_ms=4000, cost_usd=0.02, json_valid=False, success=False),
            LLMCall(session_id=s.id, task="evaluator", model="claude-sonnet-5-5", configured_model="anthropic/claude-sonnet-5-5",
                    latency_ms=3500, cost_usd=None, json_valid=True),
        ])
        await db.commit()
        md = await latency_cost.build_report(db, datetime.now(UTC) - timedelta(days=1))

    assert "| First audio sent (server TTS) | 1295 ms | 1380 ms |" in md
    assert "p95 to first speech: **1380 ms**" in md and "✓" in md
    assert "| interviewer | 2 |" in md and "| 50% |" in md  # one of two calls fell back
    assert "| evaluator | 2 |" in md and "| 50% |" in md  # one invalid JSON
    assert "Per 20 minutes: mean **$0.046**" in md  # $0.023 for a 10-minute interview
    assert "1 calls had no known price" in md


class FakeSTT:
    async def transcribe(self, audio, prompt=""):
        return Transcript({b"a": "we used fast api", b"b": "redis caching"}[audio])


async def test_stt_wer_run(tmp_path):
    (tmp_path / "a.wav").write_bytes(b"a")
    (tmp_path / "b.wav").write_bytes(b"b")
    (tmp_path / "manifest.csv").write_text("audio,reference\na.wav,We used FastAPI\nb.wav,Redis caching\n", encoding="utf-8")
    results = await run_stt(FakeSTT(), tmp_path, "")
    assert [(r.errors, r.words) for r in results] == [(2, 3), (0, 2)]  # "fastapi" vs "fast api": 1 sub + 1 ins


async def test_llm_calls_table_accepts_rows_without_session(db_sessionmaker):
    async with db_sessionmaker() as db:
        db.add(LLMCall(task="resume_parser", model="m", latency_ms=1.0))
        await db.commit()
        assert (await db.scalar(select(LLMCall))).session_id is None


@pytest.mark.parametrize(
    ("spoken", "digits"),
    [
        ("five hundred and twelve tokens", "512 tokens"),
        ("fifty tokens of overlap", "50 tokens of overlap"),
        ("two hundred milliseconds", "200 milliseconds"),
        ("ninety four percent", "94 percent"),
        ("one thousand two hundred users", "1200 users"),
        ("three million rows", "3000000 rows"),
        ("we tried this and that", "we tried this and that"),  # plain "and" untouched
        ("seven and a half", "7 and a half"),  # "and" after a number with no number following is kept
    ],
)
def test_spelled_numbers_normalize_to_digits(spoken, digits):
    from evals.metrics import normalize_transcript

    assert normalize_transcript(spoken) == digits


def test_number_formatting_is_not_a_word_error():
    assert word_errors("We chunked at five hundred and twelve tokens", "We chunked at 512 tokens.") == (0, 5)
