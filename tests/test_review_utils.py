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


def test_apply_column_mapping_quote_prefixes_formula_injection():
    raw_rows = [{"ID": '=HYPERLINK("http://evil","click")'}]
    mapping = {"test_id": "ID"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result[0]["test_id"].startswith("'=")
    assert not result[0]["test_id"].startswith("=")


@pytest.mark.parametrize("dangerous", ["=1+1", "+1", "-1+1", "@SUM(A1)"])
def test_apply_column_mapping_quote_prefixes_all_formula_triggers(dangerous):
    result = apply_column_mapping([{"ID": dangerous}], {"test_id": "ID"})

    assert result[0]["test_id"] == "'" + dangerous


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
