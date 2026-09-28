# Bug Report Writer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Bug Reporter page that turns a tester's rough notes into a structured bug report, editable and exportable as Markdown or Excel.

**Architecture:** One-bug core (`AIClient.write_bug_report` → `BugReport`) reusing the existing `_call_ai` retry/usage wrapper; tracker-neutral exporters in `core/bug_exporters.py`; a Streamlit page `pages/2_Bug_Reporter.py` that edits the report in session state and exports it. Step 2 (batch from a test run) will call the same core later.

**Tech Stack:** Python 3.11+, Streamlit (`streamlit.testing.v1.AppTest` for page tests), Anthropic Python SDK 1.x structured outputs (`messages.parse`), Pydantic v2, openpyxl, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-bug-report-writer-design.md`

## Global Constraints

- Run tests with `.venv/Scripts/python.exe -m pytest -q` (Windows; `.venv/bin/python` elsewhere). The suite is 109 passing before this plan.
- No test calls the real Anthropic API; use the `FakeMessages`/`make_client` pattern in `tests/test_ai_client.py` or `patch.object(AIClient, ...)` in page tests.
- Model default stays `DEFAULT_MODEL = "claude-sonnet-5"`; do not add models.
- Severity values exactly `Critical`, `Major`, `Minor`, `Trivial`; priority values exactly `High`, `Medium`, `Low`.
- Excel string cells are written as literal text (`cell.data_type = "s"`), as `core/excel_exporter.py` does.
- Nothing is written to disk on the server; exports are download bytes only.
- Source, comments, commit messages and docs are English. Commits use Conventional Commits and carry no `Co-Authored-By` or `Claude-Session` trailers. Stage files explicitly (no `git add -A`).
- Work on branch `feat/bug-report-writer` (already created; the spec is committed there).

## Review Focus

1. Notes containing Markdown syntax (`# heading`, `- item`, `1. item`, backticks) — the exported Markdown must keep its own structure; user text renders literally.
2. Text starting with `=` (e.g. actual result `=SUM(A1)` or test data `=1+1`) — Excel must store it as text, not a formula.
3. Vietnamese and other non-ASCII text — preserved in the Markdown download (UTF-8) and in Excel.
4. Writing a second report after editing the first — every field shows the new report; no edited value from the first report leaks through.
5. A related test case pasted as plain text rather than JSON — sent to the AI verbatim; JSON objects are sent pretty-printed.

Tests pinning each line: 1 → Task 2 `test_markdown_escapes_user_markdown`; 2 → Task 2 `test_excel_keeps_formula_like_text_literal`; 3 → Task 2 `test_markdown_and_excel_keep_non_ascii_text`; 4 → Task 3 `test_second_report_replaces_edited_fields`; 5 → Task 1 `test_write_bug_report_sends_plain_text_related_case_verbatim` and Task 3 `test_related_case_json_is_parsed_and_text_is_kept`.

---

### Task 1: BugReport model, prompt and `write_bug_report`

**Files:**
- Create: `prompts/bug_report_system_prompt.md`
- Modify: `core/prompt_builder.py` (add `BUG_REPORT_PROMPT_PATH` after `COLUMN_MAPPING_PROMPT_PATH`, line 13)
- Modify: `core/ai_client.py` (add `BugReport` after `ColumnMappingResult`; add `write_bug_report` at the end of `AIClient`)
- Test: `tests/test_ai_client.py`, `tests/test_ai_client_schemas.py`, `tests/test_prompt_builder.py`

**Interfaces:**
- Consumes: `AIClient._call_ai(system_prompt: str, user_content: str, output_format: type[BaseModel])`, `AIClient._build_usage(usage)`, `build_system_prompt(config: dict, base_prompt_path: Path) -> str`.
- Produces:
  - `core.ai_client.BugReport` (Pydantic model; fields in Step 3).
  - `AIClient.write_bug_report(system_prompt: str, notes: str, related_test_case: dict | str | None = None) -> dict` returning `{"report": <BugReport dict>, "usage": <usage dict>}`.
  - `core.prompt_builder.BUG_REPORT_PROMPT_PATH: Path`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ai_client.py` (update the import on line 8 to `from core.ai_client import AIClient, BugReport, GenerationResult, ReviewResult, ColumnMappingResult`):

```python
VALID_BUG = BugReport.model_validate(
    {
        "title": "App freezes when paying with an expired card",
        "module": "Checkout",
        "severity": "Major",
        "priority": "High",
        "environment": "",
        "preconditions": "Logged in with a cart that has one item",
        "steps_to_reproduce": ["Open the cart", "Tap Pay", "Enter an expired card and confirm"],
        "expected_result": "An 'expired card' error is shown",
        "actual_result": "The app freezes and shows no error",
        "test_data": "Card 4111 1111 1111 1111, expiry 01/20",
        "related_test_id": "",
        "open_questions": ["Which app version and device?"],
    }
)


