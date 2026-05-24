import base64
import time
from pathlib import Path

import anthropic

from claude_coach.adapters.llm.base import ImagePart, LLMResult, Message, TextPart
from claude_coach.config import settings


def _encode_image(path: Path, media_type: str) -> dict:
    with path.open("rb") as f:
        data = base64.standard_b64encode(f.read()).decode("utf-8")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data},
    }


class ClaudeProvider:
    name = "claude"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to .env to use the Claude provider."
            )
        self.client = anthropic.Anthropic(api_key=key)

    def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        system: str | None = None,
        response_format: str | None = None,  # noqa: ARG002 -- claude ignores this hint
    ) -> LLMResult:
        api_messages: list[dict] = []
        for msg in messages:
            content: list[dict] = []
            for part in msg.parts:
                if isinstance(part, TextPart):
                    content.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    content.append(_encode_image(part.path, part.media_type))
            api_messages.append({"role": msg.role, "content": content})

        kwargs: dict = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": api_messages,
        }
        if system:
            kwargs["system"] = system

        started = time.monotonic()
        response = self.client.messages.create(**kwargs)
        duration_ms = int((time.monotonic() - started) * 1000)

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        return LLMResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=model,
            provider=self.name,
            duration_ms=duration_ms,
        )
