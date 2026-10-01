"""
Render a validated API automation result (core.api_automation_validate) as
Playwright API tests. Pure functions: no Streamlit, no AI. Every string that
reaches TypeScript goes through ts_string() and every comment through
comment(); the only expressions made from the result are ${ENV:NAME} and
${VAR:name} placeholders, and a variable only when this renderer declared it.
"""
import json

from core.api_automation_validate import PLACEHOLDER
from core.automation_validate import WINDOWS_RESERVED
from core.playwright_renderer import comment, slug, ts_string

# Rendered through request.fetch with an explicit method.
_FETCH_ONLY = ("HEAD", "OPTIONS")


def text_expr(text: str, declared: set[str] | None = None) -> str:
    """
    A TypeScript string expression for text that may hold placeholders.
    With `declared`, a ${VAR:name} outside it stays literal text, so the
    output never names an identifier the test did not declare.
    """
    parts: list[str] = []
    position = 0
    for match in PLACEHOLDER.finditer(text):
        variable = match.group(2)
        if variable and declared is not None and variable not in declared:
            continue
        if match.start() > position:
            parts.append(ts_string(text[position:match.start()]))
        parts.append(f"String({variable})" if variable else f"(process.env.{match.group(1)} ?? '')")
        position = match.end()
    if position < len(text) or not parts:
        parts.append(ts_string(text[position:]))
    return " + ".join(parts)


def _value_expr(text: str, declared: set[str]) -> str:
    """Like text_expr, but a string that is exactly one saved variable keeps the variable's type."""
    match = PLACEHOLDER.fullmatch(text)
    if match and match.group(2) in declared:
        return match.group(2)
    if match and match.group(1):
        return f"process.env.{match.group(1)} ?? ''"
    return text_expr(text, declared)


def _key_expr(key: str) -> str:
    # A plain "__proto__" key would set the object's prototype instead of sending a property.
    return f"[{ts_string(key)}]" if key == "__proto__" else ts_string(key)


def _ts_value(value, declared: set[str]) -> str:
    """A parsed JSON value as a TypeScript literal, with placeholders inside strings resolved."""
    if isinstance(value, str):
        return _value_expr(value, declared)
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = ", ".join(f"{_key_expr(key)}: {_ts_value(item, declared)}" for key, item in value.items())
        return "{ " + items + " }"
    if isinstance(value, list):
        return "[" + ", ".join(_ts_value(item, declared) for item in value) + "]"
    return json.dumps(value)


def _pairs_expr(pairs: list[dict], declared: set[str]) -> str:
    return "{ " + ", ".join(
        f"{ts_string(pair['name'])}: {text_expr(pair['value'], declared)}" for pair in pairs
    ) + " }"


def _query_expr(pairs: list[dict], declared: set[str]) -> str:
    names = [pair["name"] for pair in pairs]
    if len(set(names)) == len(names):
        return _pairs_expr(pairs, declared)
    # A name sent more than once (?tag=a&tag=b) cannot be an object key.
    entries = ", ".join(f"[{ts_string(pair['name'])}, {text_expr(pair['value'], declared)}]" for pair in pairs)
    return f"new URLSearchParams([{entries}])"


