"""Unit tests for core/locator_healing.py."""
import pytest

from core.locator_healing import (
    MAX_FILE_BYTES,
    HealingInputError,
    healing_problems,
    parse_locators,
    read_page_object,
)
from core.playwright_renderer import render_page

GENERATED = render_page({"name": "LoginPage", "var": "loginPage", "path": "/login", "locators": [
    {"key": "emailInput", "strategy": "label", "role": "", "value": "Email", "confident": True},
    {"key": "submitButton", "strategy": "role", "role": "button", "value": "Sign in", "confident": False},
]})

HAND_EDITED = (
    "import { type Locator, type Page } from '@playwright/test';\n"
    "\n"
    "export class LoginPage {\n"
    "  readonly emailInput: Locator;\n"
    "  readonly banner: Locator;\n"
    "  readonly help: Locator;\n"
    "\n"
    "  constructor(readonly page: Page) {\n"
    "    this.emailInput = page.getByLabel('Email; work'); // tester note; keep\n"
    "    this.banner = page\n"
    "      .getByTestId('banner');\n"
    "    this.emailInput = page.getByLabel('Other');\n"
    "    this.help = this.page.getByText('Help');\n"
    "    this.count = 3;\n"
    "  }\n"
    "\n"
    "  async login(email: string) {\n"
    "    await this.emailInput.fill(email);\n"
    "  }\n"
    "}\n"
)


def _summary(locators):
    return [(loc["key"], loc["expression"], loc["line"]) for loc in locators]


def test_parse_a_generated_page_object():
    locators, skipped = parse_locators(GENERATED)

    assert _summary(locators) == [
        ("emailInput", 'page.getByLabel("Email")', 8),
        ("submitButton", 'page.getByRole("button", { name: "Sign in" })', 10),
    ]
    assert skipped == []


def test_spans_point_at_the_expression():
    locators, _ = parse_locators(GENERATED)
    line = GENERATED.split("\n")[locators[0]["line"]]

    assert line[locators[0]["start"]:locators[0]["end"]] == 'page.getByLabel("Email")'


def test_parse_a_hand_edited_file_skips_multiline_and_repeated_assignments():
    locators, skipped = parse_locators(HAND_EDITED)

    assert _summary(locators) == [("emailInput", "page.getByLabel('Email; work')", 8)]
    assert skipped == [9, 11]


def test_semicolon_and_slashes_inside_strings_do_not_end_the_expression():
    source = "    this.a = page.getByText('a; b // c', { exact: true });  // note\n"
    locators, skipped = parse_locators(source)

    assert _summary(locators) == [("a", "page.getByText('a; b // c', { exact: true })", 0)]
    assert skipped == []


def test_escaped_quote_inside_a_string():
    source = '    this.a = page.getByText("say \\"hi\\"; now");\n'
    locators, _ = parse_locators(source)

    assert locators[0]["expression"] == 'page.getByText("say \\"hi\\"; now")'


def test_code_after_the_semicolon_skips_the_line():
    locators, skipped = parse_locators("    this.a = page.getByText('x'); this.b = 1;\n")

    assert locators == [] and skipped == [0]


def test_read_page_object():
    assert read_page_object("const a = 'Đăng nhập';\n".encode("utf-8")) == "const a = 'Đăng nhập';\n"
    with pytest.raises(HealingInputError, match="not UTF-8"):
        read_page_object(b"\xff\xfe\x00")
    with pytest.raises(HealingInputError, match="100,000 bytes"):
        read_page_object(b"a" * (MAX_FILE_BYTES + 1))


def test_healing_problems():
    locators, _ = parse_locators(GENERATED)

    assert healing_problems(locators, "Error: locator not found", "<button>Log in</button>") == []
    assert healing_problems(None, "e", "s") == ["Upload a page object file (.ts)."]
    assert healing_problems([], "e", "s") == [
        "The file has no one-line `this.<name> = page.…;` locators. Is it a page object?"
    ]
    assert healing_problems(locators, " ", "") == [
        "Paste the Playwright error.",
        "Paste the page's current HTML or ARIA snapshot.",
    ]
    assert healing_problems(locators, "e" * 20_001, "s" * 50_001) == [
        "The error is longer than 20,000 characters; paste only the failing test's output.",
        "The snapshot is longer than 50,000 characters; paste only the relevant part of the page.",
    ]
