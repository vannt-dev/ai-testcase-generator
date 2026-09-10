"""Integration tests for pages/1_Reviewer.py using Streamlit AppTest."""
import io
from pathlib import Path
from unittest.mock import patch

import openpyxl
import streamlit as st
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

    captured = {}

    def _review(system_prompt, requirement_text, test_cases):
        captured["system_prompt"] = system_prompt
        return FAKE_REVIEW

    with patch.object(AIClient, "review_test_cases", side_effect=_review):
        at.button(key="review_session_btn").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["review_result"]["coverage_score"] == 72
    assert any("72" in m.value for m in at.metric)
    assert "only report on them" in captured["system_prompt"]
    assert "write a complete, detailed set" not in captured["system_prompt"]


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
        at.text_area(key="upload_requirement_text").set_value("As a user, I want to log in").run(
            timeout=30
        )

    assert not at.exception
    assert at.button(key="review_upload_btn").disabled is False


def test_upload_review_button_disabled_when_requirement_is_empty(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    with patch.object(AIClient, "suggest_column_mapping", return_value=FAKE_MAPPING):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)

    assert not at.exception
    # Mapping is complete but the requirement text is still blank.
    assert at.button(key="review_upload_btn").disabled is True
    assert any("requirement text" in w.value for w in at.warning)


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


FAKE_MISSING_CASES = {
    "test_cases": [
        {
            "test_id": "TC_LOGIN_001", "module": "Login", "title": "OTP resend works",
            "precondition": "OTP expired", "steps": "1. Request resend", "test_data": "n/a",
            "expected_result": "New OTP sent", "priority": "High", "type": "Negative", "platform": "Web",
        }
    ],
    "summary": {"total": 1, "by_type": {"negative": 1}, "open_questions": []},
    "usage": {"model": "claude-sonnet-5", "estimated_cost_usd": 0.0005},
}


def test_generate_missing_cases_and_merge(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)

    captured = {}

    def _generate(system_prompt, requirement_text, gaps):
        captured["system_prompt"] = system_prompt
        return FAKE_MISSING_CASES

    with patch.object(AIClient, "generate_missing_cases", side_effect=_generate):
        at.button(key="generate_missing_btn").click().run(timeout=30)

    assert not at.exception
    assert len(at.session_state["generated_missing_cases"]) == 1
    assert "write a complete, detailed set" in captured["system_prompt"]
    assert "only report on them" not in captured["system_prompt"]

    at.button(key="merge_btn").click().run(timeout=30)

    assert not at.exception
    # The seeded existing case and the generated one both use test_id
    # "TC_LOGIN_001" — this exercises merge_test_cases' collision rename.
    merged_ids = [tc["test_id"] for tc in at.session_state["review_test_cases"]]
    assert merged_ids == ["TC_LOGIN_001", "TC_LOGIN_001_2"]
    assert at.session_state["merged_result"]["test_cases"][1]["title"] == "OTP resend works"


def test_merged_result_summary_is_recomputed_from_merged_cases(monkeypatch):
    """The merged export's Summary must have a real by_type breakdown, not {}."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)
    with patch.object(AIClient, "generate_missing_cases", return_value=FAKE_MISSING_CASES):
        at.button(key="generate_missing_btn").click().run(timeout=30)
    at.button(key="merge_btn").click().run(timeout=30)

    assert not at.exception
    summary = at.session_state["merged_result"]["summary"]
    assert summary["total"] == 2
    assert summary["by_type"]["positive"] == 1
    assert summary["by_type"]["negative"] == 1
    assert summary["open_questions"] == []


def test_merged_download_button_uses_project_name_in_file_name(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)
    with patch.object(AIClient, "generate_missing_cases", return_value=FAKE_MISSING_CASES):
        at.button(key="generate_missing_btn").click().run(timeout=30)

    # The rendered proto does not carry file_name, so record the kwargs the
    # page passes to st.download_button while still rendering it for real.
    real_download_button = st.download_button
    recorded = {}

    def _spy(*args, **kwargs):
        if kwargs.get("key") == "download_merged_btn":
            recorded.update(kwargs)
        return real_download_button(*args, **kwargs)

    with patch.object(st, "download_button", _spy):
        at.button(key="merge_btn").click().run(timeout=30)

    assert not at.exception
    assert recorded["file_name"] == "reviewed_testcases_E-commerce_App_Demo.xlsx"
    assert recorded["disabled"] is False


def test_merged_download_disabled_when_rows_are_incomplete(monkeypatch):
    """A merged set with a row missing required data must not be exportable."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)

    incomplete = {
        "test_cases": [{**FAKE_MISSING_CASES["test_cases"][0], "expected_result": ""}],
        "summary": {"total": 1, "by_type": {}, "open_questions": []},
        "usage": {},
    }
    with patch.object(AIClient, "generate_missing_cases", return_value=incomplete):
        at.button(key="generate_missing_btn").click().run(timeout=30)
    at.button(key="merge_btn").click().run(timeout=30)

    assert not at.exception
    assert any("missing required data" in e.value for e in at.error)


def test_new_review_clears_previous_gap_fill_state(monkeypatch):
    """Reviewing a different set must not leave the previous set's generated cases behind."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)
    with patch.object(AIClient, "generate_missing_cases", return_value=FAKE_MISSING_CASES):
        at.button(key="generate_missing_btn").click().run(timeout=30)
    at.button(key="merge_btn").click().run(timeout=30)

    assert at.session_state["merged_result"]["summary"]["total"] == 2

    # Run a second review (a different test case set) without merging.
    with patch.object(AIClient, "generate_missing_cases", return_value=FAKE_MISSING_CASES):
        at.button(key="generate_missing_btn").click().run(timeout=30)
    assert at.session_state["generated_missing_cases"]

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)

    assert not at.exception
    assert "generated_missing_cases" not in at.session_state
    assert "merged_result" not in at.session_state
    assert "missing_cases_editor" not in at.session_state


def test_reviewer_page_has_its_own_api_key_input(monkeypatch):
    """The page must be usable when opened first, with no env var set."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    assert not at.exception
    assert len(at.text_input) >= 1
    at.text_input[0].set_value("sk-typed-on-this-page").run(timeout=30)

    assert at.session_state["api_key"] == "sk-typed-on-this-page"