def _bug_response():
    return SimpleNamespace(
        parsed_output=VALID_BUG,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20),
    )


def test_write_bug_report_returns_report_and_usage():
    client, messages = make_client(_bug_response())

    result = client.write_bug_report("system prompt", "pay with expired card -> freeze")

    assert result["report"]["title"] == "App freezes when paying with an expired card"
    assert result["report"]["steps_to_reproduce"][1] == "Tap Pay"
    assert result["usage"]["output_tokens"] == 20
    assert messages.kwargs["output_format"] is BugReport
    content = messages.kwargs["messages"][0]["content"]
    assert "pay with expired card -> freeze" in content
    assert "Related test case" not in content


def test_write_bug_report_sends_related_test_case_as_json():
    client, messages = make_client(_bug_response())

    client.write_bug_report(
        "system prompt", "notes", {"test_id": "TC_PAY_003", "title": "Pay with expired card"}
    )

    content = messages.kwargs["messages"][0]["content"]
    assert "Related test case" in content
    assert '"test_id": "TC_PAY_003"' in content


def test_write_bug_report_sends_plain_text_related_case_verbatim():
    client, messages = make_client(_bug_response())

    client.write_bug_report("system prompt", "notes", "TC_PAY_003 | Pay with expired card | High")

    assert "TC_PAY_003 | Pay with expired card | High" in messages.kwargs["messages"][0]["content"]


def test_write_bug_report_serializes_non_json_native_values():
    client, messages = make_client(_bug_response())
    created = datetime(2026, 9, 28, 9, 0, 0)

    client.write_bug_report("system prompt", "notes", {"test_id": "TC_1", "created": created})

    assert str(created) in messages.kwargs["messages"][0]["content"]
```

Append to `tests/test_ai_client_schemas.py` (add `BugReport` to its `core.ai_client` import and `import pytest` / `from pydantic import ValidationError` if not already imported):

```python
def _bug_payload(**overrides):
    payload = {
        "title": "Crash on pay",
        "module": "Checkout",
        "severity": "Critical",
        "priority": "High",
        "environment": "",
        "preconditions": "",
        "steps_to_reproduce": ["Tap Pay"],
        "expected_result": "Payment succeeds",
        "actual_result": "App crashes",
        "test_data": "",
        "related_test_id": "",
        "open_questions": [],
    }
    payload.update(overrides)
    return payload


def test_bug_report_accepts_valid_payload():
    assert BugReport.model_validate(_bug_payload()).severity == "Critical"


@pytest.mark.parametrize(
    "overrides",
    [
        {"severity": "Blocker"},
        {"priority": "Urgent"},
        {"steps_to_reproduce": []},
        {"title": "   "},
        {"actual_result": ""},
    ],
)
def test_bug_report_rejects_invalid_values(overrides):
    with pytest.raises(ValidationError):
        BugReport.model_validate(_bug_payload(**overrides))
```

Append to `tests/test_prompt_builder.py` (add `BUG_REPORT_PROMPT_PATH` to the `core.prompt_builder` import):

```python
def test_build_system_prompt_for_bug_reports_includes_rules_and_project():
    config = load_project_config(CONFIGS_DIR / "example_ecommerce.yaml")

    prompt = build_system_prompt(config, base_prompt_path=BUG_REPORT_PROMPT_PATH)

    assert "Never invent steps" in prompt
    assert "open_questions" in prompt
    assert "E-commerce App Demo" in prompt
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ai_client.py tests/test_ai_client_schemas.py tests/test_prompt_builder.py -q`
Expected: collection errors — `ImportError: cannot import name 'BugReport'` and `cannot import name 'BUG_REPORT_PROMPT_PATH'`.

- [ ] **Step 3: Implement the model, prompt path, prompt and method**

In `core/ai_client.py`, after `class ColumnMappingResult`:

```python
class BugReport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    module: str = Field(min_length=1)
    severity: Literal["Critical", "Major", "Minor", "Trivial"]
    priority: Literal["High", "Medium", "Low"]
    # Empty strings mean "the notes don't say"; the AI must not guess them.
    environment: str
    preconditions: str
    steps_to_reproduce: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    actual_result: str = Field(min_length=1)
    test_data: str
    related_test_id: str
    open_questions: list[str]
