"""Integration tests for app.py using Streamlit AppTest (mocks AIClient, no real API calls)."""
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient

APP_PATH = Path(__file__).parent.parent / "app.py"

FAKE_RESULT = {
    "test_cases": [
        {
            "test_id": "TC_LOGIN_001",
            "module": "Login",
            "title": "Successful login",
            "precondition": "Account is valid",
            "steps": "1. Enter phone number\n2. Enter OTP",
            "test_data": "Phone: 0912345678",
            "expected_result": "Home page is reached",
            "priority": "High",
            "type": "Positive",
            "platform": "Web",
        }
    ],
    "summary": {"total": 1, "by_type": {"positive": 1}, "open_questions": ["How long until the OTP expires?"]},
    "usage": {
        "model": "claude-sonnet-5",
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "total_input_tokens": 100,
        "estimated_cost_usd": 0.0007,
    },
}


def _run_generation(monkeypatch, requirement="As a user, I want to log in with OTP"):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch.object(AIClient, "generate_test_cases", return_value=FAKE_RESULT):
        at = AppTest.from_file(str(APP_PATH))
        at.run(timeout=30)
        at.text_area[0].set_value(requirement).run(timeout=30)
        at.button[0].click().run(timeout=30)
    return at


def test_generate_flow_shows_editor_and_no_exception(monkeypatch):
    at = _run_generation(monkeypatch)

    assert not at.exception
    assert at.session_state["last_result"]["summary"]["total"] == 1
    assert "test_case_editor" in at.session_state
    assert at.session_state["last_config"]["project_name"] == at.session_state["last_project_name"]
    assert at.session_state["last_requirement_text"] == "As a user, I want to log in with OTP"


def test_generate_flow_records_history(monkeypatch):
    at = _run_generation(monkeypatch)

    history = at.session_state["history"]
    assert len(history) == 1
    assert history[0]["test_case_count"] == 1
    assert history[0]["project_name"] == at.session_state["last_project_name"]


def test_empty_requirement_shows_warning_and_no_history(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)

    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("Please enter a requirement" in w.value for w in at.warning)
    assert st_history_empty(at)


def test_requirement_too_long_shows_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)

    at.text_area[0].set_value("a" * 40001).run(timeout=30)
    at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("too long" in e.value for e in at.error)
    assert st_history_empty(at)


def st_history_empty(at) -> bool:
    return "history" not in at.session_state or not at.session_state["history"]
