import json
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from app.claude_client import (
    detect_domain_family,
    extract_json_from_text,
    load_system_prompt,
    propose_generation_config,
    propose_specification,
    test_connection as run_test_connection,
)


def test_test_connection_in_mock_mode(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "true")
    res = run_test_connection()
    parsed = json.loads(res)
    assert parsed["status"] == "ok"
    assert parsed["mode"] == "mock"


def test_propose_specification_in_mock_mode(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "true")
    metadata = {
        "sheet_names": ["Specification"],
        "sheet_count": 1,
        "sheets": [{"name": "Specification", "max_row": 10, "max_column": 5}],
    }
    project_info = {
        "project_name": "Investment Customer / Client Data",
        "domain": "Financial services",
        "country": "India",
        "record_count": 10000,
        "random_seed": 42,
    }

    suggestions = propose_specification(metadata, project_info)
    assert isinstance(suggestions, list)
    assert len(suggestions) > 0
    first = suggestions[0]
    assert "sheet_name" in first
    assert "cell" in first
    assert "proposed_value" in first
    assert "reasoning" in first
    assert "confidence" in first


def test_propose_specification_adapts_to_agriculture_domain(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "true")
    metadata = {"sheet_names": ["Project_Overview"], "sheet_count": 1, "sheets": [{"name": "Project_Overview", "max_row": 10, "max_column": 5}]}
    agri_info = {
        "project_name": "Soil Chemistry and Crop Yield",
        "domain": "Agriculture",
        "country": "Kenya",
        "dataset_objective": "Predict harvest yield from soil nitrogen",
        "record_count": 2500,
        "random_seed": 55,
    }

    suggestions = propose_specification(metadata, agri_info)
    assert len(suggestions) > 0
    field_names = [s["field_name"] for s in suggestions]
    assert any("Soil" in name or "Nutrient" in name for name in field_names)
    assert not any("Income" in name or "Investment" in name for name in field_names)


def test_propose_generation_config_in_mock_mode(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "true")
    project_info = {
        "project_name": "Investment Customer / Client Data",
        "domain": "Financial services",
        "record_count": 5000,
        "random_seed": 99,
    }
    cfg = propose_generation_config({}, [], project_info)
    assert isinstance(cfg, dict)
    assert cfg["record_count"] == 5000
    assert cfg["random_seed"] == 99
    assert len(cfg["columns"]) > 0
    assert "noise_policy" in cfg


def test_detect_domain_family():
    assert detect_domain_family({"domain": "Agriculture", "project_name": "Crop Yield"}) == "agriculture"
    assert detect_domain_family({"domain": "Clinical Trials", "project_name": "Patient Vitals"}) == "healthcare"
    assert detect_domain_family({"domain": "Retail E-Commerce", "project_name": "Customer Churn"}) == "retail"
    assert detect_domain_family({"domain": "Financial Services", "project_name": "Investment Portfolio"}) == "finance"
    assert detect_domain_family({"domain": "Astronomy", "project_name": "Deep Sky Stellar Survey"}) == "generic"


def test_extract_json_from_text_pure_json():
    text = '{"status": "ok", "count": 10}'
    data = extract_json_from_text(text)
    assert data == {"status": "ok", "count": 10}


def test_extract_json_from_text_markdown_block():
    text = """Here is the result:
```json
[
  {"name": "test_col", "type": "integer"}
]
```
Hope this helps!"""
    data = extract_json_from_text(text)
    assert isinstance(data, list)
    assert data[0]["name"] == "test_col"


def test_extract_json_from_text_malformed_raises():
    with pytest.raises(RuntimeError, match="invalid JSON"):
        extract_json_from_text("This is not valid json at all {broken: json")


def test_load_system_prompt_success():
    spec_prompt = load_system_prompt("specification_system.txt")
    assert len(spec_prompt) > 0
    gen_prompt = load_system_prompt("generation_system.txt")
    assert len(gen_prompt) > 0


def test_load_system_prompt_missing_raises():
    with pytest.raises(FileNotFoundError, match="not found"):
        load_system_prompt("nonexistent_prompt_file.txt")


def test_live_mode_auth_error_handling(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.AuthenticationError(
        message="Invalid API Key",
        response=MagicMock(status_code=401),
        body={"error": {"message": "Invalid API key"}},
    )

    with patch("app.claude_client.create_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="Authentication failed"):
            run_test_connection()


def test_live_mode_rate_limit_error_handling(monkeypatch):
    monkeypatch.setenv("CLAUDE_MOCK_MODE", "false")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = anthropic.RateLimitError(
        message="Rate limit exceeded",
        response=MagicMock(status_code=429),
        body={"error": {"message": "Rate limit exceeded"}},
    )

    with patch("app.claude_client.create_client", return_value=mock_client):
        with pytest.raises(RuntimeError, match="rate limit or usage quota"):
            run_test_connection()


def test_call_claude_with_continuation_stitches_truncated_chunks():
    from app.claude_client import call_claude_with_continuation

    mock_client = MagicMock()

    # Mock block object with type="text" and text attribute
    block1 = MagicMock(type="text", text='[{"field": "col1", ')
    block2 = MagicMock(type="text", text='"proposed_value": 100}]')

    resp1 = MagicMock(content=[block1], stop_reason="max_tokens")
    resp2 = MagicMock(content=[block2], stop_reason="end_turn")

    mock_client.messages.create.side_effect = [resp1, resp2]

    assembled = call_claude_with_continuation(
        client=mock_client,
        model="claude-3-5-sonnet-20241022",
        system_prompt="You are an analyst.",
        user_prompt="Generate json",
        task="specification",
    )

    assert assembled == '[{"field": "col1", "proposed_value": 100}]'
    assert mock_client.messages.create.call_count == 2

    # Check that chunk 2 was called with assistant prefill containing chunk 1
    second_call_args = mock_client.messages.create.call_args_list[1][1]
    msgs = second_call_args["messages"]
    assert len(msgs) == 2
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"] == '[{"field": "col1", '


def test_call_claude_with_continuation_single_turn():
    from app.claude_client import call_claude_with_continuation

    mock_client = MagicMock()
    block = MagicMock(type="text", text='{"status": "ok"}')
    resp = MagicMock(content=[block], stop_reason="end_turn")
    mock_client.messages.create.return_value = resp

    assembled = call_claude_with_continuation(
        client=mock_client,
        model="claude-3-5-sonnet-20241022",
        system_prompt="system",
        user_prompt="user",
        task="general",
    )

    assert assembled == '{"status": "ok"}'
    assert mock_client.messages.create.call_count == 1


def test_extract_json_from_text_repairs_unclosed_brackets():
    # Truncated array missing closing bracket
    truncated_array = '[{"sheet_name": "Sheet1", "cell": "B2", "proposed_value": "test"}'
    repaired = extract_json_from_text(truncated_array)
    assert isinstance(repaired, list)
    assert repaired[0]["cell"] == "B2"

