"""Integration tests for pages/3_Automation.py using Streamlit AppTest."""
import io
from pathlib import Path
from unittest.mock import patch

import openpyxl
from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient

PAGE_PATH = Path(__file__).parent.parent / "pages" / "3_Automation.py"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _case(test_id, platform="Web", module="Login"):
    return {
        "test_id": test_id, "module": module, "title": f"Case {test_id}", "precondition": "-",
        "steps": "1. Open login", "test_data": "-", "expected_result": "Login page shown",
        "priority": "High", "type": "Positive", "platform": platform,
    }


FAKE_AUTOMATION = {
    "automation": {
        "pages": [{"name": "LoginPage", "path": "/login", "locators": [
            {"key": "emailInput", "strategy": "label", "role": "", "value": "Email", "confident": False},
        ]}],
        "tests": [{"test_id": "TC_1", "title": "Case TC_1", "steps": [
            {"action": "goto", "page": "LoginPage", "locator": "", "value": "", "source": "Open login"},
            {"action": "click", "page": "LoginPage", "locator": "missing", "value": "", "source": "Click it"},
        ]}],
        "open_questions": ["Which account?"],
    },
    "usage": {"model": "claude-sonnet-5", "input_tokens": 10, "output_tokens": 5, "estimated_cost_usd": 0.001},
}

MAPPING = {"mapping": {
    "test_id": "ID", "module": "", "title": "Title", "precondition": "", "steps": "Steps",
    "test_data": "", "expected_result": "Expected", "priority": "", "type": "", "platform": "",
}}


def _xlsx(rows):
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["ID", "Title", "Steps", "Expected"])
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _app(monkeypatch, cases=None):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    if cases is not None:
        at.session_state["last_result"] = {"test_cases": cases, "summary": {}}
    at.run(timeout=30)
    return at


def _generate(at):
    at.text_input(key="automation_base_url").set_value("https://staging.example.com").run(timeout=30)
    with patch.object(AIClient, "generate_automation", return_value=FAKE_AUTOMATION) as mocked:
        at.button(key="automation_generate_btn").click().run(timeout=30)
    return mocked


def test_no_session_cases_points_to_generator(monkeypatch):
    at = _app(monkeypatch)

    assert not at.exception
    assert any("Generator" in info.value for info in at.info)


def test_non_web_cases_are_hidden_and_counted(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1"), _case("TC_2", platform="iOS"), _case("TC_3", platform="All")])

    assert not at.exception
    assert any("1 non-web test case" in caption.value for caption in at.caption)


def test_generate_is_disabled_until_base_url_is_valid(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])

    assert at.button(key="automation_generate_btn").disabled is True
    assert any("Base URL" in warning.value for warning in at.warning)

    at.text_input(key="automation_base_url").set_value("https://staging.example.com").run(timeout=30)
    assert at.button(key="automation_generate_btn").disabled is False


def test_only_the_first_ten_web_cases_are_preselected(monkeypatch):
    at = _app(monkeypatch, [_case(f"TC_{i}") for i in range(12)])
    mocked = _generate(at)

    sent_cases = mocked.call_args.args[1]
    assert [case["test_id"] for case in sent_cases] == [f"TC_{i}" for i in range(10)]


