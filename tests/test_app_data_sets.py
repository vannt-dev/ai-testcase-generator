"""The Generator's test data sets, with AIClient mocked (no real API calls)."""
from unittest.mock import patch

from core.ai_client import AIClient
from core.data_sets import MAX_AI_ROWS
from core.prompt_builder import DATA_SET_PROMPT_PATH
from tests.test_app_revision import _generated, _reply as _revision_reply, _revise


def _data_reply(**overrides) -> dict:
    reply = {
        "fields": ["phone", "otp"],
        "rows": [
            {"category": "Valid", "values": [{"field": "phone", "value": "0912345678"},
                                             {"field": "otp", "value": "123456"}],
             "expected_result": "Home page is reached"},
            {"category": "Invalid", "values": [{"field": "phone", "value": "0912345678"},
                                               {"field": "otp", "value": ""}],
             "expected_result": "Error: OTP is required"},
        ],
        "open_questions": ["Is the OTP always 6 digits?"],
        "usage": {"provider": "anthropic", "model": "claude-sonnet-5", "input_tokens": 12,
                  "output_tokens": 34, "estimated_cost_usd": 0.0002},
    }
    reply.update(overrides)
    return reply


def _generate_rows(at, test_id="TC_LOGIN_002", **patch_kwargs):
    at.selectbox(key="data_set_case").set_value(test_id).run(timeout=30)
    patch_kwargs.setdefault("return_value", _data_reply())
    with patch.object(AIClient, "generate_data_set", **patch_kwargs) as generate:
        at.button(key="data_set_generate_btn").click().run(timeout=30)
    at.generate_mock = generate
    return at


def _data_sets(at) -> dict:
    return at.session_state["last_result"].get("data_sets", {})


def test_the_prompt_file_exists():
    assert "Write a data set" in DATA_SET_PROMPT_PATH.read_text(encoding="utf-8")


def test_generated_rows_are_attached_to_the_selected_case(monkeypatch):
    at = _generate_rows(_generated(monkeypatch))

    assert not at.exception
    args = at.generate_mock.call_args.args
    assert "Write a data set" in args[0]
    assert args[1] == "OTP login story"
    assert args[2]["test_id"] == "TC_LOGIN_002"
    assert args[3] == MAX_AI_ROWS
    data_set = _data_sets(at)["TC_LOGIN_002"]
    assert data_set["fields"] == ["phone", "otp"]
    assert data_set["rows"][1]["values"]["otp"] == ""
    assert data_set["usage"]["output_tokens"] == 34
    assert list(_data_sets(at)) == ["TC_LOGIN_002"]
    # The test cases, and the history entry made at generation, are left as they were.
    assert len(at.session_state["last_result"]["test_cases"]) == 2
    assert "data_sets" not in at.session_state["history"][-1]["result"]
    assert any("Is the OTP always 6 digits?" in md.value for md in at.markdown)
    assert any("2 data rows" in md.value for md in at.markdown)


def test_an_ai_error_or_a_bad_reply_attaches_nothing(monkeypatch):
    at = _generate_rows(_generated(monkeypatch), side_effect=ValueError("Rate limit."))

    assert not at.exception
    assert any("Could not write the data set: Rate limit." in e.value for e in at.error)
    assert _data_sets(at) == {}

    bad = _data_reply(rows=[{"category": "Valid", "values": [{"field": "phone", "value": "1"}],
                             "expected_result": "ok"}])
    at = _generate_rows(at, return_value=bad)

    assert any("no value for otp" in e.value for e in at.error)
    assert _data_sets(at) == {}


def test_a_csv_file_is_attached_on_click_and_can_be_removed(monkeypatch):
    at = _generated(monkeypatch)
    at.selectbox(key="data_set_case").set_value("TC_LOGIN_001").run(timeout=30)
    assert at.button(key="data_set_attach_btn").disabled

    csv_bytes = b"phone,expected_result\n,Phone is required\n09123,Too short\n"
    at.file_uploader(key="data_set_file").upload("otp_rows.csv", csv_bytes, "text/csv").run(timeout=30)
    # Choosing the file attaches nothing yet.
    assert _data_sets(at) == {}
    at.button(key="data_set_attach_btn").click().run(timeout=30)

    assert not at.exception
    data_set = _data_sets(at)["TC_LOGIN_001"]
    assert data_set["source"] == "otp_rows.csv"
    assert [row["values"]["phone"] for row in data_set["rows"]] == ["", "09123"]

    at.button(key="data_set_remove_btn").click().run(timeout=30)
    assert _data_sets(at) == {}


def test_a_bad_file_shows_an_error(monkeypatch):
    at = _generated(monkeypatch)
    at.file_uploader(key="data_set_file").upload(
        "rows.csv", b"category,expected_result\nValid,ok\n", "text/csv"
    ).run(timeout=30)
    at.button(key="data_set_attach_btn").click().run(timeout=30)

    assert not at.exception
    assert any("no input field columns" in e.value for e in at.error)
    assert _data_sets(at) == {}


def test_attached_rows_survive_an_accepted_revision(monkeypatch):
    at = _generate_rows(_generated(monkeypatch), test_id="TC_LOGIN_001")
    data_set = _data_sets(at)["TC_LOGIN_001"]

    at = _revise(at, return_value=_revision_reply())
    at.button(key="accept_revision_btn").click().run(timeout=30)

    assert not at.exception
    assert len(at.session_state["last_result"]["test_cases"]) == 3
    assert _data_sets(at) == {"TC_LOGIN_001": data_set}
    # The accepted set goes into the history with its data rows.
    assert at.session_state["history"][-1]["result"]["data_sets"] == {"TC_LOGIN_001": data_set}


def test_attached_rows_offer_a_csv_download(monkeypatch):
    at = _generate_rows(_generated(monkeypatch))

    assert not at.exception
    labels = [button.proto.label for button in at.get("download_button")]
    assert "⬇️ Download data set (.csv)" in labels