```

At the end of `class AIClient`:

```python
    def write_bug_report(
        self,
        system_prompt: str,
        notes: str,
        related_test_case: dict | str | None = None,
    ) -> dict:
        """
        Turn a tester's rough notes about one defect into a structured bug
        report. `related_test_case` is optional context: a dict of test case
        fields (sent as JSON) or text pasted by the user (sent verbatim).
        Returns {"report": {...BugReport...}, "usage": {...}}.
        """
        user_content = f"Tester's notes about the defect:\n\n{notes}"
        if isinstance(related_test_case, dict):
            related = json.dumps(related_test_case, ensure_ascii=False, indent=2, default=str)
        else:
            related = (related_test_case or "").strip()
        if related:
            user_content += f"\n\nRelated test case:\n\n{related}"

        message = self._call_ai(system_prompt, user_content, BugReport)
        return {
            "report": message.parsed_output.model_dump(),
            "usage": self._build_usage(message.usage),
        }
```

In `core/prompt_builder.py`, after line 13:

```python
BUG_REPORT_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "bug_report_system_prompt.md"
```

Create `prompts/bug_report_system_prompt.md`:

```markdown
You are a Senior QA Lead writing a bug report from a tester's rough
notes about ONE defect. You are NOT writing test cases.

TASK:
Turn the notes (and the related test case, when one is given) into a
complete, precise bug report a developer can act on without asking the
tester again — except for the questions you list.

MANDATORY RULES:
1. Use only facts from the notes, the related test case and the project
   config. Never invent steps, environments, app versions, devices,
   accounts or data.
2. When a developer would need something the notes don't give (build or
   app version, device/browser, account, exact input), add a question to
   "open_questions" and leave the related field as an empty string instead
   of guessing.
3. "steps_to_reproduce": one action per item, in order, starting from the
   state described in "preconditions". Do not number them yourself.
4. "title": the observed failure and where it happens, under 100
   characters (e.g. "Checkout freezes when paying with an expired card").
5. "severity" is user impact:
   - Critical: crash, data loss or a security issue with no workaround
   - Major: a main flow is broken
   - Minor: something is wrong but a workaround exists
   - Trivial: cosmetic
   "priority" (High / Medium / Low) is how urgently it should be fixed and
   may differ from severity.
6. Use the project's glossary terms and domain rules where they apply;
   name the violated domain rule in "actual_result" when there is one.
7. "related_test_id": the test_id of the related test case when one is
   given, otherwise an empty string.
8. Write in the same language as the tester's notes.

OUTPUT FORMAT:
Respond with ONLY a single valid JSON object matching the BugReport
schema: title, module, severity, priority, environment, preconditions,
steps_to_reproduce (array of strings), expected_result, actual_result,
test_data, related_test_id, open_questions (array of strings).
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_ai_client.py tests/test_ai_client_schemas.py tests/test_prompt_builder.py -q`
Expected: all pass.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 109 + the new tests pass, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add core/ai_client.py core/prompt_builder.py prompts/bug_report_system_prompt.md tests/test_ai_client.py tests/test_ai_client_schemas.py tests/test_prompt_builder.py
git commit -m "feat: write structured bug reports from a tester's notes"
```

---

### Task 2: Markdown and Excel exporters

**Files:**
- Create: `core/bug_exporters.py`
- Test: `tests/test_bug_exporters.py`

**Interfaces:**
- Consumes: a report dict with the `BugReport` keys (Task 1). Exporters must also accept edited reports whose required fields are empty strings (the page renders previews while the user edits).
- Produces:
  - `REQUIRED_FIELD_LABELS: dict[str, str]`
  - `missing_required_fields(report: dict) -> list[str]` — labels of required fields that are blank, in display order.
  - `to_markdown(report: dict) -> str`
  - `to_excel(reports: list[dict]) -> bytes`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bug_exporters.py`:

```python
import io

import openpyxl

from core.bug_exporters import missing_required_fields, to_excel, to_markdown


def _report(**overrides):
    report = {
        "title": "Checkout freezes when paying with an expired card",
        "module": "Checkout",
        "severity": "Major",
        "priority": "High",
        "environment": "Android 15, app 3.2.0",
        "preconditions": "Logged in with one item in the cart",
        "steps_to_reproduce": ["Open the cart", "Tap Pay", "Enter an expired card"],
        "expected_result": "An 'expired card' error is shown",
        "actual_result": "The app freezes",
        "test_data": "Card expiry 01/20",
        "related_test_id": "TC_PAY_003",
        "open_questions": ["Does it happen on iOS?"],
    }
    report.update(overrides)
    return report


def _sheet(data: bytes):
    return openpyxl.load_workbook(io.BytesIO(data)).active


