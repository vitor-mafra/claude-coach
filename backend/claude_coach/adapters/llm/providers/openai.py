import base64
import time

import openai

from claude_coach.adapters.llm.base import ImagePart, LLMResult, Message, TextPart
from claude_coach.config import settings

# Models that use the newer Responses-API-style `max_completion_tokens` parameter
# and ignore (or reject) `temperature`. Update as new families ship.
_NEW_PARAM_PREFIXES: tuple[str, ...] = ("gpt-5", "o1", "o3", "o4")


def _uses_completion_tokens(model: str) -> bool:
    return any(model.startswith(p) for p in _NEW_PARAM_PREFIXES)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key or settings.openai_api_key
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set. Add it to .env to use the OpenAI provider."
            )
        self.client = openai.OpenAI(api_key=key)

    def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int = 4000,
        temperature: float = 0.0,
        system: str | None = None,
        response_format: str | None = None,
    ) -> LLMResult:
        api_messages: list[dict] = []
        if system:
            api_messages.append({"role": "system", "content": system})

        for msg in messages:
            content_parts: list[dict] = []
            for part in msg.parts:
                if isinstance(part, TextPart):
                    content_parts.append({"type": "text", "text": part.text})
                elif isinstance(part, ImagePart):
                    with part.path.open("rb") as f:
                        data = base64.standard_b64encode(f.read()).decode("utf-8")
                    content_parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{part.media_type};base64,{data}"},
                        }
                    )
            api_messages.append({"role": msg.role, "content": content_parts})

        kwargs: dict = {
            "model": model,
            "messages": api_messages,
        }
        # Newer OpenAI models (gpt-5 family, o-series reasoning models) require
        # `max_completion_tokens` and reject `max_tokens`; older chat models
        # (gpt-4o, gpt-4, gpt-3.5) still use `max_tokens`. Switch by prefix.
        if _uses_completion_tokens(model):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = temperature
        if response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        started = time.monotonic()
        response = self.client.chat.completions.create(**kwargs)
        duration_ms = int((time.monotonic() - started) * 1000)

        usage = response.usage
        return LLMResult(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=model,
            provider=self.name,
            duration_ms=duration_ms,
        )
