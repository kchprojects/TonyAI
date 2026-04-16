import pytest

from tony_ai.llm.provider import AnthropicProvider, GitHubCopilotProvider, get_provider


def test_default_provider_is_github_copilot(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    provider = get_provider()
    assert isinstance(provider, GitHubCopilotProvider)
    assert provider.copilot_session_kwargs() == {}


def test_anthropic_provider_selected_by_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    provider = get_provider()

    assert isinstance(provider, AnthropicProvider)
    kwargs = provider.copilot_session_kwargs()
    assert kwargs["provider"]["type"] == "anthropic"
    assert kwargs["provider"]["base_url"] == "https://api.anthropic.com"
    assert kwargs["provider"]["api_key"] == "sk-ant-test"


def test_anthropic_provider_missing_key_raises(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(KeyError):
        get_provider()
