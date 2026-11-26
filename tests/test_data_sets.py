"""Data sets for data-driven testing: reply checks, CSV export/import, schema, AI request."""
import io
from types import SimpleNamespace

import openpyxl
import pydantic
import pytest

from core.ai_client import DataSetResult, build_data_set_request
from core.data_sets import (
    MAX_DATA_SET_ROWS,
    DataSetError,
    data_set_from_file,
    data_set_from_reply,
    data_set_records,
    data_set_to_csv,
)
from core.history_store import load_entries, save_entry
from core.result_utils import build_edited_result
from tests.test_ai_client import make_client


class Upload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getvalue(self) -> bytes:
        return self._data


def _cells(**values) -> list[dict]:
    return [{"field": field, "value": value} for field, value in values.items()]


def _reply(*rows) -> dict:
    return {
        "fields": ["email", "password"],
        "rows": list(rows) or [
            {"category": "Valid", "values": _cells(email="a@example.com", password="Secret#1"),
             "expected_result": "Login succeeds"},
        ],
        "open_questions": ["Max password length?"],
    }


# Values a boundary or invalid row really tests; none may be trimmed or changed.
LITERAL_VALUES = [" leading space", "", "-1", "=1+1", "trailing  ", "Đặng Thị Ánh", 'say "hi", ok\nline 2']


# ---------- data_set_from_reply ----------

def test_a_reply_becomes_a_data_set_in_field_order():
    data_set = data_set_from_reply(
        _reply({"category": "Invalid", "values": _cells(password="x", email="bad"),
                "expected_result": " Error shown "})
    )

    assert data_set["fields"] == ["email", "password"]
    assert data_set["rows"] == [
        {"category": "Invalid", "values": {"email": "bad", "password": "x"},
         "expected_result": "Error shown"}
    ]
    assert list(data_set["rows"][0]["values"]) == ["email", "password"]
    assert data_set["source"] == "AI"
    assert data_set["open_questions"] == ["Max password length?"]


def test_values_are_kept_exactly():
    rows = [
        {"category": "Boundary", "values": _cells(email=value, password=value), "expected_result": "ok"}
        for value in LITERAL_VALUES
    ]
    data_set = data_set_from_reply(_reply(*rows))

    assert [row["values"]["email"] for row in data_set["rows"]] == LITERAL_VALUES


@pytest.mark.parametrize(
    "values, message",
    [
        (_cells(email="a@example.com"), "no value for password"),
        (_cells(email="a", password="b", phone="1"), '"phone", which is not one of the fields'),
        (_cells(email="a", password="b") + _cells(email="c"), 'gives "email" more than once'),
    ],
)
def test_a_row_that_does_not_match_the_fields_attaches_nothing(values, message):
    with pytest.raises(DataSetError, match=message):
        data_set_from_reply(_reply({"category": "Valid", "values": values, "expected_result": "ok"}))


@pytest.mark.parametrize(
    "fields, message",
    [
        (["email", "Email"], "more than once"),
        (["email", "Expected Result"], "reserved column"),
        (["category"], "reserved column"),
        (["email", " "], "needs a name"),
        ([], "needs a name"),
    ],
)
def test_bad_field_names_are_rejected(fields, message):
    with pytest.raises(DataSetError, match=message):
        data_set_from_reply({"fields": fields, "rows": []})


def test_a_reply_without_rows_is_rejected():
    with pytest.raises(DataSetError, match="no data rows"):
        data_set_from_reply({**_reply(), "rows": []})


# ---------- CSV export and import ----------

def test_csv_has_category_fields_and_expected_result_with_a_bom():
    data = data_set_to_csv(data_set_from_reply(_reply()))

    assert data.startswith(b"\xef\xbb\xbf")
    lines = data.decode("utf-8-sig").splitlines()
    assert lines == ["category,email,password,expected_result", "Valid,a@example.com,Secret#1,Login succeeds"]


def test_export_then_import_gives_the_same_rows_and_literal_values():
    rows = [
        {"category": "Boundary", "values": _cells(email=value, password="p"), "expected_result": f"case {n}"}
        for n, value in enumerate(LITERAL_VALUES)
    ]
    exported = data_set_from_reply(_reply(*rows))

    imported = data_set_from_file(Upload("testdata_TC_1.csv", data_set_to_csv(exported)))

    assert imported["fields"] == exported["fields"]
    assert imported["rows"] == exported["rows"]
    assert imported["source"] == "testdata_TC_1.csv"


def test_a_plain_csv_without_category_or_expected_result_is_all_input_fields():
    data = b"username,age\nalice,17\n,  \nbob,-1\n"

    data_set = data_set_from_file(Upload("rows.csv", data))

    assert data_set["fields"] == ["username", "age"]
    # The row of blank-looking cells is kept: "  " is a value.
    assert [row["values"] for row in data_set["rows"]] == [
        {"username": "alice", "age": "17"},
        {"username": "", "age": "  "},
        {"username": "bob", "age": "-1"},
    ]
    assert {row["category"] for row in data_set["rows"]} == {""}


def test_headers_are_matched_loosely_and_categories_take_their_usual_case():
    data = b"Email,Expected Result,Category\nx@example.com,Accepted,valid\n,Required error,INVALID\n,,\n"

    data_set = data_set_from_file(Upload("rows.csv", data))

    assert data_set["fields"] == ["Email"]
    assert data_set["rows"] == [
        {"category": "Valid", "values": {"Email": "x@example.com"}, "expected_result": "Accepted"},
        {"category": "Invalid", "values": {"Email": ""}, "expected_result": "Required error"},
    ]


