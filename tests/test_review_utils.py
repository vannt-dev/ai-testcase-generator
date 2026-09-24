import pytest

from core.review_utils import apply_column_mapping


def test_apply_column_mapping_rekeys_rows_to_target_fields():
    raw_rows = [{"ID": "TC_001", "Name": "Login works", "Steps": "1. Login"}]
    mapping = {"test_id": "ID", "title": "Name", "steps": "Steps"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result == [
        {
            "test_id": "TC_001",
            "module": "",
            "title": "Login works",
            "precondition": "",
            "steps": "1. Login",
            "test_data": "",
            "expected_result": "",
            "priority": "",
            "type": "",
            "platform": "",
        }
    ]


def test_apply_column_mapping_handles_unmapped_field_as_empty():
    raw_rows = [{"ID": "TC_001"}]
    mapping = {"test_id": "ID"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result[0]["title"] == ""


def test_apply_column_mapping_stringifies_non_string_values():
    raw_rows = [{"ID": 42}]
    mapping = {"test_id": "ID"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result[0]["test_id"] == "42"


def test_apply_column_mapping_preserves_falsy_but_valid_values():
    raw_rows = [{"ID": "TC_001", "Count": 0, "Flag": False}]
    mapping = {"test_id": "ID", "module": "Count", "title": "Flag"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result[0]["test_id"] == "TC_001"
    assert result[0]["module"] == "0"
    assert result[0]["title"] == "False"


@pytest.mark.parametrize(
    "value", ["-1", "- Open the app\n- Tap Login", "+84 912 345 678", "@admin", "=1+1"]
)
def test_apply_column_mapping_keeps_uploaded_values_literal(value):
    # Negative boundaries, bullet steps and phone numbers are ordinary test data.
    result = apply_column_mapping([{"ID": value}], {"test_id": "ID"})

    assert result[0]["test_id"] == value


def test_formula_like_uploaded_values_export_as_text_cells():
    # The spreadsheet injection guard lives in the exporter, which writes literal text cells.
    import io

    import openpyxl

    from core.excel_exporter import export_to_excel

    dangerous = '=HYPERLINK("http://evil","click")'
    rows = apply_column_mapping([{"ID": dangerous, "D": "-1"}], {"test_id": "ID", "test_data": "D"})
    sheet = openpyxl.load_workbook(io.BytesIO(export_to_excel({"test_cases": rows}))).active

    assert (sheet["A2"].value, sheet["A2"].data_type) == (dangerous, "s")
    assert (sheet["F2"].value, sheet["F2"].data_type) == ("-1", "s")


def test_apply_column_mapping_leaves_safe_values_untouched():
    result = apply_column_mapping([{"ID": "TC_001"}], {"test_id": "ID"})

    assert result[0]["test_id"] == "TC_001"


from core.review_utils import merge_test_cases


def test_merge_test_cases_appends_without_collision():
    existing = [{"test_id": "TC_001", "title": "A"}]
    new = [{"test_id": "TC_002", "title": "B"}]

    result = merge_test_cases(existing, new)

    assert [tc["test_id"] for tc in result] == ["TC_001", "TC_002"]


def test_merge_test_cases_renames_colliding_test_id():
    existing = [{"test_id": "TC_001", "title": "A"}]
    new = [{"test_id": "TC_001", "title": "B (new)"}]

    result = merge_test_cases(existing, new)

    ids = [tc["test_id"] for tc in result]
    assert ids == ["TC_001", "TC_001_2"]
    assert result[1]["title"] == "B (new)"


def test_merge_test_cases_renames_multiple_collisions_sequentially():
    existing = [{"test_id": "TC_001"}, {"test_id": "TC_001_2"}]
    new = [{"test_id": "TC_001"}]

    result = merge_test_cases(existing, new)

    assert [tc["test_id"] for tc in result] == ["TC_001", "TC_001_2", "TC_001_3"]


def test_merge_test_cases_does_not_mutate_inputs():
    existing = [{"test_id": "TC_001"}]
    new = [{"test_id": "TC_001"}]

    merge_test_cases(existing, new)

    assert new[0]["test_id"] == "TC_001"
