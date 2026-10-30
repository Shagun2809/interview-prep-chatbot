"""Pydantic models = the "contract" of the API.

FastAPI uses these to (1) validate incoming JSON, (2) shape outgoing JSON,
and (3) auto-generate the /docs page. Bad input never reaches our logic.
"""
from typing import Literal

from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    role: str = Field(min_length=2, max_length=100, examples=["Machine Learning Engineer"])
    experience_level: Literal["fresher", "junior", "mid", "senior"]
    skills: list[str] = Field(default_factory=list, max_length=15)
    num_questions: int = Field(default=5, ge=1, le=10)


class QuestionOut(BaseModel):
    index: int  # 1-based, for display
    total: int
    text: str


class SessionCreated(BaseModel):
    session_id: str
    question: QuestionOut


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)


class Evaluation(BaseModel):
    """Scores for one answer, on the three criteria from the project description."""

    relevance: int = Field(ge=1, le=10)
    clarity: int = Field(ge=1, le=10)
    technical_depth: int = Field(ge=1, le=10)
    feedback: str


class AnswerResult(BaseModel):
    evaluation: Evaluation
    finished: bool
    next_question: QuestionOut | None = None


class Summary(BaseModel):
    overall_score: float
    average_scores: dict[str, float]
    strengths: list[str]
    improvements: list[str]
    overall_feedback: str
