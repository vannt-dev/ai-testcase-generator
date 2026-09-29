"""Unit tests for core/playwright_renderer.py."""
import pytest

from core.playwright_renderer import (
    comment,
    locator_expr,
    render_page,
    render_spec,
    slug,
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
