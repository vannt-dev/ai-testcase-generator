"""
Render a validated automation result (core.automation_validate) as a
Playwright + TypeScript project. Pure functions: no Streamlit, no AI.
Every string that reaches TypeScript goes through ts_string(), and every
comment through comment(), so AI text cannot break out of either.
"""
import io
import json
import re
import zipfile

from core.automation_validate import ENV_VALUE, WINDOWS_RESERVED, ascii_fold

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


PLAYWRIGHT_VERSION = "1.63.0"
TYPESCRIPT_VERSION = "5.9.3"
TYPES_NODE_VERSION = "22.20.4"

ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")

TSCONFIG = json.dumps({
    "compilerOptions": {
        "target": "ES2022",
        "module": "commonjs",
        "moduleResolution": "node",
        "strict": True,
        "esModuleInterop": True,
        "skipLibCheck": True,
        "types": ["node"],
        "noEmit": True,
    },
    "include": ["**/*.ts"],
}, indent=2) + "\n"

GITIGNORE = "node_modules/\ntest-results/\nplaywright-report/\nblob-report/\n.env\n"


def project_root(project_name: str) -> str:
    return f"{slug(project_name) or 'project'}-playwright"


def _one_line(text: str) -> str:
    return " ".join(str(text).split())


def _env_names(result: dict) -> list[str]:
    names = set()
    for test in result["tests"]:
        for step in test["steps"]:
            # expect_url matches its value literally, so it never reads .env.
            match = step["action"] != "expect_url" and ENV_VALUE.match(step["value"])
            if match:
                names.add(match.group(1))
    return sorted(names)


def _package_json(root: str) -> str:
    return json.dumps({
        "name": root,
        "private": True,
        "scripts": {
            "test": "playwright test",
            "test:ui": "playwright test --ui",
            "report": "playwright show-report",
            "typecheck": "tsc --noEmit",
        },
        "engines": {"node": ">=20.12"},
        "devDependencies": {
            "@playwright/test": PLAYWRIGHT_VERSION,
            "@types/node": TYPES_NODE_VERSION,
            "typescript": TYPESCRIPT_VERSION,
        },
    }, indent=2) + "\n"


def _playwright_config(base_url: str) -> str:
    return (
        "import { existsSync } from 'node:fs';\n"
        "import { defineConfig, devices } from '@playwright/test';\n"
        "\n"
        "// Values such as BASE_URL and passwords come from .env (see .env.example).\n"
        "if (existsSync('.env')) process.loadEnvFile('.env');\n"
        "\n"
        "export default defineConfig({\n"
        "  testDir: './tests',\n"
        "  fullyParallel: true,\n"
        "  retries: process.env.CI ? 2 : 0,\n"
        "  reporter: 'html',\n"
        "  use: {\n"
        f"    baseURL: process.env.BASE_URL ?? {ts_string(base_url)},\n"
        "    trace: 'on-first-retry',\n"
        "  },\n"
        "  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],\n"
        "});\n"
    )


def _env_example(base_url: str, names: list[str], api_base_url: str | None = None) -> str:
    lines = [f"BASE_URL={_one_line(base_url)}"]
    if api_base_url is not None:
        lines.append(f"API_BASE_URL={_one_line(api_base_url)}")
    return "".join(f"{line}\n" for line in lines + [f"{name}=" for name in names])


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "None."


def _api_readme(api_result: dict) -> str:
    fixme = [
        f"`{t['test_id']}` {_one_line(t['title'])}".rstrip()
        for t in api_result["tests"] if any(s["action"] == "todo" for s in t["steps"])
    ]
    unverified = [
        f"`{t['test_id']}` step {number}: {s['method']} {_one_line(s['path'])}"
        for t in api_result["tests"] for number, s in enumerate(t["steps"], start=1)
        if s["action"] == "request" and not s["confident"]
    ]
    return (
        "## API tests\n"
        "\n"
        "The tests under `tests/api` call `API_BASE_URL` from `.env`. Run only them with:\n"
        "\n"
        "```bash\n"
        "npx playwright test tests/api\n"
        "```\n"
        "\n"
        "### API tests marked fixme\n"
        "\n"
        f"{_bullets(fixme)}\n"
        "\n"
        "### Requests to verify\n"
        "\n"
        f"{_bullets(unverified)}\n"
        "\n"
    )


