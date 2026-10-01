"""
Render a validated API automation result (core.api_automation_validate) as
Playwright API tests. Pure functions: no Streamlit, no AI. Every string that
reaches TypeScript goes through ts_string() and every comment through
comment(); the only expressions made from the result are placeholders the
validator accepted.
"""
import json

from core.api_automation_validate import PLACEHOLDER
from core.automation_validate import WINDOWS_RESERVED
from core.playwright_renderer import comment, slug, ts_string

# Playwright's request fixture has no method of its own for these.
_FETCH_ONLY = ("HEAD", "OPTIONS")


def text_expr(text: str) -> str:
    """A TypeScript string expression for text that may hold placeholders."""
    parts: list[str] = []
    position = 0
    for match in PLACEHOLDER.finditer(text):
        if match.start() > position:
            parts.append(ts_string(text[position:match.start()]))
        parts.append(f"(process.env.{match.group(1)} ?? '')" if match.group(1) else f"String({match.group(2)})")
        position = match.end()
    if position < len(text) or not parts:
        parts.append(ts_string(text[position:]))
    return " + ".join(parts)


def _value_expr(text: str) -> str:
    """Like text_expr, but a string that is exactly one saved variable keeps the variable's type."""
    match = PLACEHOLDER.fullmatch(text)
    if match and match.group(2):
        return match.group(2)
    if match:
        return f"process.env.{match.group(1)} ?? ''"
    return text_expr(text)


def _ts_value(value) -> str:
    """A parsed JSON value as a TypeScript literal, with placeholders inside strings resolved."""
    if isinstance(value, str):
        return _value_expr(value)
    if isinstance(value, dict):
        if not value:
            return "{}"
        return "{ " + ", ".join(f"{ts_string(key)}: {_ts_value(item)}" for key, item in value.items()) + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_ts_value(item) for item in value) + "]"
    return json.dumps(value)


def _pairs_expr(pairs: list[dict]) -> str:
    return "{ " + ", ".join(f"{ts_string(pair['name'])}: {text_expr(pair['value'])}" for pair in pairs) + " }"


def _render_request(step: dict, number: int) -> list[str]:
    lines: list[str] = []
    note = comment(step["source"])
    if note:
        lines.append(f"// {note}")
    if not step["confident"]:
        lines.append("// TODO verify this request: the endpoint was not in the API description")

    method = step["method"]
    options: list[str] = []
    if method in _FETCH_ONLY:
        options.append(f"method: {ts_string(method)},")
    if step["headers"]:
        options.append(f"headers: {_pairs_expr(step['headers'])},")
    if step["query"]:
        options.append(f"params: {_pairs_expr(step['query'])},")
    if step["body"]:
        options.append(f"data: {_ts_value(json.loads(step['body']))},")

    call = "fetch" if method in _FETCH_ONLY else method.lower()
    response, body = f"response{number}", f"body{number}"
    url = f"apiUrl({text_expr(step['path'])})"
    if options:
        lines.append(f"const {response} = await request.{call}({url}, {{")
        lines += [f"  {option}" for option in options]
        lines.append("});")
    else:
        lines.append(f"const {response} = await request.{call}({url});")

    if step["expect_status"]:
        lines.append(f"expect({response}.status()).toBe({step['expect_status']});")
    if step["saves"] or any(check["kind"] != "text_contains" for check in step["checks"]):
        lines.append(f"const {body} = await {response}.json();")
    for check in step["checks"]:
        target = f"at({body}, {ts_string(check['path'])})"
        kind = check["kind"]
        if kind == "json_equals":
            lines.append(f"expect({target}).toEqual({_ts_value(json.loads(check['value']))});")
        elif kind == "json_contains":
            lines.append(f"expect(String({target})).toContain({text_expr(check['value'])});")
        elif kind == "json_exists":
            lines.append(f"expect({target}).toBeDefined();")
        elif kind == "json_absent":
            lines.append(f"expect({target}).toBeUndefined();")
        else:
            lines.append(f"expect(await {response}.text()).toContain({text_expr(check['value'])});")
    for save in step["saves"]:
        lines.append(f"const {save['var']} = at({body}, {ts_string(save['path'])});")
    return lines


def _render_test(test: dict) -> str:
    fixme = any(step["action"] == "todo" for step in test["steps"])
    title = ts_string(f"{test['test_id']} {test['title']}".strip())
    lines = [f"{'test.fixme' if fixme else 'test'}({title}, async ({{ request }}) => {{"]
    for number, step in enumerate(test["steps"], start=1):
        if step["action"] == "todo":
            lines.append(f"  // TODO: {comment(step['source'])}")
        else:
            lines += [f"  {line}" for line in _render_request(step, number)]
    lines.append("});")
    return "\n".join(lines)


def render_api_spec(tests: list[dict]) -> str:
    imports = "import { test, expect } from '@playwright/test';\nimport { apiUrl, at } from './support';\n"
    return imports + "\n" + "\n\n".join(_render_test(test) for test in tests) + "\n"


def _support(api_base_url: str) -> str:
    return (
        "// Helpers for the generated API tests.\n"
        f"const API_BASE_URL = (process.env.API_BASE_URL ?? {ts_string(api_base_url)}).replace(/\\/+$/, '');\n"
        "\n"
        "export function apiUrl(path: string): string {\n"
        "  return API_BASE_URL + path;\n"
        "}\n"
        "\n"
        "// Reads a path such as \"data.items[0].id\" from a parsed JSON body; undefined when it is missing.\n"
        "// eslint-disable-next-line @typescript-eslint/no-explicit-any\n"
        "export function at(body: unknown, path: string): any {\n"
        "  // eslint-disable-next-line @typescript-eslint/no-explicit-any\n"
        "  let current: any = body;\n"
        "  for (const key of path.match(/[^.[\\]]+/g) ?? []) {\n"
        "    if (current === null || current === undefined) return undefined;\n"
        "    current = current[key];\n"
        "  }\n"
        "  return current;\n"
        "}\n"
    )


def render_api_files(result: dict, api_base_url: str) -> dict[str, str]:
    files = {"tests/api/support.ts": _support(api_base_url)}
    groups: dict[str, list[dict]] = {}
    for test in result["tests"]:
        module = slug(test.get("module", "")) or "general"
        if module in WINDOWS_RESERVED:
            module += "-tests"
        groups.setdefault(module, []).append(test)
    for module, tests in sorted(groups.items()):
        files[f"tests/api/{module}.api.spec.ts"] = render_api_spec(tests)
    return files


def _texts(step: dict) -> list[str]:
    return (
        [step["path"], step["body"]]
        + [pair["value"] for pair in step["headers"] + step["query"]]
        + [check["value"] for check in step["checks"]]
    )


def api_env_names(result: dict) -> list[str]:
    names = set()
    for test in result["tests"]:
        for step in test["steps"]:
            for text in _texts(step):
                names.update(match.group(1) for match in PLACEHOLDER.finditer(text) if match.group(1))
    return sorted(names)


def summarize_api(result: dict) -> dict:
    return {
        "tests": len(result["tests"]),
        "fixme": sum(1 for test in result["tests"] if any(step["action"] == "todo" for step in test["steps"])),
        "unverified_requests": sum(
            1 for test in result["tests"] for step in test["steps"]
            if step["action"] == "request" and not step["confident"]
        ),
    }