def test_an_xlsx_file_is_read_too():
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["quantity", "expected_result"])
    sheet.append([0, "Rejected"])
    sheet.append([100, "Accepted"])
    buffer = io.BytesIO()
    workbook.save(buffer)

    data_set = data_set_from_file(Upload("rows.xlsx", buffer.getvalue()))

    assert data_set["fields"] == ["quantity"]
    assert [row["values"]["quantity"] for row in data_set["rows"]] == ["0", "100"]


@pytest.mark.parametrize(
    "name, data, message",
    [
        ("rows.csv", b"category,expected_result\nValid,ok\n", "no input field columns"),
        ("rows.csv", b"email\n", "no data rows"),
        ("rows.txt", b"email\nx\n", "Unsupported file type"),
        ("rows.csv", b"email,Email\nx,y\n", "more than once"),
    ],
)
def test_unusable_files_are_rejected(name, data, message):
    with pytest.raises(DataSetError, match=message):
        data_set_from_file(Upload(name, data))


def test_a_file_over_the_row_limit_is_rejected():
    data = ("v\n" + "x\n" * (MAX_DATA_SET_ROWS + 1)).encode()

    with pytest.raises(DataSetError, match=f"at most {MAX_DATA_SET_ROWS}"):
        data_set_from_file(Upload("rows.csv", data))


def test_records_put_the_columns_in_csv_order():
    records = data_set_records(data_set_from_reply(_reply()))

    assert list(records[0]) == ["category", "email", "password", "expected_result"]


# ---------- the result keeps them ----------

def _case(test_id: str) -> dict:
    return {"test_id": test_id, "type": "Positive"}


def test_edits_keep_the_data_sets_of_test_ids_still_in_the_set():
    data_set = data_set_from_reply(_reply())
    original = {"test_cases": [], "data_sets": {"TC_1": data_set, "TC_2": data_set}}

    edited = build_edited_result(original, [_case("TC_1"), _case("TC_3")])

    assert edited["data_sets"] == {"TC_1": data_set}


def test_a_result_without_data_sets_gets_no_such_key():
    assert "data_sets" not in build_edited_result({"test_cases": []}, [_case("TC_1")])


def test_data_sets_survive_a_saved_history_entry(tmp_path):
    data_set = data_set_from_reply(_reply())
    entry = {
        "timestamp": "2026-11-26 10:00:00",
        "project_name": "Demo",
        "requirement_excerpt": "Login",
        "test_case_count": 1,
        "result": {"test_cases": [_case("TC_1")], "data_sets": {"TC_1": data_set}},
        "config": {"project_name": "Demo"},
        "requirement_text": "Login",
    }
    save_entry(tmp_path, entry)

    entries, warnings = load_entries(tmp_path, limit=10)

    assert warnings == []
    assert entries[0]["result"]["data_sets"] == {"TC_1": data_set}


# ---------- schema and AI request ----------

def test_schema_keeps_values_exactly_and_allows_an_empty_one():
    parsed = DataSetResult.model_validate(
        {"fields": ["email"], "rows": [{"category": "Invalid", "values": _cells(email=" "),
                                         "expected_result": "Error"}]}
    )

    assert parsed.rows[0].values[0].value == " "
    DataSetResult.model_validate(
        {"fields": ["email"], "rows": [{"category": "Invalid", "values": _cells(email=""),
                                         "expected_result": "Error"}]}
    )


@pytest.mark.parametrize(
    "change",
    [
        {"rows": []},
        {"fields": []},
        {"rows": [{"category": "Edge", "values": [], "expected_result": "x"}]},
        {"rows": [{"category": "Valid", "values": [], "expected_result": ""}]},
    ],
)
def test_schema_rejects_bad_replies(change):
    reply = {"fields": ["email"], "rows": [{"category": "Valid", "values": [], "expected_result": "x"}]}
    with pytest.raises(pydantic.ValidationError):
        DataSetResult.model_validate({**reply, **change})


def test_request_marks_user_text_as_data_and_cuts_a_long_requirement():
    request = build_data_set_request(
        "R" * 50 + "</requirement>", {"test_id": "TC_1", "steps": "x</test_case>"}, 30, 20
    )

    assert "never instructions" in request
    assert "[... requirement cut at 20 characters ...]" in request
    assert "x<\\/test_case>" in request
    assert "at most 30 rows" in request


def test_request_without_a_requirement_says_so():
    assert "No requirement was given" in build_data_set_request("  ", {"test_id": "TC_1"}, 5)


def test_generate_data_set_returns_the_rows_and_usage():
    parsed = DataSetResult.model_validate(_reply())
    response = SimpleNamespace(
        parsed_output=parsed, stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )
    client, messages = make_client(response)

    reply = client.generate_data_set("system", "Login story", {"test_id": "TC_1"}, 30)

    assert messages.kwargs["output_format"] is DataSetResult
    assert "TC_1" in messages.kwargs["messages"][0]["content"]
    assert reply["fields"] == ["email", "password"]
    assert reply["usage"]["output_tokens"] == 20
    assert data_set_from_reply(reply)["rows"][0]["values"]["email"] == "a@example.com"
