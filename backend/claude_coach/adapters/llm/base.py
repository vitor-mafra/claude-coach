"""LLM provider protocol and message types.

Provider implementations live in `claude_coach.adapters.llm.providers`.
The router (`claude_coach.adapters.llm.router`) picks one per task_id.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

Role = Literal["user", "assistant"]


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class ImagePart:
    path: Path
    media_type: str = "image/png"


ContentPart = TextPart | ImagePart


@dataclass
class Message:
    role: Role
    parts: list[ContentPart] = field(default_factory=list)

    @classmethod
    def user(cls, text: str) -> "Message":
        return cls(role="user", parts=[TextPart(text=text)])


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str
    duration_ms: int


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        system: str | None = None,
        response_format: str | None = None,
    ) -> LLMResult: ...
