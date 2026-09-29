"""Edge cases for core/locator_healing.py found in the Heal Locators review."""
from core.locator_healing import apply_fixes, parse_locators, unified_diff, validate_fixes


def _fix(key, strategy="text", role="", value="New", confident=True, reason="r"):
    return {"key": key, "strategy": strategy, "role": role, "value": value, "confident": confident, "reason": reason}


def _heal(source, *fixes):
    locators, _ = parse_locators(source)
    kept, _ = validate_fixes(list(fixes), locators)
    return apply_fixes(source, locators, kept)


def test_lines_inside_a_block_comment_are_not_locators():
    source = (
        "    /*\n"
        "    this.a = page.getByText('old'); don't\n"
        "    */\n"
        "    this.a = page.getByText('real');\n"
        "    // a line comment with /* does not open a block\n"
        "    this.b = page.getByText('b');\n"
    )
    locators, skipped = parse_locators(source)

    assert [(loc["key"], loc["expression"], loc["line"]) for loc in locators] == [
        ("a", "page.getByText('real')", 3),
        ("b", "page.getByText('b')", 5),
    ]
    assert skipped == []


def test_regex_literal_skips_the_line():
    locators, skipped = parse_locators("    this.a = page.getByText(/'/).or(page.getByText('; //'));\n")

    assert locators == [] and skipped == [0]


def test_mixed_line_endings_keep_every_locator_and_terminator():
    source = (
        "    this.a = page.getByText('a');\r\n"
        "    this.b = page.getByText('b');\n"
        "    this.c = page.getByText('c');\r\n"
    )
    locators, _ = parse_locators(source)

    assert [loc["key"] for loc in locators] == ["a", "b", "c"]
    assert _heal(source, _fix("b")) == (
        "    this.a = page.getByText('a');\r\n"
        "    // healed: r\n"
        '    this.b = page.getByText("New");\n'
        "    this.c = page.getByText('c');\r\n"
    )


def test_note_above_a_last_line_without_newline():
    assert _heal("    this.a = page.getByText('a');", _fix("a")) == (
        '    // healed: r\n    this.a = page.getByText("New");'
    )


def test_a_testers_own_todo_comment_is_kept():
    source = "    // TODO verify locator: ask design about the id\n    this.a = page.getByText('a');\n"

    assert _heal(source, _fix("a")) == (
        "    // TODO verify locator: ask design about the id\n"
        "    // healed: r\n"
        '    this.a = page.getByText("New");\n'
    )


def test_healing_again_replaces_the_previous_notes():
    source = (
        "    // healed: first\n"
        "    // TODO verify locator: not confirmed by the new snapshot\n"
        "    this.a = page.getByText('a');\n"
    )

    assert _heal(source, _fix("a")) == '    // healed: r\n    this.a = page.getByText("New");\n'


def test_a_fix_that_only_changes_quote_style_is_dropped():
    locators, _ = parse_locators("    this.a = page.getByLabel('Email');\n")
    kept, warnings = validate_fixes([_fix("a", strategy="label", value="Email")], locators)

    assert kept == []
    assert warnings == ["a: the proposed locator is the same as the current one."]


def test_diff_of_a_mixed_line_ending_file():
    source = "    this.a = page.getByText('a');\r\n    this.b = page.getByText('b');\n"
    diff = unified_diff(source, _heal(source, _fix("b")), "p.ts")

    assert "\n+    this.b = page.getByText(\"New\");" in diff
    assert "\r" not in diff
