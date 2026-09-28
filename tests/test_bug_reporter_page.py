"""Integration tests for pages/2_Bug_Reporter.py using Streamlit AppTest."""
from pathlib import Path
from unittest.mock import patch

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

    _write(at, notes="login button does nothing", result=_fake_result(title="Login button does nothing",
                                                                       steps_to_reproduce=["Tap Login"]))

    assert at.text_input(key="bug_title").value == "Login button does nothing"
    assert at.text_area(key="bug_steps").value == "Tap Login"


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
