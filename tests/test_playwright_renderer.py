"""Unit tests for core/playwright_renderer.py."""
import io
import json
import zipfile

import pytest

from core.playwright_renderer import (
    build_zip,
    comment,
    locator_expr,
    project_root,
    render_project,
    render_page,
    render_spec,
    slug,
    summarize,
    ts_string,
    value_expr,
)


def _loc(key, strategy, value, role="", confident=True):
    return {"key": key, "strategy": strategy, "role": role, "value": value, "confident": confident}


def _step(action, page="", locator="", value="", source="src"):
    return {"action": action, "page": page, "locator": locator, "value": value, "source": source}


LOGIN = {
    "name": "LoginPage", "var": "loginPage", "path": "/login",
    "locators": [
        _loc("emailInput", "label", "Email"),
        _loc("submitButton", "role", "Sign in", role="button", confident=False),
    ],
}
PAGES = {"LoginPage": LOGIN}


@pytest.mark.parametrize("locator, expected", [
    (_loc("a", "role", "Sign in", role="button"), 'page.getByRole("button", { name: "Sign in" })'),
    (_loc("a", "role", "", role="searchbox"), 'page.getByRole("searchbox")'),
    (_loc("a", "label", "Email"), 'page.getByLabel("Email")'),
    (_loc("a", "placeholder", "Search"), 'page.getByPlaceholder("Search")'),
    (_loc("a", "text", "Welcome"), 'page.getByText("Welcome")'),
    (_loc("a", "test_id", "login-error"), 'page.getByTestId("login-error")'),
    (_loc("a", "css", "select#lang"), 'page.locator("select#lang")'),
])
def test_locator_strategies(locator, expected):
    assert locator_expr(locator) == expected


def test_value_expr_reads_env_placeholders():
    assert value_expr("${ENV:TEST_PASSWORD}") == "process.env.TEST_PASSWORD ?? ''"
    assert value_expr("${ENV:lower}") == '"${ENV:lower}"'
    assert value_expr("x ${ENV:A}") == '"x ${ENV:A}"'
    assert value_expr("plain") == '"plain"'


def test_hostile_strings_stay_inside_literals_and_comments():
    hostile = "a\"b'c`d${e}*/f\ng h\\i"

    assert ts_string(hostile) == '"a\\"b\'c`d${e}*/f\\ng h\\\\i"'
    assert comment(hostile) == "a\"b'c`d${e}* /f g h\\i"
    assert "\n" not in comment("one\r\ntwo three")


def test_slug():
    assert slug("Đăng nhập") == "dang-nhap"
    assert slug("  Checkout / Payment ") == "checkout-payment"
    assert slug("!!!") == ""


def test_render_page():
    assert render_page(LOGIN) == (
        "import { type Locator, type Page } from '@playwright/test';\n"
        "\n"
        "export class LoginPage {\n"
        '  readonly path = "/login";\n'
        "  readonly emailInput: Locator;\n"
        "  readonly submitButton: Locator;\n"
        "\n"
        "  constructor(readonly page: Page) {\n"
        '    this.emailInput = page.getByLabel("Email");\n'
        "    // TODO verify locator: not confirmed by an HTML/ARIA snapshot\n"
        '    this.submitButton = page.getByRole("button", { name: "Sign in" });\n'
        "  }\n"
        "\n"
        "  async goto() {\n"
        "    await this.page.goto(this.path);\n"
        "  }\n"
        "}\n"
    )