def _readme(
    project_name: str, result: dict, api_result: dict | None = None, api_questions: list[str] | None = None,
) -> str:
    """`api_result` is set when there are API tests; their questions come separately, as they matter even without."""
    fixme = [
        f"`{t['test_id']}` {_one_line(t['title'])}".rstrip()
        for t in result["tests"] if any(s["action"] == "todo" for s in t["steps"])
    ]
    unverified = [
        f"`{p['name']}.{loc['key']}`" for p in result["pages"] for loc in p["locators"] if not loc["confident"]
    ]
    questions = [_one_line(q) for q in result["open_questions"]]
    questions += [_one_line(q) for q in api_questions or []]
    return (
        f"# {_one_line(project_name)}: Playwright tests\n"
        "\n"
        "Generated by AI Test Case Generator. Review every TODO before relying on these tests.\n"
        "\n"
        "## Run\n"
        "\n"
        "```bash\n"
        "npm install\n"
        "npx playwright install\n"
        "cp .env.example .env   # then fill in the values\n"
        "npm test\n"
        "```\n"
        "\n"
        "## Tests marked fixme\n"
        "\n"
        f"{_bullets(fixme)}\n"
        "\n"
        "## Locators to verify\n"
        "\n"
        f"{_bullets(unverified)}\n"
        "\n"
        + (_api_readme(api_result) if api_result else "")
        + "## Open questions\n"
        "\n"
        f"{_bullets(questions)}\n"
    )


def render_project(
    result: dict, project_name: str, base_url: str, api_result: dict | None = None, api_base_url: str = "",
) -> dict[str, str]:
    """`api_result` (core.api_automation_validate) adds API tests to the same project."""
    # Imported here: core.api_renderer builds on this module's string helpers.
    from core.api_renderer import api_env_names, render_api_files

    api = api_result if api_result and api_result["tests"] else None
    pages_by_name = {page["name"]: page for page in result["pages"]}
    files: dict[str, str] = {}
    for page in sorted(result["pages"], key=lambda p: p["name"]):
        files[f"pages/{page['name']}.ts"] = render_page(page)
    groups: dict[str, list[dict]] = {}
    for test in result["tests"]:
        module = slug(test.get("module", "")) or "general"
        if module in WINDOWS_RESERVED:
            module += "-tests"
        groups.setdefault(module, []).append(test)
    for module, tests in sorted(groups.items()):
        files[f"tests/{module}.spec.ts"] = render_spec(tests, pages_by_name)
    names = _env_names(result)
    if api:
        files.update(render_api_files(api, api_base_url))
        names = sorted(set(names) | set(api_env_names(api)))
    # A project with API tests only has no web base URL; Playwright still wants one.
    web_base_url = base_url or api_base_url
    files["package.json"] = _package_json(project_root(project_name))
    files["playwright.config.ts"] = _playwright_config(web_base_url)
    files["tsconfig.json"] = TSCONFIG
    files[".env.example"] = _env_example(web_base_url, names, api_base_url if api else None)
    files[".gitignore"] = GITIGNORE
    files["README.md"] = _readme(project_name, result, api, (api_result or {}).get("open_questions"))
    return files


def summarize(result: dict) -> dict:
    return {
        "tests": len(result["tests"]),
        "fixme": sum(1 for t in result["tests"] if any(s["action"] == "todo" for s in t["steps"])),
        "unverified_locators": sum(1 for p in result["pages"] for loc in p["locators"] if not loc["confident"]),
    }


def _check_path(path: str) -> None:
    if not _SAFE_PATH.match(path) or ".." in path.split("/"):
        raise ValueError(f"Unsafe path in generated project: {path!r}")


def build_zip(files: dict[str, str], root_dir: str) -> bytes:
    _check_path(root_dir)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(files):
            _check_path(path)
            info = zipfile.ZipInfo(f"{root_dir}/{path}", date_time=ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[path])
    return buffer.getvalue()
