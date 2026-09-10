"""Business logic for the Test Case Reviewer page: column mapping and merging."""
from core.result_utils import TEST_CASE_FIELDS


def apply_column_mapping(raw_rows: list[dict], mapping: dict[str, str]) -> list[dict]:
    """
    Re-key raw uploaded rows (arbitrary column names) into TEST_CASE_FIELDS
    using a confirmed {target_field: uploaded_column_name} mapping. A
    field mapped to "" (or missing from `mapping`) becomes an empty
    string in the output. Falsy-but-valid values (e.g. 0, False) are
    preserved as strings, not converted to empty strings.
    """
    normalized = []
    for row in raw_rows:
        normalized.append(
            {
                field: (
                    "" if row.get(mapping.get(field, "")) is None
                    else str(row.get(mapping.get(field, ""))).strip()
                )
                for field in TEST_CASE_FIELDS
            }
        )
    return normalized
