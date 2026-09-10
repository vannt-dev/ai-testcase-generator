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
