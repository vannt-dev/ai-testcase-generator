"""
Traceability between a requirement's acceptance criteria and the test cases
that verify them: which test cases cover each criterion, and which criteria
have none. Built from the generation result alone, with no AI call.
"""
from core.result_utils import parse_covers


def has_traceability(result: dict) -> bool:
    """True when the result lists criteria or any test case names one it covers."""
    return bool(result.get("acceptance_criteria")) or any(
        parse_covers(test_case.get("covers")) for test_case in result.get("test_cases", [])
    )


def build_traceability(result: dict) -> dict:
    """
    Returns {"criteria": [...], "unlinked_test_ids": [...]}.

    Each criterion row is {"id", "text", "test_ids", "listed"}, in the order the
    criteria were listed; an id a test case cites that is not in the list
    follows with "listed": False and no text, so a typo in the editor shows up
    instead of disappearing. `unlinked_test_ids` are test cases that cite no
    criterion.
    """
    rows: list[dict] = []
    by_id: dict[str, dict] = {}
    for criterion in result.get("acceptance_criteria") or []:
        criterion_id = " ".join(str(criterion.get("id") or "").split())
        if not criterion_id or criterion_id in by_id:
            continue
        row = {
            "id": criterion_id,
            "text": str(criterion.get("text") or "").strip(),
            "test_ids": [],
            "listed": True,
        }
        by_id[criterion_id] = row
        rows.append(row)

    unlinked = []
    for number, test_case in enumerate(result.get("test_cases", []), start=1):
        test_id = str(test_case.get("test_id") or "").strip() or f"(row {number})"
        cited = parse_covers(test_case.get("covers"))
        if not cited:
            unlinked.append(test_id)
        for criterion_id in cited:
            row = by_id.get(criterion_id)
            if row is None:
                row = {"id": criterion_id, "text": "", "test_ids": [], "listed": False}
                by_id[criterion_id] = row
                rows.append(row)
            if test_id not in row["test_ids"]:
                row["test_ids"].append(test_id)

    return {"criteria": rows, "unlinked_test_ids": unlinked}


def uncovered_criteria(result: dict) -> list[str]:
    """The ids of the listed criteria that no test case covers."""
    return [row["id"] for row in build_traceability(result)["criteria"] if not row["test_ids"]]
