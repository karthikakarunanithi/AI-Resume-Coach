import uuid
from collections import Counter

import pytest

from app.llm.schemas import CandidateProfile, JDAnalysis
from app.rag.question_bank import QuestionRow, load_question_bank
from app.rag.retriever import build_query, rrf_fuse

HEADER = "text,role,topic,type,difficulty,ideal_key_points\n"


def test_rrf_rewards_agreement_between_sources():
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fused = rrf_fuse({"vector": [a, b], "keyword": [c, b]})
    assert fused[0][0] == b  # ranked 2nd in both beats 1st in only one
    assert fused[0][2] == ["vector", "keyword"]
    assert fused[0][1] == pytest.approx(2 / 62)
    assert {f[0] for f in fused} == {a, b, c}


def test_build_query_combines_role_jd_and_resume_skills():
    jd = JDAnalysis(required_skills=["Python", "RAG"], nice_to_have_skills=["Docker"], responsibilities=["Build agents"])
    profile = CandidateProfile(skills=["python", "LangGraph"])
    q = build_query("GenAI Developer", jd, profile)
    assert q.keywords == ["GenAI Developer", "Python", "RAG", "Docker", "LangGraph"]  # case-insensitive dedupe
    assert "Required skills: Python, RAG." in q.text
    assert "Build agents" in q.text


def test_build_query_role_only():
    q = build_query("ML Engineer")
    assert q.keywords == ["ML Engineer"]


def test_question_row_parses_key_points_and_stable_id():
    row = QuestionRow.model_validate({
        "text": "What is RAG?", "role": "genai", "topic": "rag", "type": "technical",
        "difficulty": "1", "ideal_key_points": "Retrieve documents | Ground the answer | Reduces hallucination",
    })
    assert row.ideal_key_points == ["Retrieve documents", "Ground the answer", "Reduces hallucination"]
    same = row.model_copy(update={"text": "what is  RAG"})
    assert row.id == same.id
    assert row.embedding_text == "rag: What is RAG?"


def test_load_question_bank_reports_bad_rows_and_duplicates(tmp_path):
    path = tmp_path / "bank.csv"
    path.write_text(
        HEADER
        + '"What is a vector database?",genai,embeddings_vector_db,technical,2,"Stores embeddings | ANN search"\n'
        + '"What is a vector database",genai,embeddings_vector_db,technical,2,"Stores embeddings | ANN search"\n'
        + '"Explain bias and variance?",unknown_track,ml_fundamentals,technical,9,"only one point"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError) as e:
        load_question_bank(path)
    msg = str(e.value)
    assert "line 3: duplicate of line 2" in msg
    assert "line 4" in msg


def test_shipped_question_bank_is_valid_and_balanced():
    rows = load_question_bank()  # raises on any invalid row or duplicate
    assert len(rows) >= 500
    tracks = Counter(r.role for r in rows)
    assert set(tracks) == {"genai", "ml", "backend", "data", "general"}
    assert min(tracks.values()) >= 80
    assert {"technical", "behavioral", "hr", "system_design"} <= {r.type for r in rows}
    difficulties = Counter(r.difficulty for r in rows)
    assert all(difficulties[d] >= 0.05 * len(rows) for d in range(1, 6))
