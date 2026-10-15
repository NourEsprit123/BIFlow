from unittest.mock import Mock, patch

import pytest
import requests

from agents.llm_client import LLMClient


def test_qwen3_generation_disables_thinking_and_limits_output(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_NUM_PREDICT", "128")
    monkeypatch.setenv("OLLAMA_TIMEOUT_SECONDS", "45")
    client = LLMClient()

    with patch("agents.llm_client.requests.post") as post:
        post.return_value.json.return_value = {"response": '{"status":"ok"}'}
        result = client.generate_json("Return a JSON status.")
        request_kwargs = post.call_args.kwargs

    assert result == {"status": "ok"}
    assert request_kwargs["json"]["think"] is False
    assert request_kwargs["json"]["options"]["num_predict"] == 128
    assert request_kwargs["timeout"] == 45


def test_ollama_timeout_returns_fallback_json(monkeypatch, caplog):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3:8b")
    client = LLMClient()

    with patch("agents.llm_client.requests.post", side_effect=requests.Timeout):
        assert client.generate_json("Return JSON.") == {}

    assert "Try a smaller model" in caplog.text


def test_openai_provider_generates_json(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    client = LLMClient()
    mock_client = Mock()
    mock_client.chat.completions.create.return_value.choices = [
        Mock(message=Mock(content='{"status":"ok"}'))
    ]

    with patch("openai.OpenAI", return_value=mock_client) as openai_client:
        result = client.generate_json(
            "Return a JSON status.",
            system_prompt="Return JSON only.",
        )

    assert client.provider == "openai"
    assert result == {"status": "ok"}
    openai_client.assert_called_once_with(api_key="test-api-key")
    mock_client.chat.completions.create.assert_called_once_with(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "Return a JSON status."},
        ],
        response_format={"type": "json_object"},
    )


def test_groq_provider_generates_json(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")
    monkeypatch.setenv("GROQ_MODEL", "qwen/qwen3.8-27b")
    monkeypatch.setenv("GROQ_MAX_COMPLETION_TOKENS", "900")
    client = LLMClient()
    mock_client = Mock()
    mock_client.chat.completions.create.return_value.choices = [
        Mock(message=Mock(content='{"status":"ok"}'))
    ]

    with patch("openai.OpenAI", return_value=mock_client) as groq_client:
        result = client.generate_json(
            "Return a JSON status.",
            system_prompt="Return JSON only.",
            max_output_tokens=180,
        )

    assert client.provider == "groq"
    assert result == {"status": "ok"}
    groq_client.assert_called_once_with(
        api_key="test-groq-key",
        base_url="https://api.groq.com/openai/v1",
    )
    mock_client.chat.completions.create.assert_called_once_with(
        model="qwen/qwen3.8-27b",
        messages=[
            {"role": "system", "content": "Return JSON only."},
            {"role": "user", "content": "Return a JSON status."},
        ],
        response_format={"type": "json_object"},
        max_completion_tokens=180,
    )


def test_groq_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        LLMClient().generate_json("Return JSON.")


def test_openai_requires_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY is not set"):
        LLMClient().generate_json("Return JSON.")


def test_explicit_ollama_provider_is_respected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    assert LLMClient().provider == "ollama"


def test_groq_is_default_provider(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "legacy-gemini-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert LLMClient().provider == "groq"


def test_unknown_provider_does_not_fall_back_to_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")
    client = LLMClient()

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        client.generate_text("Return text.")


def test_groq_is_required_when_selected_as_default_without_api_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        LLMClient().generate_json("Return JSON.")
