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
    # The entry must carry the config/requirement it was generated with so the
    # Reviewer page reviews a restored entry against its own context.
    assert history[0]["config"] == at.session_state["last_config"]
    assert history[0]["requirement_text"] == at.session_state["last_requirement_text"]


def test_restoring_history_entry_restores_its_config_and_requirement(monkeypatch):
    at = _run_generation(monkeypatch, requirement="First requirement about OTP login")

    # Simulate a later generation having overwritten last_config /
    # last_requirement_text with a different project's context.
    at.session_state["last_config"] = {"project_name": "Some Other Project"}
    at.session_state["last_requirement_text"] = "A totally different requirement"
    at.run(timeout=30)

    entry = at.session_state["history"][0]
    at.button(key="restore_history_0").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["last_config"] == entry["config"]
    assert at.session_state["last_requirement_text"] == "First requirement about OTP login"
    assert at.session_state["last_project_name"] == entry["project_name"]


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


def test_no_page_uses_the_deprecated_use_container_width():
    root = Path(__file__).parent.parent
    for path in [root / "app.py", *sorted((root / "pages").glob("*.py"))]:
        assert "use_container_width" not in path.read_text(encoding="utf-8"), path.name
    requirement = (root / "requirements.txt").read_text(encoding="utf-8").splitlines()[0]
    assert requirement == "streamlit>=1.50.0"


def test_traceability_panel_flags_criteria_without_a_test_case(monkeypatch):
    import copy

    traced = copy.deepcopy(FAKE_RESULT)
    traced["acceptance_criteria"] = [
        {"id": "AC-1", "text": "Log in with OTP"},
        {"id": "AC-2", "text": "OTP expires after 5 minutes"},
    ]
    traced["test_cases"][0]["covers"] = ["AC-1"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch.object(AIClient, "generate_test_cases", return_value=traced):
        at = AppTest.from_file(str(APP_PATH))
        at.run(timeout=30)
        at.text_area[0].set_value("Login story").run(timeout=30)
        at.button[0].click().run(timeout=30)

    assert not at.exception
    assert any("1 of 2 acceptance criteria covered" in e.label for e in at.expander)
    assert any("No test case covers: AC-2" in w.value for w in at.warning)


def test_generation_without_traceability_shows_no_panel(monkeypatch):
    at = _run_generation(monkeypatch)

    assert not at.exception
    assert not any("acceptance criteria covered" in e.label for e in at.expander)


SPEC_MD = b"# Shop\n\n## Login\n\nOTP login.\n\n## Checkout\n\nPay by card.\n"


def _section_result(test_id, question):
    import copy

    result = copy.deepcopy(FAKE_RESULT)
    result["acceptance_criteria"] = [{"id": "AC-1", "text": question}]
    result["test_cases"][0]["test_id"] = test_id
    result["test_cases"][0]["covers"] = ["AC-1"]
    result["summary"]["open_questions"] = [question]
    return result


def _upload(at, name="spec.md", data=SPEC_MD, mime="text/markdown"):
    at.file_uploader(key="requirement_file").upload(name, data, mime).run(timeout=30)


def test_uploaded_file_generates_per_section_and_keeps_finished_sections_on_error(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    requests = []

    def first_ok_then_fail(system_prompt, requirement_text):
        requests.append(requirement_text)
        if len(requests) == 1:
            return _section_result("TC_001", "Login question")
        raise ValueError("Rate limit exceeded")

    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)
    _upload(at)
    assert at.button(key="generate_sections_btn").label == "🚀 Generate test cases for 2 section(s)"

    with patch.object(AIClient, "generate_test_cases", side_effect=first_ok_then_fail):
        at.button(key="generate_sections_btn").click().run(timeout=30)

    assert not at.exception
    assert len(requests) == 2
    assert "Login" in requests[0] and "OTP login." in requests[0]
    assert "Checkout" in requests[1] and "OTP login." not in requests[1]
    result = at.session_state["last_result"]
    assert [tc["test_id"] for tc in result["test_cases"]] == ["TC_001"]
    assert any("1 section(s) of spec.md failed" in e.value for e in at.error)
    assert any("Rate limit exceeded" in m.value for m in at.markdown)
    assert at.session_state["history"][-1]["requirement_excerpt"] == "spec.md: 1 of 2 section(s)"

    with patch.object(AIClient, "generate_test_cases", return_value=_section_result("TC_001", "Card question")):
        at.button(key="retry_sections_btn").click().run(timeout=30)

    assert not at.exception
    merged = at.session_state["last_result"]
    assert [tc["test_id"] for tc in merged["test_cases"]] == ["TC_001", "TC_001_2"]
    assert [c["id"] for c in merged["acceptance_criteria"]] == ["S1.AC-1", "S2.AC-1"]
    assert [tc["covers"] for tc in merged["test_cases"]] == [["S1.AC-1"], ["S2.AC-1"]]
    assert merged["summary"]["open_questions"] == ["[Login] Login question", "[Checkout] Card question"]
    assert not at.session_state["section_batch"]["errors"]
    assert at.session_state["last_requirement_text"].startswith("Login\n")


def test_unticked_sections_are_not_generated(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)
    _upload(at, "backlog.csv", b"Key,Summary\nUS-1,Login\nUS-2,Logout\n", "text/csv")

    editor_key = "section_picker_backlog.csv_2"  # the file name and section count
    untick_first = {"edited_rows": {0: {"generate": False}}, "added_rows": [], "deleted_rows": []}
    at.session_state[editor_key] = untick_first
    at.run(timeout=30)
    assert at.button(key="generate_sections_btn").label == "🚀 Generate test cases for 1 section(s)"

    # AppTest does not model the table's edits, so they are set again for the click's run.
    at.session_state[editor_key] = untick_first
    with patch.object(AIClient, "generate_test_cases", return_value=_section_result("TC_9", "q")) as mocked:
        at.button(key="generate_sections_btn").click().run(timeout=30)

    assert not at.exception
    assert mocked.call_count == 1
    assert "US-2" in mocked.call_args.args[1]
    assert at.session_state["last_result"]["acceptance_criteria"] == [{"id": "AC-1", "text": "q"}]


def test_an_unreadable_upload_shows_an_error_and_no_generate_button(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)
    _upload(at, "spec.docx", b"not a zip", "application/octet-stream")

    assert not at.exception
    assert any("Could not read the Word file" in e.value for e in at.error)
    assert not [b for b in at.button if b.key == "generate_sections_btn"]
