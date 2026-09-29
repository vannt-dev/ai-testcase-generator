"""
Find the locators in a Playwright page object file and patch only the ones
the AI fixed. Everything else in the file is kept byte for byte, so files a
tester edited by hand survive healing.
"""
import re

MAX_FILE_BYTES = 100_000
MAX_ERROR_CHARS = 20_000
MAX_SNAPSHOT_CHARS = 50_000

# `this.<key> = page` at the start of a line; the expression is scanned by hand
# so a ';' or '//' inside a string literal does not end it.
_ASSIGNMENT = re.compile(r"^\s*this\.([A-Za-z_$][\w$]*)\s*=\s*(?=page\b)")


class HealingInputError(ValueError):
    """A problem with the uploaded file, shown to the user as is."""


def _newline(source: str) -> str:
    return "\r\n" if "\r\n" in source else "\n"


def _split_lines(source: str) -> list[str]:
    # Not str.splitlines(): it also splits on U+2028 and friends inside strings.
    return source.split(_newline(source))


def read_page_object(data: bytes) -> str:
    if len(data) > MAX_FILE_BYTES:
        raise HealingInputError(f"The file is larger than {MAX_FILE_BYTES:,} bytes.")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise HealingInputError("The file is not UTF-8 text.") from error


def _statement_end(line: str, start: int) -> int | None:
    """Index of the ';' that ends the statement, or None when the statement
    does not end on this line or code other than a comment follows it."""
    quote = None
    index = start
    while index < len(line):
        char = line[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == ";":
            rest = line[index + 1:].strip()
            return index if not rest or rest.startswith("//") else None
        index += 1
    return None


def parse_locators(source: str) -> tuple[list[dict], list[int]]:
    locators: list[dict] = []
    skipped: list[int] = []
    seen: set[str] = set()
    for index, line in enumerate(_split_lines(source)):
        match = _ASSIGNMENT.match(line)
        if not match:
            continue
        key, start = match.group(1), match.end()
        end = _statement_end(line, start)
        if end is None or key in seen:
            skipped.append(index)
            continue
        expression = line[start:end].rstrip()
        seen.add(key)
        locators.append({
            "key": key, "expression": expression, "line": index,
            "start": start, "end": start + len(expression),
        })
    return locators, skipped


def healing_problems(locators: list[dict] | None, error_text: str, snapshot: str) -> list[str]:
    problems = []
    if locators is None:
        problems.append("Upload a page object file (.ts).")
    elif not locators:
        problems.append("The file has no one-line `this.<name> = page.…;` locators. Is it a page object?")
    if not error_text.strip():
        problems.append("Paste the Playwright error.")
    elif len(error_text) > MAX_ERROR_CHARS:
        problems.append(
            f"The error is longer than {MAX_ERROR_CHARS:,} characters; paste only the failing test's output."
        )
    if not snapshot.strip():
        problems.append("Paste the page's current HTML or ARIA snapshot.")
    elif len(snapshot) > MAX_SNAPSHOT_CHARS:
        problems.append(
            f"The snapshot is longer than {MAX_SNAPSHOT_CHARS:,} characters; "
            "paste only the relevant part of the page."
        )
    return problems
