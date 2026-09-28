"""Integration tests for pages/2_Bug_Reporter.py using Streamlit AppTest."""
import io
from pathlib import Path
from unittest.mock import patch

import openpyxl
import streamlit as st
from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient

PAGE_PATH = Path(__file__).parent.parent / "pages" / "2_Bug_Reporter.py"


def _fake_result(**overrides):
    report = {
        "title": "Checkout freezes when paying with an expired card",
        "module": "Checkout",
        "severity": "Major",
        "priority": "High",
        "reproducibility": "Always",
        "build_version": "3.2.0",
        "environment": "",
        "preconditions": "Logged in with one item in the cart",
        "steps_to_reproduce": ["Open the cart", "Tap Pay"],
        "expected_result": "An 'expired card' error is shown",
        "actual_result": "The app freezes",
        "test_data": "",
        "related_test_id": "",
        "open_questions": ["Which app version?"],
    }
    report.update(overrides)
    return {"report": report, "usage": {"model": "claude-sonnet-5", "estimated_cost_usd": 0.0012,
                                        "input_tokens": 100, "output_tokens": 50}}


def _write(at, notes="pay with expired card -> freeze", related="", result=None):
    at.text_area(key="bug_notes").set_value(notes).run(timeout=30)
    if related:
        at.text_area(key="bug_related_case").set_value(related).run(timeout=30)
    captured = {}

    def _fake(system_prompt, notes_arg, related_arg=None):
        captured.update(system_prompt=system_prompt, notes=notes_arg, related=related_arg)
        return result or _fake_result()

    with patch.object(AIClient, "write_bug_report", side_effect=_fake):
        at.button(key="write_bug_btn").click().run(timeout=30)
    return captured


def _new_page(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)
    return at


def test_button_disabled_until_notes_are_entered(monkeypatch):
    at = _new_page(monkeypatch)

    assert not at.exception
    assert at.button(key="write_bug_btn").disabled is True
    assert any("notes" in info.value for info in at.info)


def test_writing_a_report_fills_the_fields_and_preview(monkeypatch):
    at = _new_page(monkeypatch)

    captured = _write(at)

    assert not at.exception
    assert "Never invent steps" in captured["system_prompt"]
    assert captured["notes"] == "pay with expired card -> freeze"
    assert at.text_input(key="bug_title").value == "Checkout freezes when paying with an expired card"
    assert at.selectbox(key="bug_severity").value == "Major"
    assert at.text_area(key="bug_steps").value == "Open the cart\nTap Pay"
    assert any("Which app version?" in w.value for w in at.warning)
    assert any("## Steps to Reproduce" in code.value for code in at.code)


def test_ai_error_is_shown(monkeypatch):
    at = _new_page(monkeypatch)
    at.text_area(key="bug_notes").set_value("notes").run(timeout=30)

    with patch.object(AIClient, "write_bug_report", side_effect=ValueError("Invalid API key.")):
        at.button(key="write_bug_btn").click().run(timeout=30)

    assert any("Invalid API key." in e.value for e in at.error)
    assert "bug_draft" not in at.session_state


def test_clearing_a_required_field_disables_downloads(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)

    calls = []
    real_download_button = st.download_button

    def _spy(*args, **kwargs):
        calls.append((kwargs.get("key"), kwargs.get("disabled")))
        return real_download_button(*args, **kwargs)

    with patch.object(st, "download_button", _spy):
        at.text_input(key="bug_title").set_value("").run(timeout=30)

    assert any("Title" in e.value for e in at.error)
    assert ("download_bug_md", True) in calls
    assert ("download_bug_xlsx", True) in calls


def test_second_report_replaces_edited_fields(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)
    at.text_input(key="bug_title").set_value("My edited title").run(timeout=30)
    at.selectbox(key="bug_severity").set_value("Trivial").run(timeout=30)
    at.text_area(key="bug_steps").set_value("Edited step").run(timeout=30)
    at.text_area(key="bug_open_questions").set_value("").run(timeout=30)

    second = _fake_result(
        title="Login button does nothing",
        module="Login",
        severity="Minor",
        priority="Low",
        environment="Chrome 140",
        preconditions="On the login page",
        steps_to_reproduce=["Tap Login"],
        expected_result="The home page opens",
        actual_result="Nothing happens",
        test_data="user@example.com",
        related_test_id="TC_LOGIN_001",
        open_questions=["Does it happen on Safari?"],
    )
    _write(at, notes="login button does nothing", result=second)

    report = second["report"]
    for field in ("title", "module", "environment", "test_data", "related_test_id"):
        assert at.text_input(key=f"bug_{field}").value == report[field]
    for field in ("preconditions", "expected_result", "actual_result"):
        assert at.text_area(key=f"bug_{field}").value == report[field]
    assert at.selectbox(key="bug_severity").value == "Minor"
    assert at.selectbox(key="bug_priority").value == "Low"
    assert at.text_area(key="bug_steps").value == "Tap Login"
    assert at.text_area(key="bug_open_questions").value == "Does it happen on Safari?"


def test_related_case_json_is_parsed_and_text_is_kept(monkeypatch):
    at = _new_page(monkeypatch)
    captured = _write(at, related='{"test_id": "TC_PAY_003", "title": "Pay with expired card"}')
    assert captured["related"] == {"test_id": "TC_PAY_003", "title": "Pay with expired card"}

    at = _new_page(monkeypatch)
    captured = _write(at, related="TC_PAY_003 | Pay with expired card")
    assert captured["related"] == "TC_PAY_003 | Pay with expired card"


