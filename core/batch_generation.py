"""
Generates test cases for a requirement file one section at a time and merges
the per-section results into one suite: unique test ids, criterion ids kept
apart between sections, open questions labelled with their section, and the
token usage added up. A section that fails leaves the others intact.
"""
import copy

from core.requirement_import import Section
from core.result_utils import build_edited_result, parse_covers
from core.review_utils import merge_test_cases

# Sections generated per run; each one is an AI call.
MAX_SECTIONS_PER_RUN = 50

_USAGE_COUNTS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "total_input_tokens",
)


def section_request(section: Section, number: int, total: int, source_name: str) -> str:
    """The requirement text sent for one section, saying where it comes from."""
    return (
        f'Section {number} of {total} of the requirement file "{source_name}": {section.title}\n'
        "Write test cases for this section only; the other sections are covered separately.\n\n"
        f"{section.text}"
    )


def generate_section(client, system_prompt: str, section: Section, number: int, total: int,
                     source_name: str) -> tuple[dict | None, str | None]:
    """
    One AI call for one section. Returns (result, None) or (None, error message);
    never raises, so a batch keeps the sections already done.
    """
    try:
        result = client.generate_test_cases(
            system_prompt, section_request(section, number, total, source_name)
        )
    except ValueError as error:
        return None, str(error)
    except Exception as error:  # an unexpected failure must not lose the finished sections
        return None, f"Unexpected error: {error}"
    return result, None


def merge_section_results(sections: list[Section], results: dict[str, dict]) -> dict:
    """
    One result from the per-section results (`results` is keyed by section
    key; sections without a result are skipped), in document order.

    Each section's model numbers its own criteria, so an id that two sections
    list (AC-1 in both) is prefixed with the section key in each ("S1.AC-1",
    "US-12.AC-1"), along with the `covers` entries that cite it. Ids that are
    unique in the file stay as written. Test ids that collide get _2, _3...
    """
    done = [(section, results[section.key]) for section in sections if section.key in results]

    listed_in: dict[str, int] = {}
    for _, result in done:
        for criterion_id in {_criterion_id(c) for c in result.get("acceptance_criteria", [])} - {""}:
            listed_in[criterion_id] = listed_in.get(criterion_id, 0) + 1
    shared = {criterion_id for criterion_id, count in listed_in.items() if count > 1}

    criteria: list[dict] = []
    test_cases: list[dict] = []
    open_questions: list[str] = []
    usages: list[dict] = []
    for section, result in done:
        own = {_criterion_id(c) for c in result.get("acceptance_criteria", [])}
        rename = {criterion_id: f"{section.key}.{criterion_id}" for criterion_id in own & shared}
        for criterion in result.get("acceptance_criteria", []):
            criterion_id = _criterion_id(criterion)
            if criterion_id:
                criteria.append({"id": rename.get(criterion_id, criterion_id),
                                 "text": str(criterion.get("text") or "")})
        section_cases = []
        for test_case in result.get("test_cases", []):
            test_case = copy.deepcopy(test_case)
            test_case["covers"] = [rename.get(c, c) for c in parse_covers(test_case.get("covers"))]
            section_cases.append(test_case)
        test_cases = merge_test_cases(test_cases, section_cases)
        open_questions.extend(
            f"[{section.title}] {question}"
            for question in result.get("summary", {}).get("open_questions", [])
        )
        if result.get("usage"):
            usages.append(result["usage"])

    return build_edited_result(
        {
            "acceptance_criteria": criteria,
            "summary": {"open_questions": open_questions},
            "usage": _add_usage(usages),
        },
        test_cases,
    )


def _criterion_id(criterion: dict) -> str:
    return " ".join(str(criterion.get("id") or "").split())


def _add_usage(usages: list[dict]) -> dict:
    """The token counts added up; the cost only when every call had one."""
    if not usages:
        return {}
    total = {
        "provider": usages[0].get("provider", "anthropic"),
        "model": usages[0].get("model", ""),
        **{name: sum(int(usage.get(name, 0) or 0) for usage in usages) for name in _USAGE_COUNTS},
    }
    costs = [usage.get("estimated_cost_usd") for usage in usages]
    total["estimated_cost_usd"] = None if any(cost is None for cost in costs) else sum(costs)
    return total