def test_generate_shows_metrics_warnings_questions_and_preview(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    at.text_input(key="automation_page_name_0").set_value("Login").run(timeout=30)
    at.text_input(key="automation_page_path_0").set_value("/login").run(timeout=30)
    at.text_area(key="automation_page_snapshot_0").set_value("<form></form>").run(timeout=30)
    mocked = _generate(at)

    assert not at.exception
    system_prompt, cases, pages = mocked.call_args.args
    assert "Playwright" in system_prompt
    assert cases[0]["test_id"] == "TC_1"
    assert pages == [{"name": "Login", "path": "/login", "snapshot": "<form></form>"}]
    stored = at.session_state["automation_result"]
    assert stored["automation"]["tests"][0]["steps"][1]["action"] == "todo"
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics == {"Tests": "1", "Marked fixme": "1", "Locators to verify": "1"}
    assert any("unknown locator 'missing'" in md.value for md in at.markdown)
    assert any("Which account?" in md.value for md in at.markdown)
    assert at.selectbox(key="automation_preview_file").value == "pages/LoginPage.ts"
    assert "export class LoginPage" in at.code[0].value


def test_blank_page_rows_are_not_sent(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    mocked = _generate(at)

    assert mocked.call_args.args[2] == []


def test_every_test_fixme_shows_a_prominent_warning(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    _generate(at)

    assert any("every test needs manual work" in warning.value for warning in at.warning)


def test_max_tokens_error_suggests_fewer_cases(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    at.text_input(key="automation_base_url").set_value("https://staging.example.com").run(timeout=30)
    error = ValueError("The AI's response was cut off after exceeding max_tokens before finishing the JSON.")
    with patch.object(AIClient, "generate_automation", side_effect=error):
        at.button(key="automation_generate_btn").click().run(timeout=30)

    assert any("select fewer test cases" in e.value for e in at.error)
    assert "automation_result" not in at.session_state


def test_switching_source_clears_the_result(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    _generate(at)
    at.radio(key="automation_source").set_value("Upload .xlsx/.csv").run(timeout=30)

    assert "automation_result" not in at.session_state


def test_upload_requires_the_core_columns(monkeypatch):
    at = _app(monkeypatch)
    at.radio(key="automation_source").set_value("Upload .xlsx/.csv").run(timeout=30)
    incomplete = {"mapping": {**MAPPING["mapping"], "expected_result": ""}}
    with patch.object(AIClient, "suggest_column_mapping", return_value=incomplete):
        at.file_uploader(key="automation_file").upload("cases.xlsx", _xlsx([["TC_9", "t", "s", "e"]]), XLSX).run(timeout=30)

    assert any("expected_result" in warning.value for warning in at.warning)
    assert at.button(key="automation_generate_btn").disabled is True


def test_upload_flow_generates_from_mapped_rows(monkeypatch):
    at = _app(monkeypatch)
    at.radio(key="automation_source").set_value("Upload .xlsx/.csv").run(timeout=30)
    with patch.object(AIClient, "suggest_column_mapping", return_value=MAPPING):
        at.file_uploader(key="automation_file").upload("cases.xlsx", _xlsx([["TC_9", "t", "s", "e"]]), XLSX).run(timeout=30)
    mocked = _generate(at)

    assert not at.exception
    assert mocked.call_args.args[1][0]["test_id"] == "TC_9"


def test_new_upload_content_clears_result(monkeypatch):
    at = _app(monkeypatch)
    at.radio(key="automation_source").set_value("Upload .xlsx/.csv").run(timeout=30)
    with patch.object(AIClient, "suggest_column_mapping", return_value=MAPPING) as suggest:
        at.file_uploader(key="automation_file").upload("cases.xlsx", _xlsx([["TC_9", "t", "s", "e"]]), XLSX).run(timeout=30)
        _generate(at)
        at.file_uploader(key="automation_file").upload("cases.xlsx", _xlsx([["TC_10", "t", "s", "e"]]), XLSX).run(timeout=30)

    assert suggest.call_count == 2
    assert "automation_result" not in at.session_state


def test_regenerated_session_cases_with_the_same_ids_clear_the_result(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    _generate(at)
    changed = {**_case("TC_1"), "steps": "1. Open the new login page"}
    at.session_state["last_result"] = {"test_cases": [changed], "summary": {}}
    at.run(timeout=30)

    assert "automation_result" not in at.session_state


def test_download_is_hidden_until_the_base_url_is_valid_again(monkeypatch):
    at = _app(monkeypatch, [_case("TC_1")])
    _generate(at)
    assert len(at.get("download_button")) == 1

    at.text_input(key="automation_base_url").set_value("").run(timeout=30)

    assert "automation_result" in at.session_state
    assert len(at.get("download_button")) == 0
    assert any("valid Base URL to download" in warning.value for warning in at.warning)
