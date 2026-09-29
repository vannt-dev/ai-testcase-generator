"""
Find the locators in a Playwright page object file and patch only the ones
the AI fixed. Everything else in the file is kept byte for byte, so files a
tester edited by hand survive healing.
"""
import difflib
import json
import re

from core.automation_validate import normalize_strategy
from core.playwright_renderer import comment, locator_expr

MAX_FILE_BYTES = 100_000
MAX_ERROR_CHARS = 20_000
MAX_SNAPSHOT_CHARS = 50_000

# `this.<key> = page` at the start of a line; the expression is scanned by hand
# so a ';' or '//' inside a string literal does not end it.
# `page` must be followed by a dot, or end the line (a call continued below), so
# `this.page = page;` in a hand-written constructor is not taken for a locator.
_ASSIGNMENT = re.compile(r"^\s*this\.([A-Za-z_$][\w$]*)\s*=\s*(?=page\s*(?:\.|$))")
_CALL = re.compile(r"^page\s*\.\s*(\w+)\s*\(")


class HealingInputError(ValueError):
    """A problem with the uploaded file, shown to the user as is."""


def _split(source: str) -> tuple[list[str], list[str]]:
    """Lines and the terminator after each ("\\r\\n", "\\n"; none after the last),
    so a file with mixed line endings is rebuilt exactly. Not str.splitlines():
    it also splits on U+2028 and friends inside string literals."""
    parts = re.split(r"(\r?\n)", source)
    return parts[0::2], parts[1::2]


def _split_lines(source: str) -> list[str]:
    return _split(source)[0]


def _join(lines: list[str], terminators: list[str]) -> str:
    return "".join(line + end for line, end in zip(lines, terminators + [""]))


def _block_comment_after(line: str, in_block: bool) -> bool:
    """Whether a /* */ comment is still open at the end of the line."""
    quote = None
    index = 0
    while index < len(line):
        pair = line[index:index + 2]
        if in_block:
            if pair == "*/":
                in_block = False
                index += 2
                continue
        elif quote:
            if line[index] == "\\":
                index += 2
                continue
            if line[index] == quote:
                quote = None
        elif pair == "//":
            break
        elif pair == "/*":
            in_block = True
            index += 2
            continue
        elif line[index] in "'\"`":
            quote = line[index]
        index += 1
    return in_block


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
    in_block = False
    for index, line in enumerate(_split_lines(source)):
        starts_in_block = in_block
        in_block = _block_comment_after(line, in_block)
        match = None if starts_in_block else _ASSIGNMENT.match(line)
        if not match:
            continue
        key, start = match.group(1), match.end()
        end = _statement_end(line, start)
        expression = line[start:end].rstrip() if end is not None else ""
        # A '/' outside strings is a regex literal the scanner cannot follow.
        if end is None or key in seen or "/" in _code_only(expression):
            skipped.append(index)
            continue
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


# Comment lines this app writes above a locator; any other comment is the tester's and stays.
GENERATED_NOTES = (
    "// TODO verify locator: not confirmed by an HTML/ARIA snapshot",
    "// TODO verify locator: not confirmed by the new snapshot",
)
HEALED_NOTE = "// healed:"
_SIMPLE_SINGLE_QUOTED = re.compile(r"'([^'\"\\]*)'")


def _is_generated_note(line: str) -> bool:
    text = line.strip()
    return text in GENERATED_NOTES or text.startswith(HEALED_NOTE)


def _same_quotes(expression: str) -> str:
    """'Email' and "Email" render the same locator; compare them as equal."""
    return _SIMPLE_SINGLE_QUOTED.sub(lambda m: json.dumps(m.group(1), ensure_ascii=False), expression)


def _code_only(text: str) -> str:
    """The text with string literal contents blanked, so brackets and colons
    inside strings are not mistaken for code. Same length as the input."""
    out: list[str] = []
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if char == "\\":
                out.append(" " * len(text[index:index + 2]))
                index += 2
                continue
            out.append(char if char == quote else " ")
            if char == quote:
                quote = None
        else:
            if char in "'\"`":
                quote = char
            out.append(char)
        index += 1
    return "".join(out)


