"""
Render a validated automation result (core.automation_validate) as a
Playwright + TypeScript project. Pure functions: no Streamlit, no AI.
Every string that reaches TypeScript goes through ts_string(), and every
comment through comment(), so AI text cannot break out of either.
"""
import json
import re

from core.automation_validate import ascii_fold

ENV_VALUE = re.compile(r"^\$\{ENV:([A-Z][A-Z0-9_]*)\}$")
_REGEX_SPECIAL = re.compile(r"[.*+?^${}()|[\]\\/]")


def ts_string(text: str) -> str:
    return json.dumps(str(text), ensure_ascii=False)


def comment(text: str) -> str:
    """One line (str.split also splits on U+2028/U+2029) with no '*/'."""
    return " ".join(str(text).split()).replace("*/", "* /")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", ascii_fold(text).lower()).strip("-")


def value_expr(value: str) -> str:
    match = ENV_VALUE.match(value)
    if match:
        return f"process.env.{match.group(1)} ?? ''"
    return ts_string(value)


def locator_expr(locator: dict) -> str:
    strategy, value = locator["strategy"], ts_string(locator["value"])
    if strategy == "role":
        role = ts_string(locator["role"])
        if locator["value"]:
            return f"page.getByRole({role}, {{ name: {value} }})"
        return f"page.getByRole({role})"
    method = {
        "label": "getByLabel",
        "placeholder": "getByPlaceholder",
        "text": "getByText",
        "test_id": "getByTestId",
        "css": "locator",
    }[strategy]
    return f"page.{method}({value})"


def render_page(page: dict) -> str:
    lines = [
        "import { type Locator, type Page } from '@playwright/test';",
        "",
        f"export class {page['name']} {{",
        f"  readonly path = {ts_string(page['path'])};",
    ]
    lines += [f"  readonly {loc['key']}: Locator;" for loc in page["locators"]]
    lines += ["", "  constructor(readonly page: Page) {"]
    for loc in page["locators"]:
        if not loc["confident"]:
            lines.append("    // TODO verify locator: not confirmed by an HTML/ARIA snapshot")
        lines.append(f"    this.{loc['key']} = {locator_expr(loc)};")
    lines += [
        "  }",
        "",
        "  async goto() {",
        "    await this.page.goto(this.path);",
        "  }",
        "}",
        "",
    ]
    return "\n".join(lines)


def _render_step(step: dict, pages_by_name: dict[str, dict]) -> str:
    action = step["action"]
    if action == "todo":
        return f"// TODO: {comment(step['source'])}"
    if action == "expect_url":
        pattern = _REGEX_SPECIAL.sub(lambda m: "\\" + m.group(0), step["value"])
        return f"await expect(page).toHaveURL(new RegExp({ts_string(pattern)}));"
    var = pages_by_name[step["page"]]["var"]
    if action == "goto":
        return f"await {var}.goto();"
    target = f"{var}.{step['locator']}"
    value = value_expr(step["value"])
    return {
        "click": f"await {target}.click();",
        "check": f"await {target}.check();",
        "uncheck": f"await {target}.uncheck();",
        "fill": f"await {target}.fill({value});",
        "select": f"await {target}.selectOption({value});",
        "press": f"await {target}.press({value});",
        "expect_visible": f"await expect({target}).toBeVisible();",
        "expect_hidden": f"await expect({target}).toBeHidden();",
        "expect_text": f"await expect({target}).toContainText({value});",
        "expect_value": f"await expect({target}).toHaveValue({value});",
    }[action]


def _pages_used(tests: list[dict]) -> list[str]:
    used: list[str] = []
    for test in tests:
        for step in test["steps"]:
            if step["page"] and step["page"] not in used:
                used.append(step["page"])
    return used


def _render_test(test: dict, pages_by_name: dict[str, dict]) -> str:
    fixme = any(step["action"] == "todo" for step in test["steps"])
    title = ts_string(f"{test['test_id']} {test['title']}".strip())
    lines = [f"{'test.fixme' if fixme else 'test'}({title}, async ({{ page }}) => {{"]
    for name in _pages_used([test]):
        lines.append(f"  const {pages_by_name[name]['var']} = new {name}(page);")
    for step in test["steps"]:
        note = comment(step["source"])
        if step["action"] != "todo" and note:
            lines.append(f"  // {note}")
        lines.append(f"  {_render_step(step, pages_by_name)}")
    lines.append("});")
    return "\n".join(lines)


def render_spec(tests: list[dict], pages_by_name: dict[str, dict]) -> str:
    imports = ["import { test, expect } from '@playwright/test';"]
    imports += [f"import {{ {name} }} from '../pages/{name}';" for name in sorted(_pages_used(tests))]
    body = "\n\n".join(_render_test(test, pages_by_name) for test in tests)
    return "\n".join(imports) + "\n\n" + body + "\n"
