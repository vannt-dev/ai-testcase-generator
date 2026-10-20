"""Per-section generation and merging, with the AI client mocked."""
from unittest.mock import MagicMock

import pytest

from core.batch_generation import generate_section, merge_section_results, section_request
from core.requirement_import import Section


def _case(test_id, covers, title="t"):
    return {
        "test_id": test_id, "module": "M", "title": title, "precondition": "p", "steps": "s",
        "test_data": "d", "expected_result": "e", "priority": "High", "type": "Positive",
        "platform": "Web", "covers": covers,
    }


def _result(criteria, cases, questions=(), usage=None):
    return {
        "acceptance_criteria": [{"id": cid, "text": f"text of {cid}"} for cid in criteria],
        "test_cases": cases,
        "summary": {"total": len(cases), "by_type": {}, "open_questions": list(questions)},
        "usage": usage or {},
    }


SECTIONS = [
    Section("S1", "Login", "Login text"),
    Section("US-7", "Checkout", "Checkout text"),
    Section("S3", "Refunds", "Refund text"),
]


def test_merge_keeps_ids_unique_and_links_pointing_at_the_right_criteria():
    results = {
        "S1": _result(
            ["AC-1", "AC-2", "REQ-9"],
            [_case("TC_001", ["AC-1"]), _case("TC_002", ["AC-2", "REQ-9"])],
            questions=["OTP length?"],
            usage={"provider": "anthropic", "model": "m", "input_tokens": 10, "output_tokens": 5,
                   "total_input_tokens": 10, "estimated_cost_usd": 0.5},
        ),
        "US-7": _result(
            ["AC-1"],
            [_case("TC_001", ["AC-1", "REQ-9"])],
            questions=["Which cards?"],
            usage={"provider": "anthropic", "model": "m", "input_tokens": 1, "output_tokens": 2,
                   "total_input_tokens": 1, "estimated_cost_usd": 0.25},
        ),
    }

    merged = merge_section_results(SECTIONS, results)

    assert [c["id"] for c in merged["acceptance_criteria"]] == ["S1.AC-1", "AC-2", "REQ-9", "US-7.AC-1"]
    assert merged["acceptance_criteria"][0]["text"] == "text of AC-1"
    assert [(t["test_id"], t["covers"]) for t in merged["test_cases"]] == [
        ("TC_001", ["S1.AC-1"]),
        ("TC_002", ["AC-2", "REQ-9"]),
        # A cross-reference to another section's unique id stays as written.
        ("TC_001_2", ["US-7.AC-1", "REQ-9"]),
    ]
    assert merged["summary"]["total"] == 3
    assert merged["summary"]["open_questions"] == ["[Login] OTP length?", "[Checkout] Which cards?"]
    assert merged["usage"]["input_tokens"] == 11
    assert merged["usage"]["output_tokens"] == 7
    assert merged["usage"]["estimated_cost_usd"] == pytest.approx(0.75)
    # The inputs are not changed.
    assert results["S1"]["test_cases"][0]["covers"] == ["AC-1"]


def test_merge_skips_failed_sections_and_reports_no_cost_when_one_is_unknown():
    results = {
        "S1": _result(["AC-1"], [_case("TC_1", ["AC-1"])], usage={"input_tokens": 3, "estimated_cost_usd": 0.1}),
        "S3": _result(["AC-1"], [_case("TC_2", [])], usage={"input_tokens": 4, "estimated_cost_usd": None}),
    }

    merged = merge_section_results(SECTIONS, results)

    assert [c["id"] for c in merged["acceptance_criteria"]] == ["S1.AC-1", "S3.AC-1"]
    assert [t["test_id"] for t in merged["test_cases"]] == ["TC_1", "TC_2"]
    assert merged["usage"]["input_tokens"] == 7
    assert merged["usage"]["estimated_cost_usd"] is None


def test_a_single_section_keeps_its_ids_and_a_reply_without_links_merges():
    legacy = {"test_cases": [{k: v for k, v in _case("TC_1", []).items() if k != "covers"}], "summary": {}}

    merged = merge_section_results(SECTIONS, {"US-7": legacy})

    assert merged["acceptance_criteria"] == []
    assert merged["test_cases"][0]["covers"] == []
    assert merged["usage"] == {}


def test_generate_section_returns_the_result_or_the_error_without_raising():
    client = MagicMock()
    client.generate_test_cases.return_value = {"test_cases": []}

    assert generate_section(client, "SYS", SECTIONS[1], 2, 3, "spec.docx") == ({"test_cases": []}, None)
    system_prompt, request = client.generate_test_cases.call_args.args
    assert system_prompt == "SYS"
    assert request == section_request(SECTIONS[1], 2, 3, "spec.docx")
    assert 'Section 2 of 3 of the requirement file "spec.docx": Checkout' in request
    assert request.endswith("Checkout text")

    client.generate_test_cases.side_effect = ValueError("rate limit")
    assert generate_section(client, "SYS", SECTIONS[0], 1, 3, "spec.docx") == (None, "rate limit")

    client.generate_test_cases.side_effect = KeyError("boom")
    result, error = generate_section(client, "SYS", SECTIONS[0], 1, 3, "spec.docx")
    assert result is None and error.startswith("Unexpected error")