def _render_request(step: dict, number: int, declared: set[str]) -> list[str]:
    lines: list[str] = []
    note = comment(step["source"])
    if note:
        lines.append(f"// {note}")
    if not step["confident"]:
        lines.append("// TODO verify this request: the endpoint was not in the API description")

    method = step["method"]
    headers = step["headers"]
    data = ""
    if step["body"]:
        parsed = json.loads(step["body"])
        data = _ts_value(parsed, declared)
        if isinstance(parsed, str):
            # Playwright sends a string as it is, with no JSON content type; a JSON string needs both.
            data = f"JSON.stringify({data})"
            if not any(pair["name"].casefold() == "content-type" for pair in headers):
                headers = headers + [{"name": "Content-Type", "value": "application/json"}]
    options: list[str] = []
    if method in _FETCH_ONLY:
        options.append(f"method: {ts_string(method)},")
    if headers:
        options.append(f"headers: {_pairs_expr(headers, declared)},")
    if step["query"]:
        options.append(f"params: {_query_expr(step['query'], declared)},")
    if data:
        options.append(f"data: {data},")

    call = "fetch" if method in _FETCH_ONLY else method.lower()
    response, body = f"response{number}", f"body{number}"
    url = f"apiUrl({text_expr(step['path'], declared)})"
    if options:
        lines.append(f"const {response} = await request.{call}({url}, {{")
        lines += [f"  {option}" for option in options]
        lines.append("});")
    else:
        lines.append(f"const {response} = await request.{call}({url});")

    if step["expect_status"]:
        lines.append(f"expect({response}.status()).toBe({step['expect_status']});")
    if step["saves"] or any(check["kind"] != "text_contains" for check in step["checks"]):
        lines.append(f"const {body} = await jsonBody({response});")
    for check in step["checks"]:
        target = f"at({body}, {ts_string(check['path'])})"
        kind = check["kind"]
        if kind == "json_equals":
            lines.append(f"expect({target}).toEqual({_ts_value(json.loads(check['value']), declared)});")
        elif kind == "json_contains":
            lines.append(f"expect(String({target})).toContain({text_expr(check['value'], declared)});")
        elif kind == "json_exists":
            lines.append(f"expect({target}).toBeDefined();")
        elif kind == "json_absent":
            lines.append(f"expect({target}).toBeUndefined();")
        else:
            lines.append(f"expect(await {response}.text()).toContain({text_expr(check['value'], declared)});")
    for save in step["saves"]:
        lines.append(f"const {save['var']} = at({body}, {ts_string(save['path'])});")
        # Without this a missing value would reach later requests as the text "undefined".
        missing = ts_string(f"{save['path'] or 'the body'} is missing from the response")
        lines.append(f"expect({save['var']}, {missing}).toBeDefined();")
    return lines


def _render_test(test: dict) -> str:
    fixme = any(step["action"] == "todo" for step in test["steps"])
    title = ts_string(f"{test['test_id']} {test['title']}".strip())
    lines = [f"{'test.fixme' if fixme else 'test'}({title}, async ({{ request }}) => {{"]
    # Only what earlier steps of this test saved may appear as an identifier.
    declared: set[str] = set()
    for number, step in enumerate(test["steps"], start=1):
        if step["action"] == "todo":
            lines.append(f"  // TODO: {comment(step['source'])}")
            continue
        lines += [f"  {line}" for line in _render_request(step, number, declared)]
        declared.update(save["var"] for save in step["saves"])
    lines.append("});")
    return "\n".join(lines)


def render_api_spec(tests: list[dict]) -> str:
    imports = (
        "import { test, expect } from '@playwright/test';\n"
        "import { apiUrl, at, jsonBody } from './support';\n"
    )
    return imports + "\n" + "\n\n".join(_render_test(test) for test in tests) + "\n"


def _support(api_base_url: str) -> str:
    return (
        "// Helpers for the generated API tests.\n"
        "import type { APIResponse } from '@playwright/test';\n"
        "\n"
        f"const API_BASE_URL = (process.env.API_BASE_URL ?? {ts_string(api_base_url)}).replace(/\\/+$/, '');\n"
        "\n"
        "export function apiUrl(path: string): string {\n"
        "  return API_BASE_URL + path;\n"
        "}\n"
        "\n"
        "// The parsed JSON body, or undefined when the response has none (204, HEAD).\n"
        "// eslint-disable-next-line @typescript-eslint/no-explicit-any\n"
        "export async function jsonBody(response: APIResponse): Promise<any> {\n"
        "  const text = await response.text();\n"
        "  return text ? JSON.parse(text) : undefined;\n"
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
