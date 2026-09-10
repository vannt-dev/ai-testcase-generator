"""Integration tests for pages/1_Reviewer.py using Streamlit AppTest."""
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient

PAGE_PATH = Path(__file__).parent.parent / "pages" / "1_Reviewer.py"

FAKE_REVIEW = {
    "review": {
        "coverage_score": 72,
        "missing_test_types": ["security"],
        "gaps": [
            {"description": "No test for OTP resend", "suggested_type": "Negative", "severity": "High"},
        ],
        "duplicates": [],
        "summary_note": "Mostly covered, missing OTP resend and security cases.",
    },
    "usage": {"model": "claude-sonnet-5", "estimated_cost_usd": 0.001},
}


def _seed_session_state(at):
    at.session_state["last_result"] = {
        "test_cases": [
            {
                "test_id": "TC_LOGIN_001", "module": "Login", "title": "Successful login",
                "precondition": "Account exists", "steps": "1. Log in", "test_data": "Valid account",
                "expected_result": "Home page opens", "priority": "High", "type": "Positive", "platform": "Web",
            }
        ],
        "summary": {"total": 1, "by_type": {}, "open_questions": []},
    }
    at.session_state["last_project_name"] = "E-commerce App Demo"
    at.session_state["last_config"] = {
        "project_name": "E-commerce App Demo",
        "platform": ["web"],
        "test_id_format": "TC_{MODULE}_{NUMBER}",
        "test_types_required": ["positive", "security"],
        "domain_rules": [],
        "glossary": {},
        "notes": "",
    }
    at.session_state["last_requirement_text"] = "As a user, I want to log in with OTP"


def test_no_session_data_shows_hint(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    assert not at.exception
    assert any("Generator" in info.value for info in at.info)


def test_review_from_session_shows_coverage_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["review_result"]["coverage_score"] == 72
    assert any("72" in m.value for m in at.metric)
