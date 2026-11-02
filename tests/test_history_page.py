"""Integration tests for pages/5_History.py using Streamlit AppTest (no AI calls)."""
import io
import json
from pathlib import Path
from unittest.mock import patch

import openpyxl
from streamlit.testing.v1 import AppTest

from core.history_store import save_entry

APP_PATH = Path(__file__).parent.parent / "app.py"


def _result(n: int, provider: str | None = "openai", model: str | None = "gpt-5") -> dict:
    result = {
        "test_cases": [
            {
                "test_id": f"TC_{n:03d}",
                "module": "Login",
                "title": f"Login case {n}",
                "precondition": "Account exists",
                "steps": "1. Enter phone\n2. Enter OTP",
                "test_data": "0912345678",
                "expected_result": "Home page opens",
                "priority": "High",
                "type": "Positive",
                "platform": "Web",
            }
        ],
        "summary": {"total": 1, "by_type": {"positive": 1}, "open_questions": [f"Question {n}?"]},
    }
    usage = {}
    if provider:
        usage["provider"] = provider
    if model:
        usage["model"] = model
    if usage:
        result["usage"] = usage
    return result


def _save(folder, n: int, **overrides) -> str:
    entry = {
        "timestamp": f"2026-11-0{n} 10:00:00",
        "project_name": "Shop",
        "requirement_excerpt": f"Requirement {n}",
        "test_case_count": 1,
        "result": _result(n),
        "config": {"project_name": "Shop", "platform": ["web"]},
        "requirement_text": f"Full requirement {n}",
    }
    entry.update(overrides)
    return save_entry(folder, entry)


def _open_page():
    # Run it as a page of app.py, as Streamlit does, so "Open in the Generator" can switch back.
    at = AppTest.from_file(str(APP_PATH))
    at.switch_page("pages/5_History.py")
    at.run(timeout=30)
    return at


def test_an_empty_history_says_so(isolated_history_dir):
    at = _open_page()

    assert not at.exception
    assert any("No saved runs yet" in info.value for info in at.info)
    assert len(at.selectbox) == 0


def test_runs_are_listed_newest_first_with_date_source_model_and_count(isolated_history_dir):
    _save(isolated_history_dir, 1, result=_result(1, provider=None, model=None))
    _save(isolated_history_dir, 2, result=_result(2, provider=None, model="claude-sonnet-5"))
    _save(isolated_history_dir, 3)

    at = _open_page()

    assert not at.exception
    table = at.dataframe[0].value
    assert list(table.columns) == ["Date", "Source", "Project", "Model", "Test cases"]
    assert table["Source"].tolist() == ["Requirement 3", "Requirement 2", "Requirement 1"]
    assert table["Model"].tolist() == ["openai / gpt-5", "anthropic / claude-sonnet-5", "—"]
    assert table["Test cases"].tolist() == [1, 1, 1]
    assert table["Date"].tolist()[0] == "2026-11-03 10:00:00"


def test_the_page_lists_more_than_the_sidebar_shows(isolated_history_dir):
    for n in range(1, 10):
        _save(isolated_history_dir, n)
    for n in range(10, 15):
        _save(isolated_history_dir, 9, requirement_excerpt=f"Requirement {n}")

    at = _open_page()

    assert len(at.dataframe[0].value) == 14
    assert len(at.selectbox(key="history_selected").options) == 14


def test_opening_a_run_shows_its_cases_note_and_exports_excel(isolated_history_dir):
    _save(isolated_history_dir, 1)
    revised = _save(isolated_history_dir, 2, note="Add negative cases for an empty email")

    at = _open_page()
    assert at.selectbox(key="history_selected").value == revised
    assert any("Add negative cases for an empty email" in m.value for m in at.markdown)

    first = at.session_state["history_selected"]
    at.selectbox(key="history_selected").set_value(
        at.selectbox(key="history_selected").options[1]
    ).run(timeout=30)

    assert not at.exception
    assert at.selectbox(key="history_selected").value != first
    cases = at.dataframe[1].value
    assert cases["test_id"].tolist() == ["TC_001"]
    assert any("Question 1?" in m.value for m in at.markdown)
    assert not any("Revision note" in m.value for m in at.markdown)


def test_the_excel_download_holds_the_saved_cases(isolated_history_dir):
    import core.excel_exporter

    _save(isolated_history_dir, 1)
    exported = []
    real_export = core.excel_exporter.export_to_excel

    def _spy(result, *args, **kwargs):
        exported.append(real_export(result, *args, **kwargs))
        return exported[-1]

    with patch.object(core.excel_exporter, "export_to_excel", _spy):
        at = _open_page()

    assert not at.exception
    assert len(exported) == 1
    sheet = openpyxl.load_workbook(io.BytesIO(exported[0])).active
    values = [cell.value for row in sheet.iter_rows() for cell in row]
    assert "TC_001" in values
    assert "Login case 1" in values
    buttons = at.get("download_button")
    assert [button.proto.label for button in buttons] == [
        "⬇️ Download Excel",
        "⬇️ Download Gherkin (.feature)",
    ]
    assert not any(button.proto.disabled for button in buttons)


