from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Pluggable LLM provider. Implement to support a new backend."""

    @abstractmethod
    def copilot_session_kwargs(self) -> dict[str, Any]:
        """Return extra kwargs to pass to client.create_session()."""


class GitHubCopilotProvider(LLMProvider):
    """Default: uses GITHUB_TOKEN env var. No extra config needed."""

    def copilot_session_kwargs(self) -> dict[str, Any]:
        return {}


class AnthropicProvider(LLMProvider):
    """Future BYOK Anthropic. Set LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def copilot_session_kwargs(self) -> dict[str, Any]:
        return {
            "provider": {
                "type": "anthropic",
                "base_url": "https://api.anthropic.com",
                "api_key": self._api_key,
            }
        }


def get_provider() -> LLMProvider:
    """Factory: reads LLM_PROVIDER env var to select implementation."""
    import os

    name = os.getenv("LLM_PROVIDER", "github_copilot").lower()
    if name == "anthropic":
        api_key = os.environ["ANTHROPIC_API_KEY"]
        return AnthropicProvider(api_key)
    return GitHubCopilotProvider()
