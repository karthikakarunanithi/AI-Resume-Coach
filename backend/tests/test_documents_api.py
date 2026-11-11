import pytest

from app.config import get_settings
from app.llm.deps import get_llm
from app.llm.schemas import CandidateProfile, JDAnalysis
from app.main import app
from tests.test_text_extract import make_pdf

RESUME_TEXT = (
    "Karthika K  karthika.k@topgeo.ai  +91 98765 43210\n"
    "Skills: Python, FastAPI, LangGraph, Docker\n"
    "Project: Deepfake detection with CNN + LSTM, 94% accuracy\n"
    "Experience: AI Engineer at TopGeo, 2024-present"
)
JD_TEXT = "We are hiring a GenAI Developer. Must have Python, RAG and LangChain. Docker is a plus. " * 2


class FakeLLM:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[str, list[dict]]] = []

    async def structured(self, task, messages, response_model, **kwargs):
        self.calls.append((task, messages))
        if self.fail:
            raise RuntimeError("provider down")
        if response_model is CandidateProfile:
            return CandidateProfile(name="Karthika K", years_experience=1.5, skills=["Python", "FastAPI"])
        assert response_model is JDAnalysis
        return JDAnalysis(title="GenAI Developer", required_skills=["Python", "RAG", "LangChain"])


@pytest.fixture
def fake_llm(tmp_path, monkeypatch):
    llm = FakeLLM()
    app.dependency_overrides[get_llm] = lambda: llm
    monkeypatch.setattr(get_settings(), "upload_dir", tmp_path)
    return llm


def _pdf_upload(text: str = RESUME_TEXT):
    return {"file": ("resume.pdf", make_pdf(text), "application/pdf")}


async def test_upload_resume_parses_and_stores(client, make_user, fake_llm, tmp_path):
    headers = await make_user()
    resp = await client.post("/resumes", files=_pdf_upload(), headers=headers)

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["parsed_profile"]["skills"] == ["Python", "FastAPI"]
    assert len(list(tmp_path.rglob("*.pdf"))) == 1

    task, messages = fake_llm.calls[0]
    assert task == "resume_parser"
    sent = messages[-1]["content"]
    assert "LangGraph" in sent
    assert "karthika.k@topgeo.ai" not in sent and "98765" not in sent

    listed = (await client.get("/resumes", headers=headers)).json()
    assert [r["id"] for r in listed] == [body["id"]]


async def test_resumes_are_private_per_user(client, make_user, fake_llm):
    await client.post("/resumes", files=_pdf_upload(), headers=await make_user("a@example.com"))
    other = await make_user("b@example.com")
    assert (await client.get("/resumes", headers=other)).json() == []


async def test_upload_requires_auth(client, fake_llm):
    assert (await client.post("/resumes", files=_pdf_upload())).status_code == 401


async def test_unsupported_file_type(client, make_user, fake_llm):
    files = {"file": ("resume.txt", b"plain text resume", "text/plain")}
    resp = await client.post("/resumes", files=files, headers=await make_user())
    assert resp.status_code == 415
    assert fake_llm.calls == []


async def test_pdf_without_text_rejected(client, make_user, fake_llm):
    resp = await client.post("/resumes", files=_pdf_upload(" "), headers=await make_user())
    assert resp.status_code == 422
    assert fake_llm.calls == []


async def test_oversized_upload_rejected(client, make_user, fake_llm, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    resp = await client.post("/resumes", files=_pdf_upload(), headers=await make_user())
    assert resp.status_code == 413


async def test_llm_failure_returns_502_and_stores_nothing(client, make_user, fake_llm, tmp_path):
    fake_llm.fail = True
    headers = await make_user()
    resp = await client.post("/resumes", files=_pdf_upload(), headers=headers)
    assert resp.status_code == 502
    assert list(tmp_path.rglob("*")) == []
    assert (await client.get("/resumes", headers=headers)).json() == []


async def test_create_and_list_job_description(client, make_user, fake_llm):
    headers = await make_user()
    resp = await client.post("/job-descriptions", json={"raw_text": JD_TEXT}, headers=headers)

    assert resp.status_code == 201, resp.text
    assert resp.json()["analysis"]["required_skills"] == ["Python", "RAG", "LangChain"]
    assert fake_llm.calls[0][0] == "jd_analyzer"
    listed = (await client.get("/job-descriptions", headers=headers)).json()
    assert listed[0]["analysis"]["title"] == "GenAI Developer"


async def test_job_description_too_short(client, make_user, fake_llm):
    resp = await client.post("/job-descriptions", json={"raw_text": "Python dev"}, headers=await make_user())
    assert resp.status_code == 422
