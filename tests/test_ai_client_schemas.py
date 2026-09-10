"""Pure schema/unit tests for the Reviewer Pydantic models (no AI client mocking)."""
import pydantic
import pytest

from core.ai_client import ColumnMappingResult, CoverageGap, DuplicateGroup, ReviewResult

VALID_GAP = {
    "description": "No test for OTP resend after expiry",
    "suggested_type": "Negative",
    "severity": "High",
}

VALID_DUPLICATE = {"test_ids": ["TC_001", "TC_002"], "reason": "Same login happy path"}

VALID_REVIEW = {
    "coverage_score": 80,
    "missing_test_types": ["Security"],
    "gaps": [VALID_GAP],
    "duplicates": [VALID_DUPLICATE],
    "summary_note": "Mostly covered.",
}


# ---------- CoverageGap ----------

def test_coverage_gap_accepts_valid_input():
    gap = CoverageGap.model_validate(VALID_GAP)

    assert gap.severity == "High"
    assert gap.suggested_type == "Negative"


def test_coverage_gap_rejects_invalid_severity():
    with pytest.raises(pydantic.ValidationError):
        CoverageGap.model_validate({**VALID_GAP, "severity": "Critical"})


def test_coverage_gap_rejects_invalid_suggested_type():
    with pytest.raises(pydantic.ValidationError):
        CoverageGap.model_validate({**VALID_GAP, "suggested_type": "Regression"})


def test_coverage_gap_rejects_missing_required_field():
    with pytest.raises(pydantic.ValidationError):
        CoverageGap.model_validate({"suggested_type": "Negative", "severity": "High"})


def test_coverage_gap_rejects_empty_description():
    with pytest.raises(pydantic.ValidationError):
        CoverageGap.model_validate({**VALID_GAP, "description": ""})


# ---------- DuplicateGroup ----------

def test_duplicate_group_accepts_valid_input():
    group = DuplicateGroup.model_validate(VALID_DUPLICATE)

    assert group.test_ids == ["TC_001", "TC_002"]


def test_duplicate_group_rejects_fewer_than_two_test_ids():
    with pytest.raises(pydantic.ValidationError):
        DuplicateGroup.model_validate({"test_ids": ["TC_001"], "reason": "Only one id"})


def test_duplicate_group_rejects_missing_reason():
    with pytest.raises(pydantic.ValidationError):
        DuplicateGroup.model_validate({"test_ids": ["TC_001", "TC_002"]})


# ---------- ReviewResult ----------

def test_review_result_accepts_valid_input():
    review = ReviewResult.model_validate(VALID_REVIEW)

    assert review.coverage_score == 80
    assert review.gaps[0].severity == "High"
    assert review.duplicates[0].test_ids == ["TC_001", "TC_002"]


@pytest.mark.parametrize("score", [-1, 101])
def test_review_result_rejects_coverage_score_outside_range(score):
    with pytest.raises(pydantic.ValidationError):
        ReviewResult.model_validate({**VALID_REVIEW, "coverage_score": score})


def test_review_result_rejects_missing_required_field():
    payload = {k: v for k, v in VALID_REVIEW.items() if k != "coverage_score"}

    with pytest.raises(pydantic.ValidationError):
        ReviewResult.model_validate(payload)


def test_review_result_rejects_invalid_nested_gap_severity():
    payload = {**VALID_REVIEW, "gaps": [{**VALID_GAP, "severity": "Blocker"}]}

    with pytest.raises(pydantic.ValidationError):
        ReviewResult.model_validate(payload)


# ---------- ColumnMappingResult ----------

def test_column_mapping_result_accepts_arbitrary_string_mapping():
    result = ColumnMappingResult.model_validate(
        {"mapping": {"test_id": "ID", "title": "Name", "platform": ""}}
    )

    assert result.mapping == {"test_id": "ID", "title": "Name", "platform": ""}


def test_column_mapping_result_rejects_missing_mapping():
    with pytest.raises(pydantic.ValidationError):
        ColumnMappingResult.model_validate({})


def test_column_mapping_result_rejects_non_string_mapping_value():
    with pytest.raises(pydantic.ValidationError):
        ColumnMappingResult.model_validate({"mapping": {"test_id": ["ID"]}})
