"""The Generator's "revise selected test cases" flow, with AIClient mocked (no real API calls)."""
import copy
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient
from tests.test_app import FAKE_RESULT

APP_PATH = Path(__file__).parent.parent / "app.py"


def _two_case_result() -> dict:
    result = copy.deepcopy(FAKE_RESULT)
    second = dict(result["test_cases"][0], test_id="TC_LOGIN_002", title="Wrong OTP", type="Negative")
    result["test_cases"].append(second)
    result["acceptance_criteria"] = [{"id": "AC-1", "text": "Log in with OTP"}]
    result["summary"]["total"] = 2
    return result


def _reply(**overrides) -> dict:
    case = dict(_two_case_result()["test_cases"][1], title="Wrong OTP shows an error", covers=["AC-1"])
    reply = {
        "revised": [case],
        "added": [dict(case, test_id="TC_LOGIN_003", title="Empty OTP")],
        "open_questions": ["Is the OTP field required?"],
        "usage": {"provider": "anthropic", "model": "claude-sonnet-5", "input_tokens": 9,
                  "output_tokens": 9, "estimated_cost_usd": 0.0001},
    }
    reply.update(overrides)
    return reply


def _generated(monkeypatch) -> AppTest:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch.object(AIClient, "generate_test_cases", return_value=_two_case_result()):
        at = AppTest.from_file(str(APP_PATH))
        at.run(timeout=30)
        at.text_area[0].set_value("OTP login story").run(timeout=30)
        at.button[0].click().run(timeout=30)
    return at


def _revise(at: AppTest, **patch_kwargs) -> AppTest:
    at.multiselect(key="revise_selection").set_value(["TC_LOGIN_002"]).run(timeout=30)
    at.text_area(key="revise_note").set_value("Add a case for an empty OTP").run(timeout=30)
    with patch.object(AIClient, "revise_test_cases", **patch_kwargs) as revise:
        at.button(key="revise_btn").click().run(timeout=30)
    at.revise_mock = revise
    return at


def test_revise_button_needs_a_selection_and_a_note(monkeypatch):
    at = _generated(monkeypatch)

    assert at.button(key="revise_btn").disabled
    at.multiselect(key="revise_selection").set_value(["TC_LOGIN_001"]).run(timeout=30)
    assert at.button(key="revise_btn").disabled
    at.text_area(key="revise_note").set_value("Clearer title").run(timeout=30)
    assert not at.button(key="revise_btn").disabled


def test_a_revision_is_previewed_and_changes_nothing_until_accepted(monkeypatch):
    at = _revise(_generated(monkeypatch), return_value=_reply())

    assert not at.exception
    args = at.revise_mock.call_args.args
    # Only the selected case is sent, with the requirement, criteria and every id in the set.
    assert args[1] == "OTP login story"
    assert args[2] == [{"id": "AC-1", "text": "Log in with OTP"}]
    assert [case["test_id"] for case in args[3]] == ["TC_LOGIN_002"]
    assert args[4] == "Add a case for an empty OTP"
    assert args[5] == ["TC_LOGIN_001", "TC_LOGIN_002"]
    assert "pending_revision" in at.session_state
    assert any("1 revised, 1 added" in md.value for md in at.markdown)
    titles = [case["title"] for case in at.session_state["last_result"]["test_cases"]]
    assert titles == ["Successful login", "Wrong OTP"]


def test_accepting_replaces_only_the_selected_case_and_keeps_history(monkeypatch):
    at = _revise(_generated(monkeypatch), return_value=_reply())
    before = copy.deepcopy(at.session_state["last_result"]["test_cases"][0])

    at.button(key="accept_revision_btn").click().run(timeout=30)

    assert not at.exception
    cases = at.session_state["last_result"]["test_cases"]
    assert [case["test_id"] for case in cases] == ["TC_LOGIN_001", "TC_LOGIN_002", "TC_LOGIN_003"]
    assert cases[0] == {**before, "covers": []}
    assert cases[1]["title"] == "Wrong OTP shows an error"
    summary = at.session_state["last_result"]["summary"]
    assert summary["total"] == 3
    assert "Is the OTP field required?" in summary["open_questions"]
    assert at.session_state["last_result"]["acceptance_criteria"] == [{"id": "AC-1", "text": "Log in with OTP"}]
    assert "pending_revision" not in at.session_state
    history = at.session_state["history"]
    assert len(history) == 2
    assert history[-1]["requirement_excerpt"].startswith("Revised 1 test case(s)")
    # The earlier set stays in history, so Restore undoes the revision.
    assert history[0]["test_case_count"] == 2


def test_discarding_keeps_the_original_set(monkeypatch):
    at = _revise(_generated(monkeypatch), return_value=_reply())

    at.button(key="discard_revision_btn").click().run(timeout=30)

    assert not at.exception
    assert "pending_revision" not in at.session_state
    assert len(at.session_state["last_result"]["test_cases"]) == 2
    assert len(at.session_state["history"]) == 1


def test_an_ai_error_is_shown_and_the_table_is_untouched(monkeypatch):
    at = _revise(_generated(monkeypatch), side_effect=ValueError("Invalid API key."))

    assert not at.exception
    assert any("Invalid API key." in error.value and "not changed" in error.value for error in at.error)
    # The error sits inside the status box; it must open, or the "not changed" line stays hidden.
    assert [status.proto.expanded for status in at.status if status.state == "error"] == [True]
    assert "pending_revision" not in at.session_state
    assert [case["title"] for case in at.session_state["last_result"]["test_cases"]] == [
        "Successful login", "Wrong OTP",
    ]


def test_a_reply_that_drops_a_selected_case_is_rejected(monkeypatch):
    at = _revise(_generated(monkeypatch), return_value=_reply(revised=[]))

    assert not at.exception
    assert any("left out TC_LOGIN_002" in error.value for error in at.error)
    assert "pending_revision" not in at.session_state
    assert len(at.session_state["last_result"]["test_cases"]) == 2


def test_a_new_generation_drops_a_pending_revision(monkeypatch):
    at = _revise(_generated(monkeypatch), return_value=_reply())

    with patch.object(AIClient, "generate_test_cases", return_value=_two_case_result()):
        at.button[0].click().run(timeout=30)

    assert not at.exception
    assert "pending_revision" not in at.session_state