@pytest.mark.parametrize("step, expected", [
    (_step("goto", "LoginPage"), "await loginPage.goto();"),
    (_step("click", "LoginPage", "submitButton"), "await loginPage.submitButton.click();"),
    (_step("check", "LoginPage", "emailInput"), "await loginPage.emailInput.check();"),
    (_step("uncheck", "LoginPage", "emailInput"), "await loginPage.emailInput.uncheck();"),
    (_step("fill", "LoginPage", "emailInput", "a@b.c"), 'await loginPage.emailInput.fill("a@b.c");'),
    (_step("select", "LoginPage", "emailInput", "vi"), 'await loginPage.emailInput.selectOption("vi");'),
    (_step("press", "LoginPage", "emailInput", "Enter"), 'await loginPage.emailInput.press("Enter");'),
    (_step("expect_visible", "LoginPage", "emailInput"), "await expect(loginPage.emailInput).toBeVisible();"),
    (_step("expect_hidden", "LoginPage", "emailInput"), "await expect(loginPage.emailInput).toBeHidden();"),
    (_step("expect_text", "LoginPage", "emailInput", "Hi"), 'await expect(loginPage.emailInput).toContainText("Hi");'),
    (_step("expect_value", "LoginPage", "emailInput", "x"), 'await expect(loginPage.emailInput).toHaveValue("x");'),
    (_step("expect_url", value="/home?tab=1"), 'await expect(page).toHaveURL(new RegExp("\\\\/home\\\\?tab=1"));'),
])
def test_each_action(step, expected):
    spec = render_spec([{"test_id": "TC_1", "title": "t", "module": "", "steps": [step]}], PAGES)

    assert f"  {expected}\n" in spec


def test_render_spec_imports_used_pages_and_comments_steps():
    tests = [{"test_id": "TC_1", "title": "Login works", "module": "Login", "steps": [
        _step("goto", "LoginPage", source="Open the login page"),
        _step("fill", "LoginPage", "emailInput", "${ENV:USER_EMAIL}", source="Enter\nemail"),
    ]}]

    assert render_spec(tests, PAGES) == (
        "import { test, expect } from '@playwright/test';\n"
        "import { LoginPage } from '../pages/LoginPage';\n"
        "\n"
        'test("TC_1 Login works", async ({ page }) => {\n'
        "  const loginPage = new LoginPage(page);\n"
        "  // Open the login page\n"
        "  await loginPage.goto();\n"
        "  // Enter email\n"
        "  await loginPage.emailInput.fill(process.env.USER_EMAIL ?? '');\n"
        "});\n"
    )


def test_todo_step_makes_the_test_fixme():
    tests = [{"test_id": "TC_2", "title": "Needs work", "module": "", "steps": [
        _step("goto", "LoginPage", source="Open"),
        _step("todo", source="Verify the */ email arrives"),
    ]}]
    spec = render_spec(tests, PAGES)

    assert 'test.fixme("TC_2 Needs work", async ({ page }) => {' in spec
    assert "  // TODO: Verify the * / email arrives\n" in spec


def test_tests_are_separated_by_a_blank_line_and_keep_order():
    tests = [
        {"test_id": "TC_B", "title": "b", "module": "", "steps": [_step("todo")]},
        {"test_id": "TC_A", "title": "a", "module": "", "steps": [_step("todo")]},
    ]
    spec = render_spec(tests, PAGES)

    assert spec.index("TC_B") < spec.index("TC_A")
    assert "});\n\ntest.fixme(" in spec


def _result(tests, pages=None, questions=None):
    return {"pages": pages if pages is not None else [LOGIN], "tests": tests, "open_questions": questions or []}


ONE_TEST = [{"test_id": "TC_1", "title": "Login", "module": "Đăng nhập", "steps": [
    _step("goto", "LoginPage"),
    _step("fill", "LoginPage", "emailInput", "${ENV:USER_EMAIL}"),
]}]


def test_project_root():
    assert project_root("Demo Shop") == "demo-shop-playwright"
    assert project_root("!!!") == "project-playwright"


def test_render_project_file_set():
    files = render_project(_result(ONE_TEST), "Demo Shop", "https://staging.example.com")

    assert sorted(files) == [
        ".env.example", ".gitignore", "README.md", "package.json",
        "pages/LoginPage.ts", "playwright.config.ts", "tests/dang-nhap.spec.ts", "tsconfig.json",
    ]


def test_module_files_use_ascii_slugs():
    tests = [
        {**ONE_TEST[0], "test_id": "TC_1", "module": "Đăng nhập"},
        {**ONE_TEST[0], "test_id": "TC_2", "module": ""},
        {**ONE_TEST[0], "test_id": "TC_3", "module": "dang nhap"},
    ]
    files = render_project(_result(tests), "Demo", "https://x.test")

    assert "TC_1" in files["tests/dang-nhap.spec.ts"] and "TC_3" in files["tests/dang-nhap.spec.ts"]
    assert "TC_2" in files["tests/general.spec.ts"]


