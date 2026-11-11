import pytest

from app.llm.schemas import AnswerEvaluation, CoachNarrative, PracticeDay, SampleAnswer
from app.services.report import build_report, hiring_signal, to_100

STATE = {
    "session_id": "s1",
    "config": {"role": "GenAI Developer", "interview_type": "technical", "difficulty": "medium",
               "duration_min": 10, "company_type": "startup"},
    "profile": {"name": "Karthika K", "skills": ["Python"]},
    "plan": [
        {"id": f"q{i}", "text": f"Question {i}?", "topic": "rag", "difficulty": 2, "source": "bank",
         "ideal_key_points": ["kp"]}
        for i in (1, 2, 3)
    ],
    "finished_questions": ["q1", "q2"],
    "turns": [
        {"speaker": "interviewer", "text": "Question 1?", "question_id": "q1", "at_s": 0},
        {"speaker": "candidate", "text": "Answer one.", "question_id": "q1", "at_s": 5},
        {"speaker": "interviewer", "text": "Question 2?", "question_id": "q2", "at_s": 60},
        {"speaker": "candidate", "text": "Answer two.", "question_id": "q2", "at_s": 65},
    ],
}


def evaluation(qid: str, overall: float, score: int) -> AnswerEvaluation:
    dims = ["correctness", "depth", "specificity", "structure", "communication"]
    return AnswerEvaluation(
        question_id=qid, scores=dict.fromkeys(dims, score), evidence=dict.fromkeys(dims, ""),
        strengths=[f"{qid} strength"], improvements=[f"{qid} improvement"], missed_key_points=["kp"], overall=overall,
    )


NARRATIVE = CoachNarrative(
    summary="Solid start.", strengths=["a", "b", "c"], improvements=["x", "y", "z"],
    practice_plan=[PracticeDay(day=2, focus="RAG", tasks=["t"]), PracticeDay(day=1, focus="Basics", tasks=["t"])],
    sample_answers=[SampleAnswer(question_id="q2", answer="A better answer."), SampleAnswer(question_id="q9", answer="?")],
)


class CoachLLM:
    def __init__(self, result):
        self.result = result
        self.prompts = []

    async def structured(self, task, messages, response_model, **kwargs):
        assert task == "coach"
        self.prompts.append(messages[-1]["content"])
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.mark.parametrize(("x", "y"), [(1.0, 0), (3.0, 50), (5.0, 100), (4.2, 80)])
def test_to_100(x, y):
    assert to_100(x) == y


@pytest.mark.parametrize(("score", "signal"), [(80, "Strong"), (79, "Lean yes"), (65, "Lean yes"), (45, "Lean no"), (10, "Not yet")])
def test_hiring_signal(score, signal):
    assert hiring_signal(score) == signal


async def test_report_numbers_come_from_code_and_narrative_from_coach():
    llm = CoachLLM(NARRATIVE)
    report = await build_report(llm, STATE, {"q1": evaluation("q1", 4.0, 4), "q2": evaluation("q2", 2.0, 2)})

    assert report.overall_score == 50  # mean 3.0 on the 1-5 scale
    assert report.hiring_signal == "Lean no"
    assert report.dimension_scores["depth"] == 3.0
    assert (report.questions_planned, report.questions_answered) == (3, 2)
    assert [q.score for q in report.questions] == [75, 25]
    assert report.questions[1].sample_answer == "A better answer."
    assert [d.day for d in report.practice_plan] == [1, 2]
    assert report.coach_generated
    prompt = llm.prompts[0]
    assert prompt.index('"question_id": "q2"') < prompt.index('"question_id": "q1"')  # weakest first
    assert "Overall score: 50/100 (Lean no)" in prompt


async def test_coach_failure_falls_back():
    report = await build_report(CoachLLM(RuntimeError("down")), STATE, {"q1": evaluation("q1", 4.0, 4), "q2": None})
    assert not report.coach_generated
    assert report.overall_score == 75  # failed evaluation is excluded, not counted as zero
    assert report.questions[1].evaluated is False
    assert report.strengths == ["q1 strength"]


async def test_no_answers_skips_coach():
    llm = CoachLLM(NARRATIVE)
    report = await build_report(llm, {**STATE, "finished_questions": []}, {})
    assert (report.overall_score, report.hiring_signal, report.questions) == (0, "Not yet", [])
    assert llm.prompts == []
