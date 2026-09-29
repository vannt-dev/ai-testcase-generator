"""Integration tests for pages/4_Heal_Locators.py using Streamlit AppTest."""
import copy
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient
from core.playwright_renderer import render_page

PAGE_PATH = Path(__file__).parent.parent / "pages" / "4_Heal_Locators.py"

SOURCE = render_page({"name": "LoginPage", "var": "loginPage", "path": "/login", "locators": [
    {"key": "emailInput", "strategy": "label", "role": "", "value": "Email", "confident": True},
    {"key": "submitButton", "strategy": "role", "role": "button", "value": "Sign in", "confident": False},
]})

FAKE_HEALING = {
    "healing": {
        "verdict": "fixed",
        "fixes": [
            {"key": "submitButton", "strategy": "role", "role": "button", "value": "Log in",
             "confident": True, "reason": "Button text changed"},
            {"key": "emailInput", "strategy": "test_id", "role": "", "value": "email",
             "confident": False, "reason": "Label removed"},
        ],
        "explanation": "The sign-in button was renamed.",
    },
    "usage": {"model": "claude-sonnet-5", "input_tokens": 10, "output_tokens": 5, "estimated_cost_usd": 0.001},
}


def _app(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)
    return at


def _fill(at, source=SOURCE, name="LoginPage.ts"):
    at.file_uploader(key="heal_file").upload(name, source.encode("utf-8"), "text/plain").run(timeout=30)
    at.text_area(key="heal_error").set_value("Error: locator.click: Timeout 30000ms exceeded").run(timeout=30)
    at.text_area(key="heal_snapshot").set_value("<button>Log in</button>").run(timeout=30)


def _heal(at, response=FAKE_HEALING):
    with patch.object(AIClient, "heal_locators", return_value=response) as mocked:
        at.button(key="heal_btn").click().run(timeout=30)
    return mocked


def _codes(at):
    return [code.value for code in at.code]


def test_button_is_disabled_until_everything_is_given(monkeypatch):
    at = _app(monkeypatch)

    assert at.button(key="heal_btn").disabled is True
    assert any("Upload a page object file" in warning.value for warning in at.warning)

    _fill(at)
    assert at.button(key="heal_btn").disabled is False


def test_invalid_file_shows_an_error(monkeypatch):
    at = _app(monkeypatch)
    at.file_uploader(key="heal_file").upload("x.ts", b"\xff\xfe\x00", "text/plain").run(timeout=30)

    assert any("not UTF-8" in error.value for error in at.error)
    assert at.button(key="heal_btn").disabled is True


def test_heal_shows_fixes_diff_and_download(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    mocked = _heal(at)

    assert not at.exception
    system_prompt, file_name, locators, error_text, snapshot = mocked.call_args.args
    assert "behaviour_changed" in system_prompt
    assert file_name == "LoginPage.ts"
    assert [loc["key"] for loc in locators] == ["emailInput", "submitButton"]
    assert snapshot == "<button>Log in</button>"
    assert any('+    this.submitButton = page.getByRole("button", { name: "Log in" });' in c for c in _codes(at))
    assert any('+    this.emailInput = page.getByTestId("email");' in c for c in _codes(at))
    assert len(at.get("download_button")) == 1


def test_unchecking_a_fix_removes_it_from_the_diff(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    _heal(at)
    at.checkbox[1].uncheck().run(timeout=30)

    diffs = [c for c in _codes(at) if c.startswith("--- a/")]
    assert len(diffs) == 1
    assert "getByTestId" not in diffs[0]
    assert "Log in" in diffs[0]


def test_unchecking_every_fix_hides_the_download(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    _heal(at)
    at.checkbox[0].uncheck().run(timeout=30)
    at.checkbox[1].uncheck().run(timeout=30)

    assert len(at.get("download_button")) == 0
    assert any("No fix selected" in info.value for info in at.info)


def test_a_verdict_other_than_fixed_warns_about_a_possible_bug(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    response = copy.deepcopy(FAKE_HEALING)
    response["healing"].update(verdict="behaviour_changed", fixes=[])
    _heal(at, response)

    assert any("may be a real bug" in warning.value for warning in at.warning)
    assert any("proposed no locator changes" in info.value for info in at.info)


def test_validation_warnings_are_listed(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    response = copy.deepcopy(FAKE_HEALING)
    response["healing"]["fixes"].append({"key": "ghost", "strategy": "text", "role": "", "value": "x",
                                         "confident": True, "reason": "r"})
    _heal(at, response)

    assert any("'ghost', which is not a locator in this file" in md.value for md in at.text)


def test_ai_text_is_shown_as_plain_text(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    response = copy.deepcopy(FAKE_HEALING)
    response["healing"]["explanation"] = "Renamed ![x](https://evil.test/a.png)"
    response["healing"]["fixes"][0]["reason"] = "[click](https://evil.test/b)"
    _heal(at, response)

    assert not any("evil.test" in md.value for md in at.markdown)
    assert not any("evil.test" in caption.value for caption in at.caption)
    assert any("https://evil.test/a.png" in text.value for text in at.text)
    assert any("https://evil.test/b" in text.value for text in at.text)


def test_healing_again_resets_the_checkboxes(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    _heal(at)
    at.checkbox[0].uncheck().run(timeout=30)
    _heal(at)

    assert [box.value for box in at.checkbox] == [True, True]


def test_file_without_locators_shows_an_error(monkeypatch):
    at = _app(monkeypatch)
    at.file_uploader(key="heal_file").upload("util.ts", b"export const a = 1;\n", "text/plain").run(timeout=30)

    assert any("no one-line" in error.value for error in at.error)


def test_new_upload_clears_the_result(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    _heal(at)
    at.file_uploader(key="heal_file").upload(
        "LoginPage.ts", SOURCE.replace("Sign in", "Enter").encode("utf-8"), "text/plain",
    ).run(timeout=30)

    assert "healing_result" not in at.session_state


def test_editing_the_error_clears_the_result(monkeypatch):
    at = _app(monkeypatch)
    _fill(at)
    _heal(at)
    at.text_area(key="heal_error").set_value("Error: something else").run(timeout=30)

    assert "healing_result" not in at.session_state


def test_a_fix_that_drops_a_chain_starts_unticked(monkeypatch):
    at = _app(monkeypatch)
    _fill(at, source=SOURCE.replace('page.getByLabel("Email")', 'page.getByLabel("Email").first()'))
    _heal(at)

    assert [box.value for box in at.checkbox] == [True, False]
    assert any("chained calls or options" in md.value for md in at.text)
