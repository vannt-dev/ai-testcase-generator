"""Chuẩn hóa kết quả sau khi AI sinh hoặc người dùng chỉnh sửa trên UI."""

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

TYPE_KEYS = {
    "Positive": "positive",
    "Negative": "negative",
    "Edge case": "edge_case",
    "UI/UX": "ui_ux",
    "Compatibility": "compatibility",
    "Performance": "performance",
    "Security": "security",
}


def normalize_edited_records(records: list[dict]) -> list[dict]:
    """Lọc dòng trống và chỉ giữ các cột test case được hỗ trợ."""
    normalized = []
    for record in records:
        cleaned = {
            field: "" if record.get(field) is None else str(record.get(field)).strip()
            for field in TEST_CASE_FIELDS
        }
        if any(cleaned.values()):
            normalized.append(cleaned)
    return normalized


def find_incomplete_rows(test_cases: list[dict]) -> list[int]:
    """Trả về số thứ tự (bắt đầu từ 1) của các dòng còn thiếu dữ liệu."""
    return [
        index
        for index, test_case in enumerate(test_cases, start=1)
        if any(not str(test_case.get(field, "")).strip() for field in TEST_CASE_FIELDS)
    ]


def build_edited_result(original_result: dict, test_cases: list[dict]) -> dict:
    """Ghép dữ liệu đã sửa và tính lại summary để UI/Excel luôn đồng bộ."""
    by_type = {key: 0 for key in TYPE_KEYS.values()}
    for test_case in test_cases:
        type_key = TYPE_KEYS.get(test_case.get("type"))
        if type_key:
            by_type[type_key] += 1

    original_summary = original_result.get("summary", {})
    return {
        "test_cases": test_cases,
        "summary": {
            "total": len(test_cases),
            "by_type": by_type,
            "open_questions": list(original_summary.get("open_questions", [])),
        },
        "usage": dict(original_result.get("usage", {})),
    }