def test_markdown_has_sections_in_order_with_numbered_steps():
    md = to_markdown(_report())

    assert md.startswith("# Checkout freezes when paying with an expired card\n")
    assert "**Severity:** Major · **Priority:** High · **Module:** Checkout" in md
    assert "**Environment:** Android 15, app 3.2.0" in md
    order = [
        "## Preconditions",
        "## Steps to Reproduce",
        "## Expected Result",
        "## Actual Result",
        "## Test Data",
        "## Related Test Case",
        "## Open Questions",
    ]
    positions = [md.index(heading) for heading in order]
    assert positions == sorted(positions)
    assert "1. Open the cart\n2. Tap Pay\n3. Enter an expired card" in md
    assert "- Does it happen on iOS?" in md


def test_markdown_leaves_out_empty_optional_sections():
    md = to_markdown(
        _report(environment="", preconditions="", test_data="", related_test_id="", open_questions=[])
    )

    for heading in ("## Preconditions", "## Test Data", "## Related Test Case", "## Open Questions"):
        assert heading not in md
    assert "**Environment:**" not in md
    assert "## Expected Result" in md


def test_markdown_escapes_user_markdown():
    md = to_markdown(
        _report(
            title="Error `null`\nshown",
            actual_result="# Not a heading\n- not a list\n1. not a list",
            steps_to_reproduce=["> quote", "Use `code`"],
        )
    )

    assert md.startswith("# Error \\`null\\` shown\n")
    assert "\\# Not a heading\n\\- not a list\n1\\. not a list" in md
    assert "1. \\> quote\n2. Use \\`code\\`" in md


def test_missing_required_fields_names_blank_fields_in_display_order():
    report = _report(title=" ", expected_result="", steps_to_reproduce=["", "  "])

    assert missing_required_fields(report) == ["Title", "Steps to reproduce", "Expected result"]
    assert missing_required_fields(_report()) == []


def test_excel_has_headers_one_row_per_report_and_severity_fill():
    sheet = _sheet(to_excel([_report(), _report(title="Second", severity="Trivial")]))

    headers = [cell.value for cell in sheet[1]]
    assert headers[:4] == ["Title", "Module", "Severity", "Priority"]
    assert "Steps to Reproduce" in headers
    assert sheet.max_row == 3
    steps_col = headers.index("Steps to Reproduce") + 1
    assert sheet.cell(row=2, column=steps_col).value == "1. Open the cart\n2. Tap Pay\n3. Enter an expired card"
    severity_col = headers.index("Severity") + 1
    assert sheet.cell(row=2, column=severity_col).fill.start_color.rgb.endswith("FFC7CE")
    assert sheet.cell(row=3, column=severity_col).fill.start_color.rgb.endswith("C6EFCE")


def test_excel_keeps_formula_like_text_literal():
    sheet = _sheet(to_excel([_report(actual_result="=SUM(A1:A2)", test_data="=1+1")]))

    values = [cell.value for cell in sheet[2]]
    assert "=SUM(A1:A2)" in values
    assert all(cell.data_type == "s" for cell in sheet[2] if isinstance(cell.value, str))


def test_markdown_and_excel_keep_non_ascii_text():
    report = _report(title="Ứng dụng bị treo khi thanh toán", actual_result="Không hiện thông báo lỗi")

    assert "# Ứng dụng bị treo khi thanh toán" in to_markdown(report)
    sheet = _sheet(to_excel([report]))
    assert sheet.cell(row=2, column=1).value == "Ứng dụng bị treo khi thanh toán"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_exporters.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'core.bug_exporters'`.

- [ ] **Step 3: Implement the exporters**

Create `core/bug_exporters.py`:

```python
"""
Tracker-neutral exports for bug reports: Markdown for pasting into
GitHub, GitLab, Azure DevOps or Jira Cloud, and Excel for sharing a set.
"""
import io
import re

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

REQUIRED_FIELD_LABELS = {
    "title": "Title",
    "module": "Module",
    "steps_to_reproduce": "Steps to reproduce",
    "expected_result": "Expected result",
    "actual_result": "Actual result",
}

COLUMNS = [
    ("title", "Title", 40),
    ("module", "Module", 14),
    ("severity", "Severity", 11),
    ("priority", "Priority", 10),
    ("environment", "Environment", 22),
    ("preconditions", "Preconditions", 25),
    ("steps_to_reproduce", "Steps to Reproduce", 45),
    ("expected_result", "Expected Result", 30),
    ("actual_result", "Actual Result", 30),
    ("test_data", "Test Data", 20),
    ("related_test_id", "Related Test ID", 16),
    ("open_questions", "Open Questions", 35),
]

