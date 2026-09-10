"""Business logic for the Test Case Reviewer page: column mapping and merging."""
from core.result_utils import TEST_CASE_FIELDS

# Leading characters Excel/Sheets interpret as the start of a formula.
# Uploaded files are untrusted input, so a value beginning with one of
# these is quote-prefixed to force it to be treated as literal text.
FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_formula_prefix(value: str) -> str:
    """Quote-prefix a value that Excel would otherwise evaluate as a formula."""
    if value and value[0] in FORMULA_TRIGGER_CHARS:
        return "'" + value
    return value


def apply_column_mapping(raw_rows: list[dict], mapping: dict[str, str]) -> list[dict]:
    """
    Re-key raw uploaded rows (arbitrary column names) into TEST_CASE_FIELDS
    using a confirmed {target_field: uploaded_column_name} mapping. A
    field mapped to "" (or missing from `mapping`) becomes an empty
    string in the output. Falsy-but-valid values (e.g. 0, False) are
    preserved as strings, not converted to empty strings. Values that
    would be read as Excel formulas are quote-prefixed (CSV/formula
    injection guard) since the source file is untrusted.
    """
    normalized = []
    for row in raw_rows:
        normalized.append(
            {
                field: _sanitize_formula_prefix(
                    "" if row.get(mapping.get(field, "")) is None
                    else str(row.get(mapping.get(field, ""))).strip()
                )
                for field in TEST_CASE_FIELDS
            }
        )
    return normalized


def merge_test_cases(existing: list[dict], new: list[dict]) -> list[dict]:
    """
    Append `new` test cases to `existing`, renaming any `test_id` that
    collides with an existing (or already-renamed) id by appending
    _2, _3, etc. Does not mutate either input list/dicts.
    """
    used_ids = {tc.get("test_id") for tc in existing}
    merged = list(existing)
    for test_case in new:
        test_case = dict(test_case)
        base_id = test_case.get("test_id", "")
        candidate = base_id
        suffix = 2
        while candidate in used_ids:
            candidate = f"{base_id}_{suffix}"
            suffix += 1
        test_case["test_id"] = candidate
        used_ids.add(candidate)
        merged.append(test_case)
    return merged
