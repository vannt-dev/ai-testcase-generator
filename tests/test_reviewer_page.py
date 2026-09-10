"""Integration tests for pages/1_Reviewer.py using Streamlit AppTest."""
import io
from pathlib import Path
from unittest.mock import patch

import openpyxl
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

FAKE_MAPPING = {
    "mapping": {
        "test_id": "ID", "module": "Module", "title": "Title", "precondition": "Precondition",
        "steps": "Steps", "test_data": "Data", "expected_result": "Expected",
        "priority": "Priority", "type": "Type", "platform": "Platform",
    }
}


def _make_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Module", "Title", "Precondition", "Steps", "Data", "Expected", "Priority", "Type", "Platform"])
    ws.append(["TC_001", "Login", "Login works", "Account exists", "1. Login", "Valid user", "Home shown", "High", "Positive", "Web"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


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


def test_review_from_uploaded_file_shows_coverage_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    with patch.object(AIClient, "suggest_column_mapping", return_value=FAKE_MAPPING), \
         patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)
        at.selectbox(key="upload_project_select").select("example_ecommerce").run(timeout=30)
        at.text_area(key="upload_requirement_text").set_value("As a user, I want to log in").run(timeout=30)
        at.button(key="review_upload_btn").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["review_result"]["coverage_score"] == 72


def test_upload_review_button_enables_once_mapping_is_confirmed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    with patch.object(AIClient, "suggest_column_mapping", return_value=FAKE_MAPPING):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)

    assert not at.exception
    assert at.button(key="review_upload_btn").disabled is False


def test_upload_review_button_disabled_when_mapping_incomplete(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    incomplete_mapping = {"mapping": {**FAKE_MAPPING["mapping"], "expected_result": ""}}
    with patch.object(AIClient, "suggest_column_mapping", return_value=incomplete_mapping):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)

    assert not at.exception
    assert at.button(key="review_upload_btn").disabled is True
    assert any("Map every field" in w.value for w in at.warning)