SEVERITY_COLORS = {
    "Critical": "FF9999",
    "Major": "FFC7CE",
    "Minor": "FFEB9C",
    "Trivial": "C6EFCE",
}

# Characters that start a Markdown block when they open a line.
_BLOCK_START = re.compile(r"^(\s*)([#>*+\-])", re.MULTILINE)
_ORDERED_START = re.compile(r"^(\s*\d+)([.)])", re.MULTILINE)


def _escape(text: str) -> str:
    text = text.replace("\\", "\\\\").replace("`", "\\`")
    text = _BLOCK_START.sub(r"\1\\\2", text)
    return _ORDERED_START.sub(r"\1\\\2", text)


def _steps(report: dict) -> list[str]:
    return [step.strip() for step in report.get("steps_to_reproduce", []) if step.strip()]


def missing_required_fields(report: dict) -> list[str]:
    missing = []
    for key, label in REQUIRED_FIELD_LABELS.items():
        if key == "steps_to_reproduce":
            if not _steps(report):
                missing.append(label)
        elif not str(report.get(key, "")).strip():
            missing.append(label)
    return missing


def to_markdown(report: dict) -> str:
    title = " ".join(str(report.get("title", "")).split())
    meta = [
        f"**Severity:** {report.get('severity', '')}",
        f"**Priority:** {report.get('priority', '')}",
        f"**Module:** {_escape(report.get('module', ''))}",
    ]
    if report.get("environment", "").strip():
        meta.append(f"**Environment:** {_escape(report['environment'].strip())}")

    lines = [f"# {_escape(title)}", "", " · ".join(meta)]

    def section(heading: str, body: str) -> None:
        if body.strip():
            lines.extend(["", f"## {heading}", "", body.strip()])

    section("Preconditions", _escape(report.get("preconditions", "")))
    section(
        "Steps to Reproduce",
        "\n".join(f"{number}. {_escape(step)}" for number, step in enumerate(_steps(report), start=1)),
    )
    section("Expected Result", _escape(report.get("expected_result", "")))
    section("Actual Result", _escape(report.get("actual_result", "")))
    section("Test Data", _escape(report.get("test_data", "")))
    section("Related Test Case", _escape(report.get("related_test_id", "")))
    section(
        "Open Questions",
        "\n".join(f"- {_escape(q)}" for q in report.get("open_questions", []) if q.strip()),
    )
    return "\n".join(lines) + "\n"


def _cell_value(report: dict, key: str) -> str:
    if key == "steps_to_reproduce":
        return "\n".join(f"{number}. {step}" for number, step in enumerate(_steps(report), start=1))
    if key == "open_questions":
        return "\n".join(f"- {q}" for q in report.get("open_questions", []) if q.strip())
    return str(report.get(key, ""))


