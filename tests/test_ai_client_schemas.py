"""Pure schema/unit tests for the Reviewer Pydantic models (no AI client mocking)."""
import copy
import pydantic
import pytest

from core.ai_client import (
    ApiAutomationResult,
    AutomationResult,
    BugReport,
    ColumnMappingResult,
    CoverageGap,
    DuplicateGroup,
    HealingResult,
    ReviewResult,
)

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


def _bug_payload(**overrides):
    payload = {
        "title": "Crash on pay",
        "module": "Checkout",
        "severity": "Critical",
        "priority": "High",
        "reproducibility": "Unknown",
        "build_version": "",
        "environment": "",
        "preconditions": "",
        "steps_to_reproduce": ["Tap Pay"],
        "expected_result": "Payment succeeds",
        "actual_result": "App crashes",
        "test_data": "",
        "related_test_id": "",
        "open_questions": [],
    }
    payload.update(overrides)
    return payload


def test_bug_report_accepts_valid_payload():
    assert BugReport.model_validate(_bug_payload()).severity == "Critical"


@pytest.mark.parametrize(
    "overrides",
    [
        {"severity": "Blocker"},
        {"priority": "Urgent"},
        {"reproducibility": "Sometimes"},
        {"steps_to_reproduce": []},
        {"title": "   "},
        {"actual_result": ""},
    ],
)
def test_bug_report_rejects_invalid_values(overrides):
    with pytest.raises(pydantic.ValidationError):
        BugReport.model_validate(_bug_payload(**overrides))


# ---------- AutomationResult ----------

VALID_AUTOMATION = {
    "pages": [
        {
            "name": "LoginPage",
            "path": "/login",
            "locators": [
                {"key": "emailInput", "strategy": "label", "role": "", "value": "Email", "confident": True}
            ],
        }
    ],
    "tests": [
        {
            "test_id": "TC_001",
            "title": "Login works",
            "steps": [
                {"action": "fill", "page": "LoginPage", "locator": "emailInput",
                 "value": "a@b.c", "source": "Enter email"}
            ],
        }
    ],
    "open_questions": [],
}


def test_automation_result_accepts_valid_input():
    result = AutomationResult.model_validate(VALID_AUTOMATION)

    assert result.tests[0].steps[0].action == "fill"
    assert result.pages[0].locators[0].strategy == "label"


def test_automation_result_rejects_unknown_action():
    data = copy.deepcopy(VALID_AUTOMATION)
    data["tests"][0]["steps"][0]["action"] = "hover"

    with pytest.raises(pydantic.ValidationError):
        AutomationResult.model_validate(data)


def test_automation_result_rejects_unknown_strategy():
    data = copy.deepcopy(VALID_AUTOMATION)
    data["pages"][0]["locators"][0]["strategy"] = "xpath"

    with pytest.raises(pydantic.ValidationError):
        AutomationResult.model_validate(data)


def test_automation_result_requires_every_step_field():
    data = copy.deepcopy(VALID_AUTOMATION)
    del data["tests"][0]["steps"][0]["value"]

    with pytest.raises(pydantic.ValidationError):
        AutomationResult.model_validate(data)


# ---------- HealingResult ----------

VALID_HEALING = {
    "verdict": "fixed",
    "fixes": [
        {"key": "submitButton", "strategy": "role", "role": "button", "value": "Log in",
         "confident": True, "reason": "Button text changed"}
    ],
    "explanation": "The sign-in button was renamed.",
}


def test_healing_result_accepts_valid_input():
    result = HealingResult.model_validate(VALID_HEALING)

    assert result.verdict == "fixed"
    assert result.fixes[0].key == "submitButton"


def test_healing_result_rejects_unknown_verdict():
    data = copy.deepcopy(VALID_HEALING)
    data["verdict"] = "maybe"

    with pytest.raises(pydantic.ValidationError):
        HealingResult.model_validate(data)


def test_healing_fix_value_keeps_its_spaces():
    data = copy.deepcopy(VALID_HEALING)
    data["fixes"][0]["value"] = " Log in "

    assert HealingResult.model_validate(data).fixes[0].value == " Log in "


def test_healing_result_requires_a_reason_per_fix():
    data = copy.deepcopy(VALID_HEALING)
    del data["fixes"][0]["reason"]

    with pytest.raises(pydantic.ValidationError):
        HealingResult.model_validate(data)


def test_test_case_accepts_the_api_platform():
    from core.ai_client import TestCase  # imported here: pytest would try to collect a module-level Test* class

    case = TestCase.model_validate({
        "test_id": "TC_ORD_001", "module": "Orders", "title": "Create an order",
        "precondition": "A valid token", "steps": "1. POST /orders",
        "test_data": '{"sku": "A-1", "quantity": 2}', "expected_result": "201 and an id",
        "priority": "High", "type": "Positive", "platform": "API",
    })

    assert case.platform == "API"


# ---------- ApiAutomationResult ----------

VALID_API_AUTOMATION = {
    "tests": [{
        "test_id": "TC_ORD_001", "title": "Create an order",
        "steps": [{
            "action": "request", "method": "POST", "path": "/orders",
            "headers": [{"name": "Authorization", "value": "Bearer ${ENV:API_TOKEN}"}],
            "query": [], "body": '{"sku": "A-1"}', "expect_status": 201,
            "checks": [{"kind": "json_exists", "path": "id", "value": ""}],
            "saves": [{"var": "orderId", "path": "id"}],
            "confident": True, "source": "1. POST /orders",
        }],
    }],
    "open_questions": [],
}


def test_api_automation_result_accepts_valid_input():
    result = ApiAutomationResult.model_validate(VALID_API_AUTOMATION)

    assert result.tests[0].steps[0].saves[0].var == "orderId"


def test_api_automation_result_rejects_unknown_action_and_check_kind():
    for field, value in (("action", "click"), ("checks", [{"kind": "regex", "path": "", "value": ""}])):
        data = copy.deepcopy(VALID_API_AUTOMATION)
        data["tests"][0]["steps"][0][field] = value
        with pytest.raises(pydantic.ValidationError):
            ApiAutomationResult.model_validate(data)
