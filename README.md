# Interview Preparation Chatbot

FastAPI backend + Gemini. Generates role-tailored interview questions, scores each answer on
relevance / clarity / technical depth, and returns a session summary.

New to the project? Read `LEARN.md` first.

## Run it

1. `python -m venv .venv` then activate it
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and put your Gemini API key in it
   (or set `LLM_BACKEND=mock` to try it with no key)
4. `uvicorn app.main:app --reload`
5. Open https://interview-prep-chatbot-1.onrender.com/

## Test it

`pytest` (uses a mock LLM: no key or internet needed)

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions` | start an interview (role, experience_level, skills, num_questions) |
| POST | `/sessions/{id}/answer` | submit an answer, get scores + next question |
| GET | `/sessions/{id}/summary` | final report (after the last answer) |
| GET | `/health` | liveness check |
