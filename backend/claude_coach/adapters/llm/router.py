"""Routes LLM tasks to the configured provider/model via config/llm_routing.yaml."""

from functools import lru_cache

import yaml

from claude_coach.adapters.llm.base import LLMProvider, LLMResult, Message
from claude_coach.adapters.llm.observability import record_call, record_failure
from claude_coach.adapters.llm.providers.claude import ClaudeProvider
from claude_coach.adapters.llm.providers.openai import OpenAIProvider
from claude_coach.config import REPO_ROOT

ROUTING_PATH = REPO_ROOT / "config" / "llm_routing.yaml"

_PROVIDER_FACTORIES: dict[str, type] = {
    "claude": ClaudeProvider,
    "openai": OpenAIProvider,
}


@lru_cache(maxsize=4)
def _get_provider(name: str) -> LLMProvider:
    factory = _PROVIDER_FACTORIES.get(name)
    if not factory:
        raise ValueError(f"Unknown LLM provider: {name!r}")
    return factory()


def _load_routing() -> dict:
    if not ROUTING_PATH.exists():
        raise FileNotFoundError(
            f"LLM routing config missing: {ROUTING_PATH}. "
            "Create it (see docs/architecture.md)."
        )
    with ROUTING_PATH.open() as f:
        return yaml.safe_load(f)


class LLMRouter:
    def __init__(self, routing: dict | None = None) -> None:
        self.routing = routing or _load_routing()

    def _config_for(self, task_id: str) -> dict:
        return self.routing.get("tasks", {}).get(task_id, self.routing["default"])

    def complete(
        self,
        task_id: str,
        messages: list[Message],
        system: str | None = None,
    ) -> LLMResult:
        cfg = self._config_for(task_id)
        provider = _get_provider(cfg["provider"])
        try:
            result = provider.complete(
                messages=messages,
                model=cfg["model"],
                max_tokens=cfg.get("max_tokens", 4000),
                temperature=cfg.get("temperature", 0.0),
                system=system,
                response_format=cfg.get("response_format"),
            )
        except Exception as exc:
            record_failure(
                task_id=task_id, provider=cfg["provider"], model=cfg["model"], error=str(exc)
            )
            raise
        record_call(task_id=task_id, result=result, success=True)
        return result


router = LLMRouter()