def to_excel(reports: list[dict]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Bug Reports"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    wrap = Alignment(wrap_text=True, vertical="top")

    for col_idx, (_, header, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    for row_idx, report in enumerate(reports, start=2):
        for col_idx, (key, _, _) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=_cell_value(report, key))
            # Report text is text even when it starts with '='.
            cell.data_type = "s"
            cell.alignment = wrap
            color = SEVERITY_COLORS.get(report.get("severity", "")) if key == "severity" else None
            if color:
                cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")

    ws.freeze_panes = "A2"
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_exporters.py -q`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add core/bug_exporters.py tests/test_bug_exporters.py
git commit -m "feat: export bug reports as Markdown and Excel"
```

---

### Task 3: Bug Reporter page

**Files:**
- Create: `pages/2_Bug_Reporter.py`
- Test: `tests/test_bug_reporter_page.py`

**Interfaces:**
- Consumes: `AIClient.write_bug_report` (Task 1); `BUG_REPORT_PROMPT_PATH`, `build_system_prompt`, `list_available_configs`, `load_project_config`, `ProjectConfigError` (`core.prompt_builder`); `missing_required_fields`, `to_markdown`, `to_excel` (Task 2).
- Produces: widget keys used by tests — `bug_project_select`, `bug_notes`, `bug_related_case`, `write_bug_btn`, `bug_title`, `bug_module`, `bug_severity`, `bug_priority`, `bug_environment`, `bug_preconditions`, `bug_steps`, `bug_expected_result`, `bug_actual_result`, `bug_test_data`, `bug_related_test_id`, `download_bug_md`, `download_bug_xlsx`; session keys `bug_report`, `bug_usage`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bug_reporter_page.py`:

```python
"""Integration tests for pages/2_Bug_Reporter.py using Streamlit AppTest."""
from pathlib import Path
from unittest.mock import patch

import streamlit as st
from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient

PAGE_PATH = Path(__file__).parent.parent / "pages" / "2_Bug_Reporter.py"


def _fake_result(**overrides):
    report = {
        "title": "Checkout freezes when paying with an expired card",
        "module": "Checkout",
        "severity": "Major",
        "priority": "High",
        "environment": "",
        "preconditions": "Logged in with one item in the cart",
        "steps_to_reproduce": ["Open the cart", "Tap Pay"],
        "expected_result": "An 'expired card' error is shown",
        "actual_result": "The app freezes",
        "test_data": "",
        "related_test_id": "",
        "open_questions": ["Which app version?"],
    }
    report.update(overrides)
    return {"report": report, "usage": {"model": "claude-sonnet-5", "estimated_cost_usd": 0.0012,
                                        "input_tokens": 100, "output_tokens": 50}}


def _write(at, notes="pay with expired card -> freeze", related="", result=None):
    at.text_area(key="bug_notes").set_value(notes).run(timeout=30)
    if related:
        at.text_area(key="bug_related_case").set_value(related).run(timeout=30)
    captured = {}

    def _fake(system_prompt, notes_arg, related_arg=None):
        captured.update(system_prompt=system_prompt, notes=notes_arg, related=related_arg)
        return result or _fake_result()

    with patch.object(AIClient, "write_bug_report", side_effect=_fake):
        at.button(key="write_bug_btn").click().run(timeout=30)
    return captured


def _new_page(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)
    return at


def test_button_disabled_until_notes_are_entered(monkeypatch):
    at = _new_page(monkeypatch)

    assert not at.exception
    assert at.button(key="write_bug_btn").disabled is True
    assert any("notes" in info.value for info in at.info)


def test_writing_a_report_fills_the_fields_and_preview(monkeypatch):
    at = _new_page(monkeypatch)

    captured = _write(at)

    assert not at.exception
    assert "Never invent steps" in captured["system_prompt"]
    assert captured["notes"] == "pay with expired card -> freeze"
    assert at.text_input(key="bug_title").value == "Checkout freezes when paying with an expired card"
    assert at.selectbox(key="bug_severity").value == "Major"
    assert at.text_area(key="bug_steps").value == "Open the cart\nTap Pay"
    assert any("Which app version?" in w.value for w in at.warning)
    assert any("## Steps to Reproduce" in code.value for code in at.code)


def test_ai_error_is_shown(monkeypatch):
    at = _new_page(monkeypatch)
    at.text_area(key="bug_notes").set_value("notes").run(timeout=30)

    with patch.object(AIClient, "write_bug_report", side_effect=ValueError("Invalid API key.")):
        at.button(key="write_bug_btn").click().run(timeout=30)

    assert any("Invalid API key." in e.value for e in at.error)
    assert "bug_report" not in at.session_state


def test_clearing_a_required_field_disables_downloads(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)

    calls = []
    real_download_button = st.download_button

    def _spy(*args, **kwargs):
        calls.append((kwargs.get("key"), kwargs.get("disabled")))
        return real_download_button(*args, **kwargs)

    with patch.object(st, "download_button", _spy):
        at.text_input(key="bug_title").set_value("").run(timeout=30)

    assert any("Title" in e.value for e in at.error)
    assert ("download_bug_md", True) in calls
    assert ("download_bug_xlsx", True) in calls


def test_second_report_replaces_edited_fields(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)
    at.text_input(key="bug_title").set_value("My edited title").run(timeout=30)

    _write(at, notes="login button does nothing", result=_fake_result(title="Login button does nothing",
                                                                       steps_to_reproduce=["Tap Login"]))

    assert at.text_input(key="bug_title").value == "Login button does nothing"
    assert at.text_area(key="bug_steps").value == "Tap Login"


def test_related_case_json_is_parsed_and_text_is_kept(monkeypatch):
    at = _new_page(monkeypatch)
    captured = _write(at, related='{"test_id": "TC_PAY_003", "title": "Pay with expired card"}')
    assert captured["related"] == {"test_id": "TC_PAY_003", "title": "Pay with expired card"}

    at = _new_page(monkeypatch)
    captured = _write(at, related="TC_PAY_003 | Pay with expired card")
    assert captured["related"] == "TC_PAY_003 | Pay with expired card"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_reporter_page.py -q`
Expected: failures — AppTest cannot find `pages/2_Bug_Reporter.py`.

- [ ] **Step 3: Implement the page**

Create `pages/2_Bug_Reporter.py`:

```python
"""
Bug Reporter — turns a tester's rough notes about one defect into a
structured bug report, editable here and exported as Markdown or Excel.
"""
import json
import re
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.bug_exporters import missing_required_fields, to_excel, to_markdown
from core.prompt_builder import (
    BUG_REPORT_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_project_config,
)

load_dotenv()

CONFIGS_DIR = Path("configs")
SEVERITIES = ["Critical", "Major", "Minor", "Trivial"]
PRIORITIES = ["High", "Medium", "Low"]
TEXT_FIELDS = [
    "title", "module", "environment", "preconditions",
    "expected_result", "actual_result", "test_data", "related_test_id",
]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.set_page_config(page_title="Bug Reporter — AI Test Case Generator", page_icon="🐞", layout="wide")
st.title("🐞 Bug Reporter")
st.caption("Turn rough notes about a defect into a complete bug report you can paste into any tracker.")

# Streamlit renders each page's sidebar separately; without this block the
# page is a dead end when opened first with no ANTHROPIC_API_KEY set.
with st.sidebar:
    st.header("⚙️ Configuration")
    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.session_state.get("api_key", ""),
        help="Can be left blank if the ANTHROPIC_API_KEY environment variable is already set",
    )
    if api_key:
        st.session_state["api_key"] = api_key
        st.caption(
            "⚠️ The API key entered here is only kept in this browser session's "
            "memory (never written to disk). If this app is deployed publicly, "
            "set the `ANTHROPIC_API_KEY` environment variable on the server "
            "instead of typing it in here."
        )