def _drops_detail(expression: str) -> bool:
    """True when replacing the expression with one getBy/locator call would lose
    something: a chain (.nth(), .first(), .filter()) or options other than a
    role's accessible name."""
    code = _code_only(expression)
    call = _CALL.match(code)
    if not call:
        return True
    depth = 0
    for close in range(call.end() - 1, len(code)):
        if code[close] == "(":
            depth += 1
        elif code[close] == ")":
            depth -= 1
            if depth == 0:
                break
    else:
        return True
    if code[close + 1:].strip():
        return True
    keys = set(re.findall(r"([A-Za-z_$][\w$]*)\s*:", code[call.end():close]))
    return bool(keys) and (call.group(1) != "getByRole" or keys != {"name"})


def validate_fixes(fixes: list[dict], locators: list[dict]) -> tuple[list[dict], list[str]]:
    current = {loc["key"]: loc["expression"] for loc in locators}
    kept: list[dict] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for raw in fixes:
        key = str(raw.get("key") or "").strip()
        if key not in current:
            warnings.append(f"The AI proposed a fix for '{key}', which is not a locator in this file.")
            continue
        if key in seen:
            warnings.append(f"Second fix for '{key}' ignored; the first is kept.")
            continue
        seen.add(key)
        fix = {
            "key": key,
            "strategy": str(raw.get("strategy") or ""),
            "role": str(raw.get("role") or "").strip().lower(),
            "value": str(raw.get("value") or ""),
            "confident": bool(raw.get("confident")),
            "reason": comment(raw.get("reason") or ""),
        }
        normalize_strategy(fix, key, warnings)
        fix["expression"] = locator_expr(fix)
        if fix["expression"] == _same_quotes(current[key]):
            warnings.append(f"{key}: the proposed locator is the same as the current one.")
            continue
        fix["drops_detail"] = _drops_detail(current[key])
        if fix["drops_detail"]:
            warnings.append(
                f"{key}: the current locator has chained calls or options ({current[key]}) that the fix "
                "would drop; it is unticked, so check it before applying."
            )
        kept.append(fix)
    return kept, warnings


def apply_fixes(source: str, locators: list[dict], fixes: list[dict]) -> str:
    if not fixes:
        return source
    by_key = {loc["key"]: loc for loc in locators}
    lines, terminators = _split(source)
    # Bottom-up, so inserting comment lines never shifts a line still to patch.
    for fix in sorted(fixes, key=lambda f: by_key[f["key"]]["line"], reverse=True):
        loc = by_key[fix["key"]]
        index = loc["line"]
        line = lines[index]
        indent = line[: len(line) - len(line.lstrip())]
        lines[index] = line[: loc["start"]] + fix["expression"] + line[loc["end"]:]
        notes = [f"{indent}{HEALED_NOTE} {fix['reason'] or 'locator updated'}"]
        if not fix["confident"]:
            notes.append(f"{indent}{GENERATED_NOTES[1]}")
        # Notes this app wrote earlier describe the old locator, so they are replaced.
        replace_from = index
        while replace_from > 0 and _is_generated_note(lines[replace_from - 1]):
            replace_from -= 1
        # A note ends like the line it describes; the last line may have no terminator.
        if index < len(terminators):
            note_end = terminators[index]
        else:
            note_end = terminators[index - 1] if index > 0 else "\n"
        lines[replace_from:index] = notes
        terminators[replace_from:index] = [note_end] * len(notes)
    return _join(lines, terminators)


def unified_diff(old: str, new: str, file_name: str) -> str:
    return "\n".join(difflib.unified_diff(
        _split_lines(old), _split_lines(new), f"a/{file_name}", f"b/{file_name}", lineterm="",
    ))
