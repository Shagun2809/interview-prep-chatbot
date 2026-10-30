"""In-memory session storage.

Simple on purpose: a dict guarded by a lock. Limitation to be able to explain in an
interview: data disappears on restart and is not shared between multiple server
processes. The fix is to move the same interface onto Redis or Postgres.
"""
import threading
import uuid
from dataclasses import dataclass, field

from .schemas import Evaluation, Summary


@dataclass
class Session:
    id: str
    role: str
    level: str
    skills: list[str]
    questions: list[str]
    answers: list[str] = field(default_factory=list)
    evaluations: list[Evaluation] = field(default_factory=list)
    summary: Summary | None = None  # cached after first computation

    @property
    def finished(self) -> bool:
        return len(self.evaluations) >= len(self.questions)

    @property
    def current_index(self) -> int:
        return len(self.evaluations)

    @property
    def current_question(self) -> str:
        return self.questions[self.current_index]

    def record(self, answer: str, evaluation: Evaluation) -> None:
        self.answers.append(answer)
        self.evaluations.append(evaluation)

    def transcript(self) -> str:
        lines = []
        for i, (q, a, e) in enumerate(zip(self.questions, self.answers, self.evaluations), 1):
            lines.append(
                f"Q{i}: {q}\nA{i}: {a}\n"
                f"Scores: relevance={e.relevance}, clarity={e.clarity}, technical_depth={e.technical_depth}"
            )
        return "\n\n".join(lines)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def create(self, role: str, level: str, skills: list[str], questions: list[str]) -> Session:
        session = Session(id=uuid.uuid4().hex, role=role, level=level, skills=skills, questions=questions)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_id)
