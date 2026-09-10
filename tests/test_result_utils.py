from core.result_utils import (
    build_edited_result,
    find_incomplete_rows,
    normalize_edited_records,
)


def complete_test_case(**overrides):
    test_case = {
        "test_id": "TC_001",
        "module": "Login",
        "title": "Login successfully",
        "precondition": "User exists",
        "steps": "1. Login",
        "test_data": "Valid user",
        "expected_result": "Home is shown",
        "priority": "High",
        "type": "Positive",
        "platform": "Web",
    }
    test_case.update(overrides)
    return test_case


def test_normalize_edited_records_filters_blank_rows_and_unknown_columns():
    records = [complete_test_case(extra="ignored"), {"test_id": None}]

    normalized = normalize_edited_records(records)

    assert len(normalized) == 1
    assert "extra" not in normalized[0]


def test_find_incomplete_rows():
    rows = [complete_test_case(), complete_test_case(title="")]

    assert find_incomplete_rows(rows) == [2]


def test_build_edited_result_recalculates_summary_and_preserves_metadata():
    original = {
        "summary": {"open_questions": ["Confirm timeout?"]},
        "usage": {"input_tokens": 10},
    }
    rows = [complete_test_case(), complete_test_case(type="Security")]

    result = build_edited_result(original, rows)

    assert result["summary"]["total"] == 2
    assert result["summary"]["by_type"]["positive"] == 1
    assert result["summary"]["by_type"]["security"] == 1
    assert result["summary"]["open_questions"] == ["Confirm timeout?"]
    assert result["usage"] == {"input_tokens": 10}
