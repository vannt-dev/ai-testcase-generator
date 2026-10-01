"""
Clean the AI's API automation output before rendering: keep only requests
the renderer can express, make saved variables valid TypeScript identifiers
and turn anything else into a `todo` step with a warning. Never raises on
AI output.
"""
import json
import re

from core.automation_validate import TS_RESERVED, _text, _unique, ascii_fold

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")
BODYLESS_METHODS = ("GET", "HEAD")
CHECK_KINDS = {"json_equals", "json_contains", "json_exists", "json_absent", "text_contains"}

# A placeholder the renderer turns into an expression: ${ENV:NAME} (group 1) or ${VAR:name} (group 2).
PLACEHOLDER = re.compile(r"\$\{ENV:([A-Z][A-Z0-9_]*)\}|\$\{VAR:([A-Za-z_][A-Za-z0-9_]*)\}")
# Any ${VAR:...} the AI wrote, valid or not, so unknown ones can be reported.
_VAR_REFERENCE = re.compile(r"\$\{VAR:([^}]*)\}")
# A placeholder written outside a JSON string, e.g. {"id": ${VAR:orderId}}.
_BARE_PLACEHOLDER = re.compile(r'(?<!")\$\{(?:ENV|VAR):[^}]*\}(?!")')
_JSON_PATH = re.compile(r"^(?:[A-Za-z_][\w-]*|\[\d+\])(?:\.[A-Za-z_][\w-]*|\[\d+\])*$")
# Names the generated spec uses itself; responseN and bodyN are declared per step.
# arguments and eval are not reserved words, but strict mode refuses them as names.
_VAR_RESERVED = TS_RESERVED | {
    "request", "test", "expect", "process", "apiUrl", "at", "jsonBody", "arguments", "eval",
}
# With or without a number: _unique may append one, and "response2" is what step 2 declares.
_STEP_LOCAL = re.compile(r"^(response|body)\d*$")
# Deeper JSON than any real request body; beyond it Python and the renderer would hit recursion limits.
MAX_JSON_DEPTH = 50


def _todo(source: str) -> dict:
    return {
        "action": "todo", "method": "", "path": "", "headers": [], "query": [], "body": "",
        "expect_status": 0, "checks": [], "saves": [], "confident": False, "source": source,
    }


def _items(value) -> list[dict]:
    return [item for item in value or [] if isinstance(item, dict)]