def test_report_and_edits_survive_switching_pages(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH.parent.parent / "app.py"))
    at.run(timeout=30)
    at.switch_page("pages/2_Bug_Reporter.py").run(timeout=30)
    _write(at)
    at.selectbox(key="bug_severity").set_value("Trivial").run(timeout=30)

    at.switch_page("pages/1_Reviewer.py").run(timeout=30)
    at.switch_page("pages/2_Bug_Reporter.py").run(timeout=30)

    assert not at.exception
    assert at.text_input(key="bug_title").value == "Checkout freezes when paying with an expired card"
    assert at.selectbox(key="bug_severity").value == "Trivial"
    assert at.text_area(key="bug_steps").value == "Open the cart\nTap Pay"
    assert not at.error


def test_answered_open_questions_can_be_cleared(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)

    at.text_area(key="bug_open_questions").set_value("").run(timeout=30)

    assert not any("Which app version?" in w.value for w in at.warning)
    assert not any("## Open Questions" in code.value for code in at.code)


def test_notes_form_shows_and_exports_reproducibility_and_build(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)

    assert at.text_input(key="bug_build_version").value == "3.2.0"
    assert at.selectbox(key="bug_reproducibility").value == "Always"
    at.selectbox(key="bug_reproducibility").set_value("Intermittent").run(timeout=30)
    assert any("**Reproducibility:** Intermittent" in code.value for code in at.code)
    assert any("**Build:** 3.2.0" in code.value for code in at.code)


RUN_MAPPING = {
    "mapping": {
        "status": "Status", "actual_result": "Actual", "comment": "Note",
        "test_id": "ID", "title": "Title", "steps": "Steps",
        "module": "", "precondition": "", "test_data": "", "expected_result": "",
        "priority": "", "type": "", "platform": "",
    }
}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _run_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Title", "Steps", "Status", "Actual", "Note"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


RUN_ROWS = [
    ["TC_1", "Pay", "1. Pay", "Failed", "Freezes", "on Android"],
    ["TC_2", "Login", "1. Login", "Passed", "OK", ""],
    ["TC_3", "Cart", "1. Open cart", "Không đạt", "Empty", ""],
    ["TC_4", "Search", "1. Search", "Blocked", "", ""],
]


def _upload_run(at, rows=RUN_ROWS, name="run.xlsx", mapping=RUN_MAPPING):
    with patch.object(AIClient, "suggest_column_mapping", return_value=mapping):
        at.file_uploader(key="run_file").upload(name, _run_xlsx(rows), XLSX).run(timeout=30)


def test_run_upload_preselects_failed_values_and_counts_rows(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)

    assert not at.exception
    assert at.multiselect(key="run_failed_values_Status").value == ["Failed", "Không đạt"]
    assert any("**2** failed row(s)" in m.value for m in at.markdown)
    assert at.button(key="write_batch_btn").disabled is False


def test_run_button_disabled_until_status_is_mapped(monkeypatch):
    at = _new_page(monkeypatch)
    mapping = {"mapping": dict(RUN_MAPPING["mapping"], status="")}
    _upload_run(at, mapping=mapping)

    assert any("status" in w.value for w in at.warning)
    assert at.button(key="write_batch_btn").disabled is True


def test_run_changing_status_column_resets_failed_values(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)

    at.selectbox(key="run_mapping_status").select("Note").run(timeout=30)

    assert not at.exception
    assert at.multiselect(key="run_failed_values_Note").value == []


def test_run_writes_reports_and_lists_errors(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)
    responses = [_fake_result(title="Pay freezes"), ValueError("boom")]

    calls = []
    real_download_button = st.download_button

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("key"))
        return real_download_button(*args, **kwargs)

    with patch.object(AIClient, "write_bug_report", side_effect=responses), \
         patch.object(st, "download_button", _spy):
        at.button(key="write_batch_btn").click().run(timeout=30)

    assert not at.exception
    result = at.session_state["batch_result"]
    assert [r["source"] for r in result["reports"]] == ["run.xlsx, row 1"]
    assert result["errors"] == [{"row": 3, "test_id": "TC_3", "error": "boom"}]
    assert any("Row 3 (TC_3): boom" in e.value for e in at.error)
    assert "download_batch_xlsx" in calls and "download_batch_md" in calls


def test_run_all_rows_failing_shows_error_without_downloads(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)

    calls = []
    real_download_button = st.download_button

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("key"))
        return real_download_button(*args, **kwargs)

    with patch.object(AIClient, "write_bug_report", side_effect=ValueError("down")), \
         patch.object(st, "download_button", _spy):
        at.button(key="write_batch_btn").click().run(timeout=30)

    assert any("No bug reports were written" in e.value for e in at.error)
    assert "download_batch_xlsx" not in calls


def test_run_over_the_limit_disables_the_button(monkeypatch):
    at = _new_page(monkeypatch)
    rows = [[f"TC_{i}", "T", "S", "Failed", "A", ""] for i in range(51)]
    _upload_run(at, rows=rows)

    assert at.button(key="write_batch_btn").disabled is True
    assert any("limit is 50" in e.value for e in at.error)


def test_run_new_upload_clears_previous_results(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)
    with patch.object(AIClient, "write_bug_report", return_value=_fake_result()):
        at.button(key="write_batch_btn").click().run(timeout=30)
    assert "batch_result" in at.session_state

    _upload_run(at, name="run2.xlsx")

    assert "batch_result" not in at.session_state
