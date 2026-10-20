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


def test_platform_options_match_the_test_case_model():
    from typing import get_args

    from core.ai_client import TestCase
    from core.result_utils import PLATFORM_OPTIONS

    assert PLATFORM_OPTIONS == ["Web", "iOS", "Android", "API", "All"]
    assert set(PLATFORM_OPTIONS) == set(get_args(TestCase.model_fields["platform"].annotation))


def test_parse_covers_accepts_lists_text_and_missing_values():
    from core.result_utils import parse_covers

    assert parse_covers(["AC-1", " AC-2 ", "", None, "AC-1"]) == ["AC-1", "AC-2"]
    assert parse_covers("AC-1, AC-2;AC-3\nAC-4") == ["AC-1", "AC-2", "AC-3", "AC-4"]
    assert parse_covers(None) == []
    assert parse_covers(float("nan")) == []
    assert parse_covers("") == []


def test_editor_round_trip_keeps_covers_and_it_never_blocks_export():
    from core.result_utils import records_for_editor

    shown = records_for_editor([complete_test_case(covers=["AC-1", "AC-2"])])
    assert shown[0]["covers"] == "AC-1, AC-2"

    edited = normalize_edited_records([{**shown[0], "covers": "AC-2, AC-5"}, complete_test_case()])

    assert edited[0]["covers"] == ["AC-2", "AC-5"]
    assert edited[1]["covers"] == []
    assert find_incomplete_rows(edited) == []


def test_build_edited_result_keeps_the_acceptance_criteria():
    criteria = [{"id": "AC-1", "text": "Log in"}]

    result = build_edited_result({"acceptance_criteria": criteria}, [complete_test_case()])

    assert result["acceptance_criteria"] == criteria
    assert result["acceptance_criteria"][0] is not criteria[0]
    assert build_edited_result({}, [])["acceptance_criteria"] == []
