"""Normalize results after AI generation or user edits made in the UI."""
import math
import re

TEST_CASE_FIELDS = (
    "test_id",
    "module",
    "title",
    "precondition",
    "steps",
    "test_data",
    "expected_result",
    "priority",
    "type",
    "platform",
)

# Besides these, a test case may carry `covers`: the ids of the acceptance
# criteria it verifies, as a list of strings. It is optional, so it is not in
# TEST_CASE_FIELDS and an empty value never blocks an export.
_COVERS_SEPARATOR = re.compile(r"[,;\n]+")

# The platform choices of the test case editors; mirrors TestCase.platform.
PLATFORM_OPTIONS = ["Web", "iOS", "Android", "API", "All"]

TYPE_KEYS = {
    "Positive": "positive",
    "Negative": "negative",
    "Edge case": "edge_case",
    "UI/UX": "ui_ux",
    "Compatibility": "compatibility",
    "Performance": "performance",
    "Security": "security",
}


def parse_covers(value) -> list[str]:
    """
    The criterion ids of a `covers` value: a list, or text separated by commas,
    semicolons or new lines as typed in an editor. Missing values give [].
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, str):
        items = _COVERS_SEPARATOR.split(value)
    elif isinstance(value, (list, tuple, set)) or hasattr(value, "tolist"):
        items = list(value.tolist() if hasattr(value, "tolist") else value)
    else:
        items = [value]
    ids = (" ".join(str(item).split()) for item in items if item is not None)
    return list(dict.fromkeys(item for item in ids if item))


def covers_text(value) -> str:
    """`covers` as one editable cell: "AC-1, AC-2"."""
    return ", ".join(parse_covers(value))


def records_for_editor(test_cases: list[dict]) -> list[dict]:
    """Test cases with `covers` as text, since a list column cannot be edited in a table."""
    return [
        {**test_case, "covers": covers_text(test_case.get("covers"))}
        for test_case in test_cases
    ]


def normalize_edited_records(records: list[dict]) -> list[dict]:
    """Drop blank rows and keep only the supported test case columns."""
    normalized = []
    for record in records:
        cleaned = {
            field: "" if record.get(field) is None else str(record.get(field)).strip()
            for field in TEST_CASE_FIELDS
        }
        if any(cleaned.values()):
            cleaned["covers"] = parse_covers(record.get("covers"))
            normalized.append(cleaned)
    return normalized


def find_incomplete_rows(test_cases: list[dict]) -> list[int]:
    """Return 1-based row numbers for rows still missing required data."""
    return [
        index
        for index, test_case in enumerate(test_cases, start=1)
        if any(not str(test_case.get(field, "")).strip() for field in TEST_CASE_FIELDS)
    ]


def build_edited_result(original_result: dict, test_cases: list[dict]) -> dict:
    """Merge edited data and recompute the summary so UI/Excel stay in sync."""
    by_type = {key: 0 for key in TYPE_KEYS.values()}
    for test_case in test_cases:
        type_key = TYPE_KEYS.get(test_case.get("type"))
        if type_key:
            by_type[type_key] += 1

    original_summary = original_result.get("summary", {})
    return {
        "acceptance_criteria": [
            dict(criterion) for criterion in original_result.get("acceptance_criteria", [])
        ],
        "test_cases": test_cases,
        "summary": {
            "total": len(test_cases),
            "by_type": by_type,
            "open_questions": list(original_summary.get("open_questions", [])),
        },
        "usage": dict(original_result.get("usage", {})),
    }