def _related_context(text: str) -> dict | str | None:
    """A pasted JSON object is sent as data; anything else is sent as text."""
    text = text.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    return value if isinstance(value, dict) else text


def _load_report(report: dict) -> None:
    # Overwrite every widget value so edits to a previous report never leak.
    st.session_state["bug_report"] = report
    for field in TEXT_FIELDS:
        st.session_state[f"bug_{field}"] = report[field]
    st.session_state["bug_severity"] = report["severity"]
    st.session_state["bug_priority"] = report["priority"]
    st.session_state["bug_steps"] = "\n".join(report["steps_to_reproduce"])


def _current_report() -> dict:
    report = {field: st.session_state[f"bug_{field}"] for field in TEXT_FIELDS}
    report["severity"] = st.session_state["bug_severity"]
    report["priority"] = st.session_state["bug_priority"]
    report["steps_to_reproduce"] = [
        line.strip() for line in st.session_state["bug_steps"].splitlines() if line.strip()
    ]
    report["open_questions"] = st.session_state["bug_report"]["open_questions"]
    return report


def _file_stem(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:50]
    return f"bug_{slug}" if slug else "bug_report"


configs = list_available_configs(CONFIGS_DIR)
if not configs:
    st.error("No project configs found in configs/. Add one from configs/_template.yaml.")
    st.stop()

project = st.selectbox("Project", configs, key="bug_project_select")
notes = st.text_area(
    "What went wrong? Rough notes are fine.",
    key="bug_notes",
    height=160,
    placeholder="Tapping Pay with an expired card freezes the app, no error shown",
)
related = st.text_area(
    "Related test case (optional)",
    key="bug_related_case",
    height=100,
    help="Paste the test case as JSON or as plain text; it is context for the AI.",
)

if not notes.strip():
    st.info("Enter your notes above to write a bug report.")

if st.button("🐞 Write bug report", key="write_bug_btn", disabled=not notes.strip()):
    try:
        config = load_project_config(CONFIGS_DIR / f"{project}.yaml")
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except (ProjectConfigError, ValueError) as e:
        st.error(str(e))
        st.stop()

    system_prompt = build_system_prompt(config, base_prompt_path=BUG_REPORT_PROMPT_PATH)
    with st.status("Writing the bug report...", expanded=False) as status:
        try:
            result = client.write_bug_report(system_prompt, notes, _related_context(related))
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Error calling the AI: {e}")
            st.stop()
        status.update(label="Done", state="complete")
    _load_report(result["report"])
    st.session_state["bug_usage"] = result["usage"]

