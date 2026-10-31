"""
Checks the AI's rewrite of the test cases a tester selected and merges it into
the set: selected cases are replaced in place, new ones go after the last
selected case, and every other case is left exactly as it was.
"""
from core.review_utils import merge_test_cases


class RevisionError(ValueError):
    """The reply cannot be applied; the message says why, for the UI."""


def _test_id(case: dict) -> str:
    return str(case.get("test_id") or "").strip()


def revisable_ids(test_cases: list[dict]) -> list[str]:
    """The ids a tester can select: present, and used by one row only."""
    ids = [_test_id(case) for case in test_cases]
    return [test_id for test_id in ids if test_id and ids.count(test_id) == 1]


def apply_revision(test_cases: list[dict], selected_ids: list[str], revision: dict) -> dict:
    """
    Merge `revision` ({"revised": [...], "added": [...]}) into `test_cases`.

    Every selected case must come back once under its own id; anything else
    (a case left out, renamed, returned twice, or a case that was not selected)
    raises RevisionError and nothing changes. New cases keep their id unless
    another case uses it, then they get _2, _3... like merged gap cases.

    Returns {"test_cases", "revised_ids", "added_ids"}; the cases that were not
    selected are the same dicts as in `test_cases`. Inputs are not changed.
    """
    selected = [str(test_id).strip() for test_id in selected_ids]
    if not selected:
        raise RevisionError("Select at least one test case to revise.")
    table_ids = [_test_id(case) for case in test_cases]
    for test_id in selected:
        count = table_ids.count(test_id)
        if count == 0:
            raise RevisionError(f"{test_id} is no longer in the table.")
        if count > 1:
            raise RevisionError(f"{test_id} is used by {count} rows; give each row its own id.")

    replacements: dict[str, dict] = {}
    for case in revision.get("revised", []):
        test_id = _test_id(case)
        if test_id in replacements:
            raise RevisionError(
                f"The AI returned {test_id} more than once. Nothing was changed; try again."
            )
        replacements[test_id] = {**case, "test_id": test_id}
    missing = [test_id for test_id in selected if test_id not in replacements]
    extra = [test_id for test_id in replacements if test_id not in selected]
    if missing or extra:
        problems = []
        if missing:
            problems.append("left out " + ", ".join(missing))
        if extra:
            problems.append("returned cases that were not selected: " + ", ".join(extra))
        raise RevisionError(
            f"The AI {' and '.join(problems)}. Nothing was changed; try again, or put new "
            "cases in your note as additions."
        )

    # Ids of the whole set, so a new case never takes one; merge_test_cases renames clashes.
    with_added = merge_test_cases(test_cases, revision.get("added", []))
    added = with_added[len(test_cases):]
    last_selected = max(table_ids.index(test_id) for test_id in selected)

    merged = []
    for index, case in enumerate(test_cases):
        merged.append(replacements[table_ids[index]] if table_ids[index] in selected else case)
        if index == last_selected:
            merged.extend(added)
    return {
        "test_cases": merged,
        "revised_ids": [test_id for test_id in table_ids if test_id in selected],
        "added_ids": [case["test_id"] for case in added],
    }
