"""FastAPI app: the HTTP layer.

Request flow for POST /sessions/{id}/answer:
  HTTP JSON -> Pydantic validates (AnswerIn) -> route function runs
  -> LLM evaluates -> session updated -> Pydantic shapes the reply (AnswerResult) -> JSON

Routes are plain `def` (not async) because the Gemini SDK call here is blocking.
FastAPI runs sync routes in a thread pool, so one slow LLM call doesn't freeze the server.
"""
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

from .llm import LLM, LLMError, build_llm
from .schemas import (
    AnswerIn,
    AnswerResult,
    QuestionOut,
    SessionCreate,
    SessionCreated,
    Summary,
)
from .sessions import Session, SessionStore

load_dotenv()

app = FastAPI(title="Interview Preparation Chatbot", version="1.0.0")

_store = SessionStore()
_llm: LLM | None = None


# Dependencies: routes ask for these, and tests can swap them with
# app.dependency_overrides[...] instead of patching globals.
def get_store() -> SessionStore:
    return _store


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        try:
            _llm = build_llm()
        except LLMError as e:
            raise HTTPException(status_code=500, detail=str(e))
    return _llm


def _question_out(session: Session) -> QuestionOut:
    return QuestionOut(
        index=session.current_index + 1,
        total=len(session.questions),
        text=session.current_question,
    )


def _get_session_or_404(store: SessionStore, session_id: str) -> Session:
    session = store.get(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/sessions", response_model=SessionCreated, status_code=201)
def create_session(
    body: SessionCreate,
    store: SessionStore = Depends(get_store),
    llm: LLM = Depends(get_llm),
):
    """Start an interview: the LLM generates questions tailored to role + experience."""
    try:
        questions = llm.generate_questions(body.role, body.experience_level, body.skills, body.num_questions)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    session = store.create(body.role, body.experience_level, body.skills, questions)
    return SessionCreated(session_id=session.id, question=_question_out(session))


@app.post("/sessions/{session_id}/answer", response_model=AnswerResult)
def submit_answer(
    session_id: str,
    body: AnswerIn,
    store: SessionStore = Depends(get_store),
    llm: LLM = Depends(get_llm),
):
    """Evaluate the answer to the current question, then hand back the next one."""
    session = _get_session_or_404(store, session_id)
    if session.finished:
        raise HTTPException(status_code=409, detail="Interview already finished; fetch the summary")
    try:
        evaluation = llm.evaluate(session.role, session.level, session.current_question, body.answer)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e))
    session.record(body.answer, evaluation)
    return AnswerResult(
        evaluation=evaluation,
        finished=session.finished,
        next_question=None if session.finished else _question_out(session),
    )


@app.get("/sessions/{session_id}/summary", response_model=Summary)
def get_summary(
    session_id: str,
    store: SessionStore = Depends(get_store),
    llm: LLM = Depends(get_llm),
):
    """Final report: scores are averaged in code; the LLM only writes the commentary."""
    session = _get_session_or_404(store, session_id)
    if not session.finished:
        raise HTTPException(status_code=409, detail="Interview not finished yet")
    if session.summary is None:
        evals = session.evaluations
        n = len(evals)
        averages = {
            "relevance": round(sum(e.relevance for e in evals) / n, 1),
            "clarity": round(sum(e.clarity for e in evals) / n, 1),
            "technical_depth": round(sum(e.technical_depth for e in evals) / n, 1),
        }
        overall = round(sum(averages.values()) / len(averages), 1)
        try:
            text = llm.summarize(session.role, session.level, session.transcript(), averages)
        except LLMError as e:
            raise HTTPException(status_code=502, detail=str(e))
        session.summary = Summary(overall_score=overall, average_scores=averages, **text)
    return session.summary


# Serve the tiny frontend at "/". Mounted LAST so it doesn't shadow the API routes.
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