def test_delete_asks_first_then_removes_only_that_run(isolated_history_dir):
    kept = _save(isolated_history_dir, 1)
    gone = _save(isolated_history_dir, 2)
    at = _open_page()
    at.session_state["history"] = [{"id": kept}, {"id": gone}]

    at.button(key=f"history_delete_{gone}").click().run(timeout=30)
    assert len(list(isolated_history_dir.glob("*.json"))) == 2
    at.button(key="history_delete_cancel").click().run(timeout=30)
    assert len(list(isolated_history_dir.glob("*.json"))) == 2

    at.button(key=f"history_delete_{gone}").click().run(timeout=30)
    at.button(key="history_delete_confirm").click().run(timeout=30)

    assert not at.exception
    assert [path.stem for path in isolated_history_dir.glob("*.json")] == [kept]
    assert [entry["id"] for entry in at.session_state["history"]] == [kept]
    assert any("Deleted the run from 2026-11-02 10:00:00" in s.value for s in at.success)
    assert at.selectbox(key="history_selected").value == kept
    assert len(at.selectbox(key="history_selected").options) == 1


def test_clear_all_asks_first_then_removes_every_file(isolated_history_dir):
    _save(isolated_history_dir, 1)
    _save(isolated_history_dir, 2)
    (isolated_history_dir / "20260101-000000-000000-bad000.json").write_text("{oops", encoding="utf-8")
    at = _open_page()
    at.session_state["history"] = [{"id": "x"}]

    at.button(key="history_clear").click().run(timeout=30)
    at.button(key="history_clear_cancel").click().run(timeout=30)
    assert len(list(isolated_history_dir.glob("*.json"))) == 3

    at.button(key="history_clear").click().run(timeout=30)
    at.button(key="history_clear_confirm").click().run(timeout=30)

    assert not at.exception
    assert list(isolated_history_dir.glob("*.json")) == []
    assert at.session_state["history"] == []
    assert any("No saved runs yet" in info.value for info in at.info)


def test_a_broken_or_old_file_is_skipped_with_a_warning(isolated_history_dir):
    _save(isolated_history_dir, 1)
    (isolated_history_dir / "20260101-000000-000000-bad000.json").write_text("{oops", encoding="utf-8")
    old = {"timestamp": "10:00:00", "project_name": "Shop", "test_cases": []}
    (isolated_history_dir / "20260102-000000-000000-old000.json").write_text(
        json.dumps(old), encoding="utf-8"
    )

    at = _open_page()

    assert not at.exception
    assert len(at.dataframe[0].value) == 1
    warnings = " ".join(w.value for w in at.warning)
    assert "bad000.json" in warnings and "old000.json" in warnings


def test_open_in_the_generator_restores_the_run(isolated_history_dir):
    entry_id = _save(isolated_history_dir, 1)
    at = _open_page()

    at.button(key=f"history_open_{entry_id}").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["last_result"]["test_cases"][0]["test_id"] == "TC_001"
    assert at.session_state["last_config"] == {"project_name": "Shop", "platform": ["web"]}
    assert at.session_state["last_requirement_text"] == "Full requirement 1"
    assert at.session_state["last_project_name"] == "Shop"
    # It lands on the Generator, with the run in the editable table.
    assert [title.value for title in at.title] == ["🧪 AI Test Case Generator"]
    assert "test_case_editor" in at.session_state


def test_a_generated_run_shows_up_with_its_model_and_no_api_key(monkeypatch, isolated_history_dir):
    from core.ai_client import AIClient

    secret = "sk-ant-test-SECRET-key-123"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    result = _result(1, provider="anthropic", model="claude-sonnet-5")
    with patch.object(AIClient, "generate_test_cases", return_value=result):
        app = AppTest.from_file(str(APP_PATH))
        app.run(timeout=30)
        app.session_state["api_key"] = secret
        app.text_area[0].set_value("As a user, I want to log in with OTP").run(timeout=30)
        app.button[0].click().run(timeout=30)
    assert not app.exception

    [saved] = list(isolated_history_dir.glob("*.json"))
    text = saved.read_text(encoding="utf-8")
    assert secret not in text
    assert "api_key" not in text.lower()

    at = _open_page()
    assert at.dataframe[0].value["Model"].tolist() == ["anthropic / claude-sonnet-5"]


def test_a_folder_of_only_broken_files_can_still_be_cleared(isolated_history_dir):
    isolated_history_dir.mkdir()
    (isolated_history_dir / "20260101-000000-000000-bad000.json").write_text("{oops", encoding="utf-8")
    at = _open_page()
    at.session_state["history_file_warning"] = "Couldn't save this result"

    assert any("No saved runs yet" in info.value for info in at.info)
    at.button(key="history_clear").click().run(timeout=30)
    at.button(key="history_clear_confirm").click().run(timeout=30)

    assert not at.exception
    assert list(isolated_history_dir.glob("*.json")) == []
    assert at.warning.len == 0
    assert "history_file_warning" not in at.session_state
