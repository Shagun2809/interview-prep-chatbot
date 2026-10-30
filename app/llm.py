"""The LLM layer.

`LLM` is a Protocol (an interface): anything with these three methods can be plugged in.
- GeminiLLM  -> real calls to the Gemini API
- MockLLM    -> deterministic fake, used in tests and for running without an API key

The rest of the app only talks to the interface, so swapping providers (or testing)
never touches the routes. That is the main design idea of this file.
"""
import json
import os
import re
from typing import Callable, Protocol, TypeVar

from .prompts import evaluation_prompt, questions_prompt, summary_prompt
from .schemas import Evaluation

T = TypeVar("T")


class LLMError(Exception):
    """Raised when the model call fails or returns something unusable."""


class LLM(Protocol):
    def generate_questions(self, role: str, level: str, skills: list[str], n: int) -> list[str]: ...

    def evaluate(self, role: str, level: str, question: str, answer: str) -> Evaluation: ...

    def summarize(self, role: str, level: str, transcript: str, scores: dict[str, float]) -> dict: ...


# --------------------------------------------------------------------------- Gemini
class GeminiLLM:
    def __init__(self, api_key: str, model: str):
        from google import genai  # imported here so tests/mocks don't need the package

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _ask(self, prompt: str, parse: Callable[[dict], T], attempts: int = 2) -> T:
        """Call the model, parse + validate its JSON. Retry once if the output is malformed."""
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                resp = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config={"response_mime_type": "application/json", "temperature": 0.4},
                )
                return parse(json.loads(resp.text))
            except (ValueError, KeyError, TypeError) as e:
                # JSONDecodeError and pydantic's ValidationError are both ValueErrors:
                # the model replied, but not in the shape we asked for -> retry.
                last_error = e
            except Exception as e:  # network, quota, auth ... -> don't retry blindly
                raise LLMError(f"Gemini call failed: {e}") from e
        raise LLMError(f"Model returned invalid output after {attempts} attempts: {last_error}")

    def generate_questions(self, role, level, skills, n):
        def parse(data: dict) -> list[str]:
            qs = [q.strip() for q in data["questions"] if isinstance(q, str) and q.strip()]
            if not qs:
                raise ValueError("no questions returned")
            return qs[:n]

        return self._ask(questions_prompt(role, level, skills, n), parse)

    def evaluate(self, role, level, question, answer):
        return self._ask(
            evaluation_prompt(role, level, question, answer),
            lambda data: Evaluation.model_validate(data),  # enforces 1-10 ranges
        )

    def summarize(self, role, level, transcript, scores):
        def parse(data: dict) -> dict:
            return {
                "strengths": [str(s) for s in data["strengths"]][:3],
                "improvements": [str(s) for s in data["improvements"]][:3],
                "overall_feedback": str(data["overall_feedback"]),
            }

        return self._ask(summary_prompt(role, level, transcript), parse)


# --------------------------------------------------------------------------- Mock
def _clamp(x: int) -> int:
    return max(1, min(10, x))


class MockLLM:
    """Deterministic stand-in. Not smart, just consistent, so tests are repeatable."""

    TEMPLATES = [
        "Tell me about yourself and why you want to work as a {role}.",
        "Explain a project where you used {skill} and what you personally built.",
        "How would you debug a model or service that suddenly performs worse in production?",
        "What trade-offs would you consider when choosing between two approaches for a {role} task?",
        "Describe how you would explain a technical result to a non-technical stakeholder.",
        "How do you validate that your work is correct before shipping it?",
        "Walk me through designing a small system end to end for a {role}.",
        "What is the hardest bug you have fixed, and how did you find it?",
        "How do you keep learning new tools relevant to {role} work?",
        "Where do you see weaknesses in your own skills, and how are you improving them?",
    ]

    def generate_questions(self, role, level, skills, n):
        skill = skills[0] if skills else "your main tool"
        return [t.format(role=role, skill=skill) for t in self.TEMPLATES[:n]]

    def evaluate(self, role, level, question, answer):
        words = re.findall(r"[a-zA-Z']+", answer.lower())
        q_words = {w for w in re.findall(r"[a-zA-Z']+", question.lower()) if len(w) > 3}
        overlap = len(q_words & set(words))
        long_words = sum(1 for w in words if len(w) >= 9)
        relevance = _clamp(2 + overlap * 2)
        clarity = _clamp(2 + len(words) // 8)
        depth = _clamp(2 + long_words)
        return Evaluation(
            relevance=relevance,
            clarity=clarity,
            technical_depth=depth,
            feedback=f"(mock) {len(words)} words, {overlap} question terms reused. "
            "Add specifics such as tools, numbers and trade-offs.",
        )

    def summarize(self, role, level, transcript, scores):
        strengths = [f"Good {k.replace('_', ' ')}" for k, v in scores.items() if v >= 7]
        improvements = [f"Improve {k.replace('_', ' ')}" for k, v in scores.items() if v < 7]
        return {
            "strengths": strengths or ["Completed the whole session"],
            "improvements": improvements or ["Keep practising with harder questions"],
            "overall_feedback": "(mock) Summary generated from the average scores.",
        }


# --------------------------------------------------------------------------- factory
def build_llm() -> LLM:
    backend = os.environ.get("LLM_BACKEND", "gemini").lower()
    if backend == "mock":
        return MockLLM()
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise LLMError("GEMINI_API_KEY is not set. Add it to .env, or run with LLM_BACKEND=mock.")
    return GeminiLLM(api_key=key, model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))
