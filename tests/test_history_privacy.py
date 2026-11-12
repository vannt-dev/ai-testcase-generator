"""Without TESTCASE_HISTORY_DIR (a hosted demo), each browser session sees only its own runs.

Nothing is read from or written to a folder on the server, so one visitor can never see,
restore, delete or clear another visitor's runs.
"""
from pathlib import Path
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import core.history_store
from core.ai_client import AIClient
from core.history_store import save_entry

APP_PATH = Path(__file__).parent.parent / "app.py"


def _result(title: str, cases: int = 1) -> dict:
    return {
        "test_cases": [
            {
                "test_id": f"TC_{n:03d}",
                "module": "Login",
                "title": title,
                "precondition": "Account exists",
                "steps": "1. Enter phone\n2. Enter OTP",
                "test_data": "0912345678",
                "expected_result": "Home page opens",
                "priority": "High",
                "type": "Positive",
                "platform": "Web",
            }
            for n in range(1, cases + 1)
        ],
        "summary": {"total": cases, "by_type": {"positive": 1}, "open_questions": []},
        "usage": {"provider": "anthropic", "model": "claude-sonnet-5"},
    }


@pytest.fixture
def server_folder(tmp_path, monkeypatch):
    """Hosted mode: no TESTCASE_HISTORY_DIR, and the old default folder holds another run.

    An empty value (rather than an unset one) keeps a local .env from setting it again.
    """
    monkeypatch.setenv("TESTCASE_HISTORY_DIR", "")
    folder = tmp_path / "server-history"
    # Earlier versions read this folder by default; a default must never come back.
    monkeypatch.setattr(core.history_store, "DEFAULT_FOLDER", folder, raising=False)
    save_entry(
        folder,
        {
            "timestamp": "2026-11-01 09:00:00",
            "project_name": "Shop",
            "requirement_excerpt": "Another visitor's secret requirement",
            "test_case_count": 1,
            "result": _result("Another visitor's case"),
            "config": {"project_name": "Shop"},
            "requirement_text": "Another visitor's secret requirement",
        },
    )
    return folder


def _files(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.json"))


def _generate(at: AppTest, requirement: str, cases: int = 1) -> None:
    result = _result(requirement, cases)
    with patch.object(AIClient, "generate_test_cases", return_value=result):
        at.text_area[0].set_value(requirement).run(timeout=30)
        at.button[0].click().run(timeout=30)
    # The sidebar was drawn before the run was stored; the next rerun shows it there.
    at.run(timeout=30)
    assert not at.exception


def _session(monkeypatch) -> AppTest:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(APP_PATH))
    at.run(timeout=30)
    return at


def _history_page(at: AppTest) -> AppTest:
    at.switch_page("pages/5_History.py")
    at.run(timeout=30)
    assert not at.exception
    return at


def _page_text(at: AppTest) -> str:
    parts = [element.value for element in [*at.markdown, *at.caption, *at.info, *at.warning]]
    parts += [str(option) for box in at.selectbox for option in box.options]
    parts += [box.label for box in at.sidebar.expander]
    for frame in at.dataframe:
        parts.append(frame.value.to_string())
    return "\n".join(str(part) for part in parts)


def test_a_new_session_sees_no_run_saved_on_the_server(monkeypatch, server_folder):
    at = _session(monkeypatch)

    assert at.session_state["history"] == []
    assert "secret requirement" not in _page_text(at)
    assert any("this browser session only" in c.value for c in at.sidebar.caption)
    assert not [button for button in at.sidebar.button if button.key == "clear_history"]

    _history_page(at)
    assert "secret requirement" not in _page_text(at)
    assert any("No saved runs yet" in info.value for info in at.info)


def test_one_session_cannot_see_another_sessions_runs(monkeypatch, server_folder):
    first = _session(monkeypatch)
    _generate(first, "Alice's private requirement")
    second = _session(monkeypatch)
    _generate(second, "Bob's private requirement")

    assert [e["requirement_text"] for e in first.session_state["history"]] == [
        "Alice's private requirement"
    ]
    assert [e["requirement_text"] for e in second.session_state["history"]] == [
        "Bob's private requirement"
    ]
    _history_page(second)
    shown = _page_text(second)
    assert "Bob's private requirement" in shown
    assert "Alice's private requirement" not in shown
    assert "secret requirement" not in shown
    # A third visitor starts empty.
    assert _session(monkeypatch).session_state["history"] == []


def test_generating_writes_nothing_to_disk(monkeypatch, server_folder, tmp_path):
    before = sorted(tmp_path.rglob("*.json"))

    _generate(_session(monkeypatch), "A requirement that stays in this session")

    assert sorted(tmp_path.rglob("*.json")) == before
    assert len(_files(server_folder)) == 1


def test_the_sidebar_clear_only_clears_this_session(monkeypatch, server_folder):
    at = _session(monkeypatch)
    _generate(at, "My requirement")

    at.button(key="clear_history").click().run(timeout=30)
    at.button(key="clear_history_confirm").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["history"] == []
    assert len(_files(server_folder)) == 1


def test_the_history_page_lists_deletes_and_clears_only_this_sessions_runs(
    monkeypatch, server_folder
):
    at = _session(monkeypatch)
    # Different case counts keep the selector's labels apart within the same second.
    _generate(at, "First requirement", cases=1)
    _generate(at, "Second requirement", cases=2)
    _history_page(at)

    assert at.dataframe[0].value["Source"].tolist() == [
        "Second requirement",
        "First requirement",
    ]
    newest = at.selectbox(key="history_selected").value
    at.button(key=f"history_delete_{newest}").click().run(timeout=30)
    at.button(key="history_delete_confirm").click().run(timeout=30)

    assert not at.exception
    assert [e["requirement_text"] for e in at.session_state["history"]] == ["First requirement"]
    assert at.dataframe[0].value["Source"].tolist() == ["First requirement"]
    assert len(_files(server_folder)) == 1

    at.button(key="history_clear").click().run(timeout=30)
    at.button(key="history_clear_confirm").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["history"] == []
    assert any("No saved runs yet" in info.value for info in at.info)
    assert len(_files(server_folder)) == 1


def test_the_page_says_runs_last_only_for_this_session_and_names_no_server_folder(
    monkeypatch, server_folder
):
    at = _history_page(_session(monkeypatch))

    caption = " ".join(c.value for c in at.caption)
    assert "this browser session" in caption
    assert "TESTCASE_HISTORY_DIR" in caption
    assert str(server_folder) not in caption


def test_the_sidebar_shows_the_newest_ten_and_the_page_shows_them_all(monkeypatch, server_folder):
    at = _session(monkeypatch)
    for n in range(12):
        _generate(at, f"Requirement {n}", cases=n + 1)

    assert len(at.session_state["history"]) == 12
    labels = [box.label for box in at.sidebar.expander if "test cases" in box.label]
    assert len(labels) == 10
    assert "12 test cases" in labels[0] and "3 test cases" in labels[-1]
    _history_page(at)
    assert len(at.dataframe[0].value) == 12
