import os
import pytest
from app.config import get_mock_mode, is_placeholder_key, validate_config


def test_mock_mode_allows_missing_api_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "true")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    # Should not raise in mock mode
    validate_config()


def test_live_mode_rejects_missing_api_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY is missing"):
        validate_config()


def test_live_mode_rejects_placeholder_api_key(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "your_api_key_here")
    with pytest.raises(ValueError, match="placeholder text"):
        validate_config()


def test_placeholder_key_detection():
    assert is_placeholder_key("") is True
    assert is_placeholder_key("your_api_key_here") is True
    assert is_placeholder_key("sk-ant-placeholder") is True
    assert is_placeholder_key("sk-ant-api03-valid_secret_key_12345") is False


def test_live_mode_rejects_empty_model(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-validkey123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    with pytest.raises(ValueError, match="ANTHROPIC_MODEL cannot be empty"):
        validate_config()


def test_live_mode_rejects_invalid_max_tokens(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-validkey123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "-10")
    with pytest.raises(ValueError, match="ANTHROPIC_MAX_TOKENS"):
        validate_config()


def test_get_mock_mode_parsing(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "true")
    assert get_mock_mode() is True
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "1")
    assert get_mock_mode() is True
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    assert get_mock_mode() is False
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "0")
    assert get_mock_mode() is False


def test_live_mode_allows_missing_max_tokens(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-validkey123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
    monkeypatch.delenv("ANTHROPIC_MAX_TOKENS", raising=False)
    # Should not raise; ANTHROPIC_MAX_TOKENS is optional
    validate_config()


def test_get_max_tokens_for_task_dynamic_model_resolution(monkeypatch):
    from app.config import get_max_tokens_for_task, get_model_token_ceiling

    monkeypatch.delenv("ANTHROPIC_MAX_TOKENS", raising=False)

    # Claude 3.5 Sonnet supports 8192 tokens
    assert get_model_token_ceiling("claude-3-5-sonnet-20241022") == 8192
    assert get_max_tokens_for_task("specification", "claude-3-5-sonnet-20241022") == 8192
    assert get_max_tokens_for_task("connectivity_check", "claude-3-5-sonnet-20241022") == 256

    # Claude 3.7 Sonnet supports up to 64000 tokens
    assert get_model_token_ceiling("claude-3-7-sonnet-20250219") == 64000

    # Claude 3 Opus supports 4096 tokens
    assert get_model_token_ceiling("claude-3-opus-20240229") == 4096
    assert get_max_tokens_for_task("specification", "claude-3-opus-20240229") == 4096


def test_get_max_tokens_for_task_respects_env_override(monkeypatch):
    from app.config import get_max_tokens_for_task

    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "2048")
    assert get_max_tokens_for_task("specification", "claude-3-5-sonnet-20241022") == 2048

    # If user requests 50000 on a model that only supports 8192, cap at model ceiling
    monkeypatch.setenv("ANTHROPIC_MAX_TOKENS", "50000")
    assert get_max_tokens_for_task("specification", "claude-3-5-sonnet-20241022") == 8192

