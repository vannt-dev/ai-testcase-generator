"""
Batch bug reports: turn the failed rows of an executed test run into bug
reports, one write_bug_report call per row.
"""
import unicodedata
from collections.abc import Callable

from core.bug_exporters import to_markdown
from core.result_utils import TEST_CASE_FIELDS

RUN_FIELDS = ("status", "actual_result", "comment")
REQUIRED_RUN_FIELDS = ("status", "actual_result")
MAX_BATCH_ROWS = 50
SEVERITIES = ("Critical", "Major", "Minor", "Trivial")
PRIORITIES = ("High", "Medium", "Low")
# "x" is left out on purpose: many teams mark executed or passed rows with it.
FAILED_STATUS_WORDS = {"fail", "failed", "failure", "ng", "ko dat", "khong dat"}
USAGE_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _normalize(value: str) -> str:
    # NFKD splits most accented letters into base + combining mark; đ/Đ have no decomposition.
    text = unicodedata.normalize("NFKD", value.replace("đ", "d").replace("Đ", "D"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _cell(row: dict, column: str) -> str:
    if not column:
        return ""
    value = row.get(column)
    return "" if value is None else str(value).strip()


def distinct_values(rows: list[dict], column: str) -> list[str]:
    values = []
    for row in rows:
        value = _cell(row, column)
        if value and value not in values:
            values.append(value)
    return values


def default_failed_values(values: list[str]) -> list[str]:
    selected = []
    for value in values:
        text = "" if value is None else str(value).strip()
        if text and text not in selected and _normalize(text) in FAILED_STATUS_WORDS:
            selected.append(text)
    return selected


def failed_rows(rows: list[dict], mapping: dict[str, str], failed_values: list[str]) -> list[dict]:
    wanted = {value.strip() for value in failed_values}
    selected = []
    for number, row in enumerate(rows, start=1):
        if _cell(row, mapping.get("status", "")) not in wanted:
            continue
        test_case = {}
        for field in TEST_CASE_FIELDS:
            value = _cell(row, mapping.get(field, ""))
            if value:
                test_case[field] = value
        selected.append(
            {
                "row_number": number,
                "test_case": test_case,
                "actual_result": _cell(row, mapping.get("actual_result", "")),
                "comment": _cell(row, mapping.get("comment", "")),
            }
        )
    return selected


def notes_for_row(row: dict) -> str:
    notes = f"Test case failed during a test run.\n\nActual result: {row['actual_result']}"
    if row["comment"]:
        notes += f"\n\nTester comment: {row['comment']}"
    return notes


def _sum_usage(usages: list[dict]) -> dict:
    total = {key: sum(int(usage.get(key, 0) or 0) for usage in usages) for key in USAGE_TOKEN_KEYS}
    costs = [usage.get("estimated_cost_usd") for usage in usages]
    # One unknown price makes the total unknown rather than silently too low.
    total["estimated_cost_usd"] = None if not usages or None in costs else sum(costs)
    total["model"] = usages[0].get("model", "N/A") if usages else "N/A"
    return total


def write_reports(
    client,
    system_prompt: str,
    rows: list[dict],
    source_name: str = "",
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    reports, errors, usages = [], [], []
    for index, row in enumerate(rows, start=1):
        try:
            result = client.write_bug_report(system_prompt, notes_for_row(row), row["test_case"] or None)
        except ValueError as error:
            errors.append(
                {"row": row["row_number"], "test_id": row["test_case"].get("test_id", ""), "error": str(error)}
            )
        else:
            report = result["report"]
            location = f"row {row['row_number']}"
            report["source"] = f"{source_name}, {location}" if source_name else location
            reports.append(report)
            usages.append(result["usage"])
        if on_progress:
            on_progress(index, len(rows))
    return {"reports": reports, "errors": errors, "usage": _sum_usage(usages)}


def apply_summary_edits(reports: list[dict], rows: list[dict]) -> list[dict]:
    """Apply title/severity/priority edits from the summary table; blank or invalid edits keep the original."""
    updated = []
    for report, row in zip(reports, rows):
        report = dict(report)
        title = str(row.get("title") or "").strip()
        if title:
            report["title"] = title
        if row.get("severity") in SEVERITIES:
            report["severity"] = row["severity"]
        if row.get("priority") in PRIORITIES:
            report["priority"] = row["priority"]
        updated.append(report)
    return updated


def combined_markdown(reports: list[dict]) -> str:
    return "\n---\n\n".join(to_markdown(report) for report in reports)
