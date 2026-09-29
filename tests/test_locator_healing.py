"""Unit tests for core/locator_healing.py."""
import pytest

from core.locator_healing import (
    MAX_FILE_BYTES,
    HealingInputError,
    apply_fixes,
    healing_problems,
    parse_locators,
    read_page_object,
    unified_diff,
    validate_fixes,
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


LOCATORS, _ = parse_locators(GENERATED)


def _fix(key="submitButton", strategy="role", role="button", value="Log in", confident=True, reason="Button text changed"):
    return {"key": key, "strategy": strategy, "role": role, "value": value, "confident": confident, "reason": reason}


def test_valid_fix_gets_its_rendered_expression():
    kept, warnings = validate_fixes([_fix()], LOCATORS)

    assert warnings == []
    assert kept[0]["expression"] == 'page.getByRole("button", { name: "Log in" })'


def test_fix_for_an_unknown_key_is_dropped():
    kept, warnings = validate_fixes([_fix(key="ghost")], LOCATORS)

    assert kept == []
    assert warnings == ["The AI proposed a fix for 'ghost', which is not a locator in this file."]


def test_second_fix_for_a_key_is_dropped():
    kept, warnings = validate_fixes([_fix(), _fix(value="Other")], LOCATORS)

    assert [fix["value"] for fix in kept] == ["Log in"]
    assert warnings == ["Second fix for 'submitButton' ignored; the first is kept."]


def test_unknown_role_falls_back_to_text():
    kept, warnings = validate_fixes([_fix(role="btn")], LOCATORS)

    assert (kept[0]["strategy"], kept[0]["role"], kept[0]["confident"]) == ("text", "", False)
    assert warnings == ["submitButton: unknown ARIA role 'btn'; using a text locator."]


def test_fix_that_changes_nothing_is_dropped():
    kept, warnings = validate_fixes([_fix(key="emailInput", strategy="label", role="", value="Email")], LOCATORS)

    assert kept == []
    assert warnings == ["emailInput: the proposed locator is the same as the current one."]


def test_reason_is_one_line():
    kept, _ = validate_fixes([_fix(reason="a\nb */ c")], LOCATORS)

    assert kept[0]["reason"] == "a b * / c"


def test_apply_replaces_only_the_fixed_line():
    kept, _ = validate_fixes([_fix()], LOCATORS)

    assert apply_fixes(GENERATED, LOCATORS, kept) == GENERATED.replace(
        "    // TODO verify locator: not confirmed by an HTML/ARIA snapshot\n"
        '    this.submitButton = page.getByRole("button", { name: "Sign in" });\n',
        "    // healed: Button text changed\n"
        '    this.submitButton = page.getByRole("button", { name: "Log in" });\n',
    )


def test_unconfident_fix_gets_a_todo():
    kept, _ = validate_fixes(
        [_fix(key="emailInput", strategy="test_id", role="", value="email", confident=False, reason="Label removed")],
        LOCATORS,
    )

    assert apply_fixes(GENERATED, LOCATORS, kept) == GENERATED.replace(
        '    this.emailInput = page.getByLabel("Email");\n',
        "    // healed: Label removed\n"
        "    // TODO verify locator: not confirmed by the new snapshot\n"
        '    this.emailInput = page.getByTestId("email");\n',
    )


def test_several_fixes_at_once():
    kept, _ = validate_fixes(
        [_fix(), _fix(key="emailInput", strategy="test_id", role="", value="email", reason="r")], LOCATORS,
    )
    patched = apply_fixes(GENERATED, LOCATORS, kept)

    assert 'this.emailInput = page.getByTestId("email");' in patched
    assert 'this.submitButton = page.getByRole("button", { name: "Log in" });' in patched
    assert patched.index("emailInput = page") < patched.index("submitButton = page")


def test_crlf_and_trailing_comment_are_kept():
    source = HAND_EDITED.replace("\n", "\r\n")
    locators, _ = parse_locators(source)
    kept, _ = validate_fixes([_fix(key="emailInput", strategy="label", role="", value="Work email", reason="r")], locators)
    patched = apply_fixes(source, locators, kept)

    assert "\r\n    // healed: r\r\n    this.emailInput = page.getByLabel(\"Work email\"); // tester note; keep\r\n" in patched
    assert patched.count("\r\n") == source.count("\r\n") + 1
    assert "\n" not in patched.replace("\r\n", "")


def test_missing_trailing_newline_is_kept():
    source = GENERATED.rstrip("\n")
    locators, _ = parse_locators(source)
    kept, _ = validate_fixes([_fix()], locators)

    assert apply_fixes(source, locators, kept).endswith("}")


def test_u2028_inside_a_string_is_not_a_line_break():
    source = "    this.a = page.getByText(\"x\u2028y\");\n    this.b = page.getByText(\"b\");\n"
    locators, _ = parse_locators(source)
    kept, _ = validate_fixes([_fix(key="b", strategy="text", role="", value="c")], locators)

    assert [loc["line"] for loc in locators] == [0, 1]
    assert apply_fixes(source, locators, kept) == (
        "    this.a = page.getByText(\"x\u2028y\");\n    // healed: Button text changed\n    this.b = page.getByText(\"c\");\n"
    )


def test_hostile_value_and_reason_stay_escaped():
    kept, _ = validate_fixes([_fix(strategy="text", role="", value='a"b`${c}*/\nd', reason="x\ny */")], LOCATORS)
    patched = apply_fixes(GENERATED, LOCATORS, kept)

    assert '    // healed: x y * /\n' in patched
    assert '    this.submitButton = page.getByText("a\\"b`${c}*/\\nd");\n' in patched


def test_no_fixes_returns_the_source_unchanged():
    assert apply_fixes(GENERATED, LOCATORS, []) == GENERATED


def test_unified_diff():
    kept, _ = validate_fixes([_fix()], LOCATORS)
    diff = unified_diff(GENERATED, apply_fixes(GENERATED, LOCATORS, kept), "pages/LoginPage.ts")

    assert diff.startswith("--- a/pages/LoginPage.ts\n+++ b/pages/LoginPage.ts\n@@")
    assert '\n-    this.submitButton = page.getByRole("button", { name: "Sign in" });' in diff
    assert '\n+    this.submitButton = page.getByRole("button", { name: "Log in" });' in diff
