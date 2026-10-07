"""
Exports a test case set (the dict returned by the AI) to a Gherkin
``.feature`` file, for teams that keep their cases in Cucumber, Behave,
SpecFlow or pytest-bdd.

The mapping is mechanical, with no AI call: the precondition becomes the
``Given`` steps, the numbered test steps the ``When`` steps and the expected
result the ``Then`` steps. The wording is the tester's own, so the scenarios
read as written and still need step definitions behind them.
"""
import re

# "1. Enter the phone number", "2) Tap Login", "- Tap Login", "* Tap Login"
_STEP_MARKER = re.compile(r"^\s*(?:\d+\s*[.)]|[-*•])\s+")
_TAG_UNSAFE = re.compile(r"[^\w.-]+", re.UNICODE)
_KEYWORD = re.compile(r"^(?:Given|When|Then|And|But)\b\s*", re.IGNORECASE)


def _one_line(text) -> str:
    """Gherkin steps, names and comments are single lines."""
    return " ".join(str(text or "").split())


def _lines(text) -> list[str]:
    """The non-empty lines of a cell, without list markers."""
    result = []
    for raw in str(text or "").splitlines():
        line = _one_line(_STEP_MARKER.sub("", raw))
        if line:
            result.append(line)
    return result


def _step_text(line: str) -> str:
    """
    A line that already starts with a Gherkin keyword keeps only its text, so
    "Given the user is logged in" does not become "Given Given the user...".
    """
    stripped = _KEYWORD.sub("", line, count=1)
    return stripped or line


def _tag(value) -> str:
    """A tag is one token: no spaces, and no "@" of its own."""
    cleaned = _TAG_UNSAFE.sub("_", _one_line(value)).strip("_")
    return f"@{cleaned}" if cleaned else ""


def _steps(keyword: str, lines: list[str]) -> list[str]:
    """The first line takes the keyword, the rest continue it with And."""
    return [
        f"    {keyword if index == 0 else 'And'} {_step_text(line)}"
        for index, line in enumerate(lines)
    ]


def _scenario(test_case: dict, number: int) -> list[str]:
    title = _one_line(test_case.get("title")) or f"Test case {number}"
    tags = [
        _tag(test_case.get(key))
        for key in ("test_id", "module", "priority", "type", "platform")
    ]
    tags = [tag for tag in dict.fromkeys(tags) if tag]

    block = []
    if tags:
        block.append(f"  {' '.join(tags)}")
    block.append(f"  Scenario: {title}")
    for line in _lines(test_case.get("test_data")):
        block.append(f"    # Test data: {line}")

    given = _lines(test_case.get("precondition"))
    when = _lines(test_case.get("steps"))
    then = _lines(test_case.get("expected_result"))
    block.extend(_steps("Given", given))
    block.extend(_steps("When", when))
    block.extend(_steps("Then", then))
    if not (given or when or then):
        block.append("    # This test case has no precondition, steps or expected result.")
    return block


def export_to_gherkin(result: dict, feature_name: str = "Test cases") -> str:
    """
    Takes a dict {"test_cases": [...], "summary": {...}} and returns the text
    of one ``.feature`` file: a single Feature with a Scenario per test case.

    Each scenario is tagged with its test id, module, priority, type and
    platform, so a runner can select by any of them (``--tags @High``).
    """
    name = _one_line(feature_name) or "Test cases"
    test_cases = result.get("test_cases", [])
    lines = ["# language: en", f"Feature: {name}"]

    open_questions = result.get("summary", {}).get("open_questions", [])
    if open_questions:
        lines.append("")
        lines.append("  # Open questions to confirm with BA/Dev:")
        for question in open_questions:
            text = _one_line(question)
            if text:
                lines.append(f"  # - {text}")

    for number, test_case in enumerate(test_cases, start=1):
        lines.append("")
        lines.extend(_scenario(test_case, number))

    return "\n".join(lines) + "\n"
