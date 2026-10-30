import pytest
from fastapi.testclient import TestClient

from app.llm import LLMError, MockLLM
from app.main import app, get_llm, get_store
from app.sessions import SessionStore


@pytest.fixture()
def client():
    # Fresh store + fake LLM for every test: no network, no API key, repeatable.
    store = SessionStore()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: MockLLM()
    yield TestClient(app)
    app.dependency_overrides.clear()


def start(client, n=2):
    r = client.post(
        "/sessions",
        json={"role": "ML Engineer", "experience_level": "fresher", "skills": ["Python"], "num_questions": n},
    )
    assert r.status_code == 201
    return r.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_full_interview_flow(client):
    data = start(client, n=2)
    sid = data["session_id"]
    assert data["question"]["index"] == 1 and data["question"]["total"] == 2

    r1 = client.post(f"/sessions/{sid}/answer", json={"answer": "I built a retrieval system with embeddings and FAISS indexing."})
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["finished"] is False
    assert body1["next_question"]["index"] == 2
    assert 1 <= body1["evaluation"]["clarity"] <= 10

    r2 = client.post(f"/sessions/{sid}/answer", json={"answer": "I validate with held-out data and track precision and recall."})
    assert r2.json()["finished"] is True
    assert r2.json()["next_question"] is None

    s = client.get(f"/sessions/{sid}/summary")
    assert s.status_code == 200
    summary = s.json()
    assert set(summary["average_scores"]) == {"relevance", "clarity", "technical_depth"}
    assert 1 <= summary["overall_score"] <= 10
    assert summary["strengths"] and summary["improvements"]


def test_summary_before_finish_is_409(client):
    sid = start(client)["session_id"]
    assert client.get(f"/sessions/{sid}/summary").status_code == 409


def test_answer_after_finish_is_409(client):
    sid = start(client, n=1)["session_id"]
    assert client.post(f"/sessions/{sid}/answer", json={"answer": "something"}).status_code == 200
    assert client.post(f"/sessions/{sid}/answer", json={"answer": "again"}).status_code == 409


def test_unknown_session_is_404(client):
    assert client.post("/sessions/nope/answer", json={"answer": "x"}).status_code == 404
    assert client.get("/sessions/nope/summary").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "x", "experience_level": "fresher"},  # role too short
        {"role": "ML Engineer", "experience_level": "wizard"},  # not an allowed level
        {"role": "ML Engineer", "experience_level": "fresher", "num_questions": 99},  # too many
    ],
)
def test_invalid_create_is_422(client, payload):
    assert client.post("/sessions", json=payload).status_code == 422


def test_empty_answer_is_422(client):
    sid = start(client)["session_id"]
    assert client.post(f"/sessions/{sid}/answer", json={"answer": ""}).status_code == 422


def test_llm_failure_becomes_502(client):
    class Broken(MockLLM):
        def generate_questions(self, *a, **k):
            raise LLMError("boom")

    app.dependency_overrides[get_llm] = lambda: Broken()
    r = client.post("/sessions", json={"role": "ML Engineer", "experience_level": "fresher"})
    assert r.status_code == 502