def test_package_json_pins_versions_and_scripts():
    package = json.loads(render_project(_result(ONE_TEST), "Demo Shop", "https://x.test")["package.json"])

    assert package["name"] == "demo-shop-playwright"
    assert package["private"] is True
    assert package["devDependencies"] == {
        "@playwright/test": "1.63.0", "@types/node": "22.20.4", "typescript": "5.9.3",
    }
    assert package["scripts"]["typecheck"] == "tsc --noEmit"
    assert package["scripts"]["test"] == "playwright test"
    assert package["engines"] == {"node": ">=20.12"}


def test_config_uses_base_url_and_loads_env_file():
    config = render_project(_result(ONE_TEST), "Demo", 'https://x.test/"a')["playwright.config.ts"]

    assert "baseURL: process.env.BASE_URL ?? \"https://x.test/\\\"a\"," in config
    assert "if (existsSync('.env')) process.loadEnvFile('.env');" in config


def test_env_example_lists_base_url_and_env_names():
    tests = [{"test_id": "TC_1", "title": "t", "module": "", "steps": [
        _step("fill", "LoginPage", "emailInput", "${ENV:USER_EMAIL}"),
        _step("fill", "LoginPage", "emailInput", "${ENV:A_TOKEN}"),
        _step("fill", "LoginPage", "emailInput", "${ENV:USER_EMAIL}"),
    ]}]
    env = render_project(_result(tests), "Demo", "https://x.test\nEVIL=1")[".env.example"]

    assert env == "BASE_URL=https://x.test EVIL=1\nA_TOKEN=\nUSER_EMAIL=\n"


def test_readme_lists_todos_and_questions():
    tests = [{"test_id": "TC_2", "title": "Needs work", "module": "", "steps": [_step("todo")]}]
    readme = render_project(_result(tests, questions=["Which account?"]), "Demo Shop", "https://x.test")["README.md"]

    assert readme.startswith("# Demo Shop: Playwright tests\n")
    assert "npm install" in readme and "npx playwright install" in readme
    assert "- `TC_2` Needs work" in readme
    assert "- `LoginPage.submitButton`" in readme
    assert "- Which account?" in readme


def test_readme_says_none_when_nothing_to_do():
    page = {**LOGIN, "locators": [_loc("emailInput", "label", "Email")]}
    readme = render_project(_result(ONE_TEST, pages=[page]), "Demo", "https://x.test")["README.md"]

    assert readme.count("None.") == 3


def test_summarize():
    tests = ONE_TEST + [{"test_id": "TC_2", "title": "t", "module": "", "steps": [_step("todo")]}]

    assert summarize(_result(tests)) == {"tests": 2, "fixme": 1, "unverified_locators": 1}