if "bug_report" in st.session_state:
    st.subheader("✏️ Bug report")
    questions = st.session_state["bug_report"]["open_questions"]
    if questions:
        st.warning(
            "The AI needs more information before this report is complete:\n\n"
            + "\n".join(f"- {q}" for q in questions)
        )

    st.text_input("Title", key="bug_title")
    col_module, col_severity, col_priority = st.columns(3)
    col_module.text_input("Module", key="bug_module")
    col_severity.selectbox("Severity", SEVERITIES, key="bug_severity")
    col_priority.selectbox("Priority", PRIORITIES, key="bug_priority")
    st.text_input("Environment", key="bug_environment")
    st.text_area("Preconditions", key="bug_preconditions")
    st.text_area("Steps to reproduce (one per line)", key="bug_steps")
    st.text_area("Expected result", key="bug_expected_result")
    st.text_area("Actual result", key="bug_actual_result")
    st.text_input("Test data", key="bug_test_data")
    st.text_input("Related test ID", key="bug_related_test_id")

    report = _current_report()
    missing = missing_required_fields(report)
    if missing:
        st.error("Fill in the required field(s) before exporting: " + ", ".join(missing))

    markdown = to_markdown(report)
    st.markdown("**Markdown preview** — use the copy button in the corner of the block.")
    st.code(markdown, language="markdown")

    stem = _file_stem(report["title"])
    col_md, col_xlsx = st.columns(2)
    # Call st.download_button (not col.download_button) so tests can spy on it, as the Reviewer's do.
    with col_md:
        st.download_button(
            "⬇️ Download .md", markdown.encode("utf-8"), f"{stem}.md", "text/markdown",
            key="download_bug_md", disabled=bool(missing),
        )
    with col_xlsx:
        st.download_button(
            "⬇️ Download .xlsx", to_excel([report]), f"{stem}.xlsx", XLSX_MIME,
            key="download_bug_xlsx", disabled=bool(missing),
        )

    usage = st.session_state.get("bug_usage", {})
    if usage:
        cost = usage.get("estimated_cost_usd")
        st.caption(
            f"Model: {usage.get('model', 'N/A')} · input {usage.get('input_tokens', 0):,} tokens"
            f" · output {usage.get('output_tokens', 0):,} tokens · estimated cost "
            + (f"${cost:.6f}" if cost is not None else "N/A")
        )
```

- [ ] **Step 4: Run the page tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_reporter_page.py -q`
Expected: 6 passed.

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass, 0 failures.

- [ ] **Step 6: Try the page by hand**

Run: `.venv/Scripts/python.exe -m streamlit run app.py --server.headless true --server.port 8599`, open `http://localhost:8599/Bug_Reporter`, and check the page renders with the button disabled and the hint visible (no API call is needed for this check). Stop the server afterwards.

- [ ] **Step 7: Commit**

```bash
git add pages/2_Bug_Reporter.py tests/test_bug_reporter_page.py
git commit -m "feat: add the Bug Reporter page"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: page name "Bug Reporter" and exports from Tasks 2–3.
- Produces: none.

- [ ] **Step 1: Update README**

In the Architecture block, replace `Generator or Reviewer workflow` with `Generator, Reviewer or Bug Reporter workflow` and `Project-aware test cases and coverage reports` with `Project-aware test cases, coverage reports and bug reports`.

In Directory structure, after the `1_Reviewer.py` line add:

```
│   └── 2_Bug_Reporter.py        # Bug reports from rough notes, Markdown/Excel export
```

and change the `1_Reviewer.py` line's prefix from `└──` to `├──`. After the `excel_exporter.py` line add `│   ├── bug_exporters.py          # Bug report Markdown/Excel export` (switch the previous last item's `└──` to `├──` so the tree stays valid). In `prompts/` add `│   ├── bug_report_system_prompt.md # Writes one bug report from notes`. Change `# pytest (core logic + both Streamlit pages)` to `# pytest (core logic + all Streamlit pages)`.

After the "Review coverage" section (after the live Reviewer link paragraph) add:

```markdown
### Write a bug report

1. Open **Bug Reporter** in Streamlit's page navigation
2. Select a project and paste your rough notes about the defect; optionally
   paste the related test case (JSON or plain text)
3. Click **Write bug report**; answer any open questions the AI lists
4. Edit the fields, then copy the Markdown or download `.md`/`.xlsx`

The Markdown pastes into GitHub, GitLab, Azure DevOps and Jira Cloud.
```

In Roadmap replace the Phase 3 line with:

```markdown
- [x] Phase 3, step 1: Bug Report Writer with tracker-neutral Markdown/Excel export
- [ ] Phase 3, step 2: Bug reports from the failed rows of an executed test run
```

- [ ] **Step 2: Update CHANGELOG**

Insert after `# Changelog`:

```markdown

## Unreleased

- Add the Bug Reporter page: turn rough notes about a defect into a structured bug report
  (severity, priority, steps, expected/actual, open questions), edit it, and export it as
  Markdown or Excel. The AI asks for missing details instead of inventing them.
```

- [ ] **Step 3: Verify and commit**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass.

```bash
git add README.md CHANGELOG.md
git commit -m "docs: document the Bug Reporter"
```