def _scrub(value):
    """The same structure with every string encodable as UTF-8 (a lone surrogate cannot be written to the zip)."""
    if isinstance(value, str):
        return value.encode("utf-8", "replace").decode("utf-8")
    if isinstance(value, dict):
        return {key: _scrub(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


def _depth(value) -> int:
    depth, level = 0, [value]
    while level:
        depth += 1
        level = [
            child for item in level if isinstance(item, (dict, list))
            for child in (item.values() if isinstance(item, dict) else item)
        ]
    return depth


def _parse_json(text: str) -> tuple[object, str]:
    """The parsed value and "", or None and why the text cannot be used."""
    try:
        value = json.loads(text)
    except RecursionError:
        return None, "is nested too deeply"
    except ValueError:
        return None, "is not valid JSON"
    if _depth(value) > MAX_JSON_DEPTH:
        return None, "is nested too deeply"
    return value, ""


def _json_dump(value) -> str:
    """JSON text with unicode escapes decoded, so a placeholder hidden behind one is seen and checked."""
    return _scrub(json.dumps(value, ensure_ascii=False))


def _valid_path(path: str) -> bool:
    return path == "" or bool(_JSON_PATH.match(path))


def _var_name(raw: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", ascii_fold(raw))
    if not words:
        return "saved"
    name = words[0][0].lower() + words[0][1:] + "".join(word[0].upper() + word[1:] for word in words[1:])
    if name[0].isdigit():
        name = "v" + name
    if name in _VAR_RESERVED or _STEP_LOCAL.match(name):
        name += "Value"
    return name


def validate_api_automation(result: dict, modules: dict[str, str]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    tests: list[dict] = []
    used_ids: set[str] = set()
    returned_ids: set[str] = set()
    result = _scrub(result)
    for raw in _items(result.get("tests")):
        raw_id = _text(raw.get("test_id")).strip() or "TC"
        if raw_id not in modules and raw_id not in returned_ids:
            warnings.append(f"{raw_id} was not among the selected test cases.")
        returned_ids.add(raw_id)
        test_id, number = raw_id, 2
        while test_id in used_ids:
            test_id = f"{raw_id}_{number}"
            number += 1
        used_ids.add(test_id)
        if test_id != raw_id:
            warnings.append(f"Duplicate test id '{raw_id}' renamed to '{test_id}'.")
        saved: dict[str, str] = {}
        used_vars: set[str] = set()
        steps = [
            _clean_step(f"{test_id} step {index}", step, saved, used_vars, warnings)
            for index, step in enumerate(_items(raw.get("steps")), start=1)
        ]
        if not steps:
            warnings.append(f"{test_id}: no steps were returned; marked as fixme.")
            steps = [_todo("No automatable steps were returned for this test case.")]
        tests.append({
            "test_id": test_id,
            "title": _text(raw.get("title")).strip(),
            "module": _text(modules.get(raw_id, "")),
            "steps": steps,
        })
    for selected_id in modules:
        if selected_id and selected_id not in returned_ids:
            warnings.append(f"{selected_id} was selected but the AI returned no test for it.")
    questions = [_text(q) for q in result.get("open_questions") or [] if _text(q).strip()]
    return {"tests": tests, "open_questions": questions}, warnings


def _clean_step(prefix: str, raw: dict, saved: dict[str, str], used_vars: set[str], warnings: list[str]) -> dict:
    source = _text(raw.get("source"))
    action = _text(raw.get("action"))
    if action == "todo":
        return _todo(source)
    if action != "request":
        warnings.append(f"{prefix}: unknown action '{action}'.")
        return _todo(source or action)

    method = _text(raw.get("method")).strip().upper()
    path = _text(raw.get("path")).strip()
    label = source or f"{method} {path}".strip()
    if method not in METHODS:
        warnings.append(f"{prefix}: unknown method '{method}'.")
        return _todo(label)
    # A variable's raw name may hold spaces ("${VAR:order id}"); it is renamed below.
    if not path.startswith("/") or re.search(r"\s", _VAR_REFERENCE.sub("", path)):
        warnings.append(f"{prefix}: path '{path}' must start with '/' and hold no spaces.")
        return _todo(label)
    parameter = re.search(r"\{[^{}]*\}", PLACEHOLDER.sub("", _VAR_REFERENCE.sub("", path)))
    if parameter:
        # "/orders/{id}" would be requested literally; the id has to come from test data or a saved value.
        warnings.append(f"{prefix}: path '{path}' still holds the parameter '{parameter.group(0)}'.")
        return _todo(label)

    body, problem = _clean_body(_text(raw.get("body")).strip())
    if problem:
        warnings.append(f"{prefix}: body {problem}.")
        return _todo(label)
    if body and method in BODYLESS_METHODS:
        warnings.append(f"{prefix}: a {method} request cannot send a body; it was dropped.")
        body = ""

    step = {
        "action": "request",
        "method": method,
        "path": path,
        "headers": _clean_pairs(prefix, "header", raw.get("headers"), warnings, fold=True),
        "query": _clean_pairs(prefix, "query parameter", raw.get("query"), warnings, fold=False),
        "body": body,
        "expect_status": _clean_status(prefix, raw.get("expect_status"), warnings),
        "checks": _clean_checks(prefix, raw.get("checks"), warnings),
        "saves": [],
        "confident": bool(raw.get("confident")),
        "source": source,
    }
    unknown = _rewrite_variables(step, saved)
    if unknown:
        warnings.append(f"{prefix}: unknown variable '{unknown[0]}'.")
        return _todo(label)
    # Saved after the references are resolved: a step cannot use what it saves itself.
    step["saves"] = _clean_saves(prefix, raw.get("saves"), saved, used_vars, warnings)
    if not step["expect_status"] and not step["checks"]:
        warnings.append(f"{prefix}: the request asserts nothing.")
    return step


def _clean_body(body: str) -> tuple[str, str]:
    """The body as normalised JSON text ("" for none) and "", or "" and why it cannot be used."""
    if not body:
        return "", ""
    problem = ""
    for candidate in (body, _BARE_PLACEHOLDER.sub(lambda m: json.dumps(m.group(0)), body)):
        value, problem = _parse_json(candidate)
        if not problem:
            return _json_dump(value), ""
        if problem != "is not valid JSON":
            break
    return "", problem


def _clean_status(prefix: str, raw, warnings: list[str]) -> int:
    try:
        status = int(raw or 0)
    except (TypeError, ValueError):
        status = -1
    if status and not 100 <= status <= 599:
        warnings.append(f"{prefix}: status {_text(raw)} is not an HTTP status; it is not asserted.")
        return 0
    return status


def _clean_pairs(prefix: str, kind: str, raw, warnings: list[str], fold: bool) -> list[dict]:
    """Named pairs with unique names; header names compare case-insensitively."""
    pairs: list[dict] = []
    seen: set[str] = set()
    for item in _items(raw):
        name = _text(item.get("name")).strip()
        if not name:
            warnings.append(f"{prefix}: {kind} without a name dropped.")
            continue
        key = name.casefold() if fold else name
        if key in seen:
            warnings.append(f"{prefix}: duplicate {kind} '{name}' dropped; the first is kept.")
            continue
        seen.add(key)
        pairs.append({"name": name, "value": _text(item.get("value"))})
    return pairs


def _clean_checks(prefix: str, raw, warnings: list[str]) -> list[dict]:
    checks: list[dict] = []
    for item in _items(raw):
        kind = _text(item.get("kind"))
        path = _text(item.get("path")).strip()
        value = _text(item.get("value"))
        if kind not in CHECK_KINDS:
            warnings.append(f"{prefix}: unknown check '{kind}' dropped.")
            continue
        if kind == "text_contains":
            path = ""
        elif not _valid_path(path):
            warnings.append(f"{prefix}: invalid JSON path '{path}'; the check was dropped.")
            continue
        if kind == "json_equals":
            value = _json_text(prefix, value, warnings)
            if value is None:
                continue
        elif kind in ("json_exists", "json_absent"):
            value = ""
        checks.append({"kind": kind, "path": path, "value": value})
    return checks


def _json_text(prefix: str, value: str, warnings: list[str]) -> str | None:
    """The expected value of json_equals as normalised JSON text; None when the check must be dropped."""
    parsed, problem = _parse_json(value)
    if not problem:
        return _json_dump(parsed)
    if problem != "is not valid JSON":
        warnings.append(f"{prefix}: expected value {problem}; the check was dropped.")
        return None
    # A lone placeholder is a value, not a mistake: quote it so it reads as a JSON string.
    alone = value.strip()
    if PLACEHOLDER.fullmatch(alone) or _VAR_REFERENCE.fullmatch(alone):
        return _json_dump(alone)
    warnings.append(f"{prefix}: expected value {value!r} is not JSON; it is compared as text.")
    return _json_dump(value)


def _clean_saves(prefix: str, raw, saved: dict[str, str], used_vars: set[str], warnings: list[str]) -> list[dict]:
    saves: list[dict] = []
    for item in _items(raw):
        raw_var = _text(item.get("var")).strip()
        path = _text(item.get("path")).strip()
        if not _valid_path(path):
            warnings.append(f"{prefix}: invalid JSON path '{path}'; '{raw_var}' is not saved.")
            continue
        var = _unique(_var_name(raw_var), used_vars)
        saves.append({"var": var, "path": path})
        saved[raw_var] = var
        saved.setdefault(var, var)
    return saves


def _rewrite_variables(step: dict, saved: dict[str, str]) -> list[str]:
    """Point every ${VAR:...} at its cleaned name (in place); returns the names nothing saved."""
    unknown: list[str] = []

    def rewrite(text: str) -> str:
        def replace(match: re.Match) -> str:
            name = match.group(1).strip()
            if name not in saved:
                unknown.append(name)
                return match.group(0)
            return "${VAR:" + saved[name] + "}"

        return _VAR_REFERENCE.sub(replace, text)

    step["path"] = rewrite(step["path"])
    step["body"] = rewrite(step["body"])
    for pair in step["headers"] + step["query"]:
        pair["value"] = rewrite(pair["value"])
    for check in step["checks"]:
        check["value"] = rewrite(check["value"])
    return unknown