def test_zip_is_deterministic_and_rooted():
    files = render_project(_result(ONE_TEST), "Demo", "https://x.test")
    first = build_zip(files, "demo-playwright")

    assert first == build_zip(dict(reversed(list(files.items()))), "demo-playwright")
    with zipfile.ZipFile(io.BytesIO(first)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(name.startswith("demo-playwright/") for name in names)
        assert archive.getinfo("demo-playwright/package.json").date_time == (1980, 1, 1, 0, 0, 0)
        assert archive.read("demo-playwright/pages/LoginPage.ts").decode("utf-8") == files["pages/LoginPage.ts"]


@pytest.mark.parametrize("bad_path", ["../evil.ts", "/abs.ts", "tests/../../x", "a\b.ts", ""])
def test_zip_rejects_unsafe_paths(bad_path):
    with pytest.raises(ValueError):
        build_zip({bad_path: "x"}, "demo-playwright")


def test_zip_rejects_unsafe_root():
    with pytest.raises(ValueError):
        build_zip({"a.ts": "x"}, "../demo")


def test_windows_reserved_module_names_get_a_suffix():
    tests = [{**ONE_TEST[0], "module": "Con"}, {**ONE_TEST[0], "test_id": "TC_2", "module": "lpt1"}]
    files = render_project(_result(tests), "Demo", "https://x.test")

    assert "tests/con-tests.spec.ts" in files
    assert "tests/lpt1-tests.spec.ts" in files


def test_env_placeholder_in_expect_url_is_not_listed_in_env_example():
    tests = [{"test_id": "TC_1", "title": "t", "module": "", "steps": [_step("expect_url", value="${ENV:HOME_URL}")]}]

    assert render_project(_result(tests), "Demo", "https://x.test")[".env.example"] == "BASE_URL=https://x.test\n"


WEB = {
    "pages": [{"name": "LoginPage", "var": "loginPage", "path": "/login", "locators": [
        {"key": "emailInput", "strategy": "label", "role": "", "value": "Email", "confident": True},
    ]}],
    "tests": [{"test_id": "TC_1", "title": "Open login", "module": "Login", "steps": [
        {"action": "goto", "page": "LoginPage", "locator": "", "value": "", "source": "Open login"},
    ]}],
    "open_questions": ["Which account?"],
}
NO_WEB = {"pages": [], "tests": [], "open_questions": []}


def _api_step(**overrides):
    step = {
        "action": "request", "method": "GET", "path": "/orders", "headers": [], "query": [], "body": "",
        "expect_status": 200, "checks": [], "saves": [], "confident": True, "source": "1. GET /orders",
    }
    step.update(overrides)
    return step


API = {
    "tests": [
        {"test_id": "TC_ORD_1", "title": "List orders", "module": "Orders", "steps": [
            _api_step(headers=[{"name": "Authorization", "value": "Bearer ${ENV:API_TOKEN}"}], confident=False),
        ]},
        {"test_id": "TC_ORD_2", "title": "Email is sent", "module": "Orders", "steps": [
            _api_step(action="todo", method="", path="", expect_status=0, confident=False, source="Check the email"),
        ]},
    ],
    "open_questions": ["Which token?"],
}


def test_a_project_without_api_arguments_is_unchanged():
    plain = render_project(WEB, "Demo", "https://web.example.com")

    assert render_project(WEB, "Demo", "https://web.example.com", None, "") == plain
    assert render_project(WEB, "Demo", "https://web.example.com", {"tests": [], "open_questions": []}, "") == plain
    assert not any(path.startswith("tests/api/") for path in plain)
    assert "API" not in plain["README.md"] and "API_BASE_URL" not in plain[".env.example"]


def test_api_tests_join_the_web_project():
    files = render_project(WEB, "Demo", "https://web.example.com", API, "https://api.example.com")

    assert "tests/api/orders.api.spec.ts" in files and "tests/api/support.ts" in files
    assert "tests/login.spec.ts" in files and "pages/LoginPage.ts" in files
    assert files[".env.example"] == (
        "BASE_URL=https://web.example.com\nAPI_BASE_URL=https://api.example.com\nAPI_TOKEN=\n"
    )
    assert 'baseURL: process.env.BASE_URL ?? "https://web.example.com"' in files["playwright.config.ts"]
    readme = files["README.md"]
    assert "npx playwright test tests/api" in readme
    assert "- `TC_ORD_2` Email is sent" in readme
    assert "- `TC_ORD_1` step 1: GET /orders" in readme
    assert "- Which account?\n- Which token?\n" in readme


def test_an_api_only_project_has_no_pages_and_falls_back_to_the_api_base_url():
    files = render_project(NO_WEB, "Demo", "", API, "https://api.example.com")

    assert not any(path.startswith("pages/") for path in files)
    assert [path for path in files if path.startswith("tests/")] == [
        "tests/api/support.ts", "tests/api/orders.api.spec.ts",
    ]
    assert 'baseURL: process.env.BASE_URL ?? "https://api.example.com"' in files["playwright.config.ts"]
    assert files[".env.example"].startswith(
        "BASE_URL=https://api.example.com\nAPI_BASE_URL=https://api.example.com\n"
    )
