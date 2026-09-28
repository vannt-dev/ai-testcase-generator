# Batch Bug Reports and Standards Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align bug reports with ISTQB / ISO/IEC/IEEE 29119-3 defect report content (reproducibility, build/version, source) and add a "From a test run" tab that writes one bug report per failed row of an uploaded test run.

**Architecture:** The one-bug core from step 1 gains two fields. A new `core/bug_batch.py` holds the batch logic (failed-value detection, row filtering, the per-row loop with error collection and usage sums, summary edits, combined Markdown), testable without Streamlit. `pages/2_Bug_Reporter.py` becomes two tabs, each rendered by its own function so an error in one tab never hides the other.

**Tech Stack:** Python 3.10+, Streamlit (`AppTest`), Anthropic SDK 1.x structured outputs, Pydantic v2, openpyxl, pandas, pytest.

**Spec:** `docs/superpowers/specs/2026-09-28-batch-bug-reports-design.md` (step 1 spec: `docs/superpowers/specs/2026-09-28-bug-report-writer-design.md`)

## Global Constraints

- Run tests with `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` (Windows). 140 tests pass before this plan.
- No test calls the real Anthropic API.
- Reproducibility values exactly `Always`, `Intermittent`, `Once`, `Unknown`. Severity `Critical`/`Major`/`Minor`/`Trivial`; priority `High`/`Medium`/`Low`.
- Default failed values come from `{"fail", "failed", "failure", "ng", "ko dat", "khong dat"}` after normalization; `x` is not one of them.
- At most 50 failed rows per batch run (`MAX_BATCH_ROWS = 50`).
- Excel strings stay literal text; control characters are stripped (existing `to_excel` behaviour).
- English source, comments, commits and docs; Conventional Commits; no `Co-Authored-By`/`Claude-Session` trailers; stage files explicitly.
- Branch `feat/batch-bug-reports` (exists; the spec is committed there).
- Several files use CRLF line endings; edit them with an editor that preserves them.

## Review Focus

1. Changing the mapped status column after values were selected — the failed-value selector must not raise and must show the new column's values.
2. Uploading a second file after a batch run — the old batch results must disappear.
3. A status cell with surrounding spaces or different case (" failed ", "FAILED") — still counts as failed when "failed"-like values are selected.
4. An error message shown for a failed row names the file row number the user can find, not an index among failed rows.
5. Every row fails — no downloads, a clear error.

Tests pinning each line: 1 → Task 3 `test_run_changing_status_column_resets_failed_values`; 2 → Task 3 `test_run_new_upload_clears_previous_results`; 3 → Task 2 `test_default_failed_values_normalizes_case_spaces_and_diacritics` + `test_failed_rows_matches_stripped_status`; 4 → Task 2 `test_write_reports_continues_after_a_failing_row`; 5 → Task 3 `test_run_all_rows_failing_shows_error_without_downloads`.

Ruling recorded here: the spec's error `row` was "index among failed rows"; the plan uses the file row number (the same number as `source`), which is what a user can find in the file. The spec is updated in Task 2.

---

### Task 1: Standards alignment of the one-bug core

**Files:**
- Modify: `core/ai_client.py` (`BugReport`)
- Modify: `prompts/bug_report_system_prompt.md`
- Modify: `core/bug_exporters.py` (`COLUMNS`, `to_markdown`)
- Modify: `pages/2_Bug_Reporter.py` (draft fields and form)
- Test: `tests/test_ai_client.py`, `tests/test_ai_client_schemas.py`, `tests/test_prompt_builder.py`, `tests/test_bug_exporters.py`, `tests/test_bug_reporter_page.py`

**Interfaces:**
- Produces: `BugReport` with `reproducibility: Literal["Always","Intermittent","Once","Unknown"]` and `build_version: str` after `priority`; exporters read optional `report.get("source", "")`; page widget keys `bug_build_version`, `bug_reproducibility`.

- [ ] **Step 1: Update fixtures and write failing tests**

In `tests/test_ai_client.py` `VALID_BUG`, add after `"priority": "High",`:
```python
        "reproducibility": "Always",
        "build_version": "",
```
In `tests/test_ai_client_schemas.py` `_bug_payload`, add after `"priority": "High",`:
```python
        "reproducibility": "Unknown",
        "build_version": "",
```
and add `{"reproducibility": "Sometimes"},` to the `test_bug_report_rejects_invalid_values` parametrize list.

In `tests/test_prompt_builder.py` `test_build_system_prompt_for_bug_reports_includes_rules_and_project`, add:
```python
    assert "reproducibility" in prompt
    assert "build_version" in prompt
```

In `tests/test_bug_exporters.py` `_report`, replace `"environment": "Android 15, app 3.2.0",` with:
```python
        "reproducibility": "Always",
        "build_version": "3.2.0",
        "environment": "Android 15",
```
In `test_markdown_has_sections_in_order_with_numbered_steps`, replace the two meta assertions with:
```python
    assert (
        "**Severity:** Major · **Priority:** High · **Reproducibility:** Always · "
        "**Module:** Checkout · **Build:** 3.2.0 · **Environment:** Android 15"
    ) in md
```
In `test_markdown_leaves_out_empty_optional_sections`, call `_report(...)` with `build_version=""` added and assert `"**Build:**" not in md` and `"**Source:**" not in md`. Append:
```python
def test_markdown_and_excel_show_the_source_when_present():
    report = _report(source="run.xlsx, row 7")

    assert "**Source:** run.xlsx, row 7" in to_markdown(report)
    sheet = _sheet(to_excel([report]))
    headers = [cell.value for cell in sheet[1]]
    assert headers[-1] == "Source"
    assert sheet.cell(row=2, column=len(headers)).value == "run.xlsx, row 7"
    assert headers[headers.index("Priority") + 1] == "Reproducibility"
    assert headers[headers.index("Environment") - 1] == "Build / Version"
```

In `tests/test_bug_reporter_page.py` `_fake_result`, add after `"priority": "High",`:
```python
        "reproducibility": "Always",
        "build_version": "3.2.0",
```
and append:
```python
def test_notes_form_shows_and_exports_reproducibility_and_build(monkeypatch):
    at = _new_page(monkeypatch)
    _write(at)

    assert at.text_input(key="bug_build_version").value == "3.2.0"
    assert at.selectbox(key="bug_reproducibility").value == "Always"
    at.selectbox(key="bug_reproducibility").set_value("Intermittent").run(timeout=30)
    assert any("**Reproducibility:** Intermittent" in code.value for code in at.code)
    assert any("**Build:** 3.2.0" in code.value for code in at.code)
```

- [ ] **Step 2: Run to verify the failures**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: failures in the schema test (`Sometimes` accepted), prompt test, exporter tests and the new page test (`KeyError`/missing widget).

- [ ] **Step 3: Implement**

`core/ai_client.py` — in `BugReport`, after `priority`:
```python
    reproducibility: Literal["Always", "Intermittent", "Once", "Unknown"]
    build_version: str
```

`prompts/bug_report_system_prompt.md` — after rule 8 add:
```
9. "build_version": the app or build version only when the notes or the
   related test case state it; otherwise an empty string and a question in
   "open_questions".
10. "reproducibility": Always, Intermittent or Once only when the notes say
    how often it happens (e.g. "every time", "sometimes", "happened once");
    otherwise Unknown and a question in "open_questions".
```
and change the output field list to: `title, module, severity, priority, reproducibility (Always | Intermittent | Once | Unknown), build_version, environment, preconditions, steps_to_reproduce (array of strings), expected_result, actual_result, test_data, related_test_id, open_questions (array of strings).`

`core/bug_exporters.py`:
- `COLUMNS`: insert `("reproducibility", "Reproducibility", 14),` after the priority entry, `("build_version", "Build / Version", 16),` before the environment entry, and append `("source", "Source", 28),`.
- In `to_markdown`, build the meta list as:
```python
    meta = [
        f"**Severity:** {report.get('severity', '')}",
        f"**Priority:** {report.get('priority', '')}",
    ]
    if report.get("reproducibility", "").strip():
        meta.append(f"**Reproducibility:** {report['reproducibility'].strip()}")
    meta.append(f"**Module:** {_escape(report.get('module', ''))}")
    if report.get("build_version", "").strip():
        meta.append(f"**Build:** {_escape(report['build_version'].strip())}")
    if report.get("environment", "").strip():
        meta.append(f"**Environment:** {_escape(report['environment'].strip())}")
```
  and after `lines = [f"# {heading}", "", " · ".join(meta)]` add (a blank line first, so Source renders as its own paragraph):
```python
    if report.get("source", "").strip():
        lines.extend(["", f"**Source:** {_escape(report['source'].strip())}"])
```

`pages/2_Bug_Reporter.py`:
- Add `REPRODUCIBILITY = ["Always", "Intermittent", "Once", "Unknown"]` after `PRIORITIES`.
- In `TEXT_FIELDS` add `"build_version"` after `"module"`.
- In `_load_report` add `draft["reproducibility"] = report["reproducibility"]` after the priority line; in `_current_report` add `report["reproducibility"] = draft["reproducibility"]`.
- In the form, after the module/severity/priority row add:
```python
    col_repro, col_build = st.columns(2)
    col_repro.selectbox("Reproducibility", REPRODUCIBILITY, key="bug_reproducibility")
    col_build.text_input("Build / version", key="bug_build_version")
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`
Expected: all pass (140 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add core/ai_client.py prompts/bug_report_system_prompt.md core/bug_exporters.py pages/2_Bug_Reporter.py tests/test_ai_client.py tests/test_ai_client_schemas.py tests/test_prompt_builder.py tests/test_bug_exporters.py tests/test_bug_reporter_page.py
git commit -m "feat: add reproducibility, build version and source to bug reports"
```

---

### Task 2: Batch logic and run column mapping prompt

**Files:**
- Create: `core/bug_batch.py`
- Create: `prompts/run_column_mapping_system_prompt.md`
- Modify: `core/prompt_builder.py` (path + loader)
- Modify: `docs/superpowers/specs/2026-09-28-batch-bug-reports-design.md` (error row ruling)
- Test: `tests/test_bug_batch.py`, `tests/test_prompt_builder.py`

**Interfaces:**
- Consumes: `AIClient.write_bug_report(system_prompt, notes, related_test_case)` → `{"report", "usage"}`; `to_markdown`; `TEST_CASE_FIELDS`.
- Produces (all in `core.bug_batch`): `RUN_FIELDS`, `REQUIRED_RUN_FIELDS`, `MAX_BATCH_ROWS`, `SEVERITIES`, `PRIORITIES`, `distinct_values(rows, column) -> list[str]`, `default_failed_values(values) -> list[str]`, `failed_rows(rows, mapping, failed_values) -> list[dict]` (keys `row_number`, `test_case`, `actual_result`, `comment`), `notes_for_row(row) -> str`, `write_reports(client, system_prompt, rows, source_name="", on_progress=None) -> {"reports", "errors", "usage"}` (error dict keys `row`, `test_id`, `error`; `row` is the file row number), `apply_summary_edits(reports, rows) -> list[dict]`, `combined_markdown(reports) -> str`. `core.prompt_builder.RUN_COLUMN_MAPPING_PROMPT_PATH`, `load_run_column_mapping_prompt() -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_bug_batch.py`:
```python
from core.bug_batch import (
    MAX_BATCH_ROWS,
    apply_summary_edits,
    combined_markdown,
    default_failed_values,
    distinct_values,
    failed_rows,
    notes_for_row,
    write_reports,
)

MAPPING = {"status": "Status", "actual_result": "Actual", "comment": "Note", "test_id": "ID", "title": "Title"}

ROWS = [
    {"ID": "TC_1", "Title": "Pay", "Status": "Failed", "Actual": "Freezes", "Note": "on Android"},
    {"ID": "TC_2", "Title": "Login", "Status": "Passed", "Actual": "OK", "Note": None},
    {"ID": "TC_3", "Title": "Cart", "Status": " FAILED ", "Actual": "Empty cart", "Note": ""},
    {"ID": None, "Title": "Search", "Status": "Không đạt", "Actual": "No results", "Note": None},
]


def _report(title="Bug", **extra):
    report = {
        "title": title, "module": "M", "severity": "Major", "priority": "High",
        "reproducibility": "Always", "build_version": "", "environment": "", "preconditions": "",
        "steps_to_reproduce": ["Do it"], "expected_result": "E", "actual_result": "A",
        "test_data": "", "related_test_id": "", "open_questions": [],
    }
    report.update(extra)
    return report


class FakeClient:
    def __init__(self, fail_on=(), costs=None):
        self.fail_on = set(fail_on)
        self.costs = costs or {}
        self.calls = []

    def write_bug_report(self, system_prompt, notes, related_test_case=None):
        self.calls.append((system_prompt, notes, related_test_case))
        number = len(self.calls)
        if number in self.fail_on:
            raise ValueError(f"boom {number}")
        return {
            "report": _report(title=f"Bug {number}"),
            "usage": {"model": "claude-sonnet-5", "input_tokens": 10, "output_tokens": 5,
                      "cache_creation_input_tokens": 1, "cache_read_input_tokens": 2,
                      "estimated_cost_usd": self.costs.get(number, 0.001)},
        }


def test_distinct_values_are_non_blank_and_first_seen():
    assert distinct_values(ROWS, "Status") == ["Failed", "Passed", "FAILED", "Không đạt"]
    assert distinct_values(ROWS, "") == []


def test_default_failed_values_normalizes_case_spaces_and_diacritics():
    values = ["Passed", "Failed", "KO ĐẠT", "Không đạt", "ko dat", "Blocked", "x", "NG", "", "FAILED"]

    assert default_failed_values(values) == ["Failed", "KO ĐẠT", "Không đạt", "ko dat", "NG", "FAILED"]


def test_failed_rows_matches_stripped_status():
    rows = failed_rows(ROWS, MAPPING, ["Failed", "FAILED", "Không đạt"])

    assert [row["row_number"] for row in rows] == [1, 3, 4]
    assert rows[0] == {
        "row_number": 1,
        "test_case": {"test_id": "TC_1", "title": "Pay"},
        "actual_result": "Freezes",
        "comment": "on Android",
    }
    assert rows[2]["test_case"] == {"title": "Search"}
    assert rows[2]["comment"] == ""


def test_notes_for_row_adds_the_comment_only_when_present():
    assert notes_for_row({"actual_result": "Freezes", "comment": ""}) == (
        "Test case failed during a test run.\n\nActual result: Freezes"
    )
    assert notes_for_row({"actual_result": "Freezes", "comment": "on Android"}).endswith(
        "\n\nTester comment: on Android"
    )


def test_write_reports_continues_after_a_failing_row():
    rows = failed_rows(ROWS, MAPPING, ["Failed", "FAILED", "Không đạt"])
    client = FakeClient(fail_on={2})
    progress = []

    result = write_reports(client, "system", rows, source_name="run.xlsx",
                           on_progress=lambda done, total: progress.append((done, total)))

    assert [r["title"] for r in result["reports"]] == ["Bug 1", "Bug 3"]
    assert [r["source"] for r in result["reports"]] == ["run.xlsx, row 1", "run.xlsx, row 4"]
    assert result["errors"] == [{"row": 3, "test_id": "TC_3", "error": "boom 2"}]
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert client.calls[0][2] == {"test_id": "TC_1", "title": "Pay"}
    assert client.calls[0][1].startswith("Test case failed during a test run.")


def test_write_reports_sums_usage_and_drops_cost_when_one_is_unknown():
    rows = failed_rows(ROWS, MAPPING, ["Failed", "Không đạt"])

    known = write_reports(FakeClient(), "system", rows)["usage"]
    assert known["input_tokens"] == 20
    assert known["cache_read_input_tokens"] == 4
    assert round(known["estimated_cost_usd"], 6) == 0.002
    assert known["model"] == "claude-sonnet-5"
    assert write_reports(FakeClient(), "system", rows)["reports"][0]["source"] == "row 1"

    unknown = write_reports(FakeClient(costs={2: None}), "system", rows)["usage"]
    assert unknown["estimated_cost_usd"] is None


def test_write_reports_sends_none_when_the_row_has_no_test_case_fields():
    rows = failed_rows([{"Status": "Failed", "Actual": "x"}], {"status": "Status", "actual_result": "Actual"}, ["Failed"])
    client = FakeClient()

    write_reports(client, "system", rows)

    assert client.calls[0][2] is None


def test_apply_summary_edits_keeps_originals_for_blank_or_invalid_values():
    reports = [_report(title="A"), _report(title="B")]
    edits = [
        {"title": "A edited", "severity": "Minor", "priority": "Low"},
        {"title": "  ", "severity": "Blocker", "priority": None},
    ]

    updated = apply_summary_edits(reports, edits)

    assert (updated[0]["title"], updated[0]["severity"], updated[0]["priority"]) == ("A edited", "Minor", "Low")
    assert (updated[1]["title"], updated[1]["severity"], updated[1]["priority"]) == ("B", "Major", "High")
    assert reports[0]["title"] == "A"


def test_combined_markdown_separates_reports():
    md = combined_markdown([_report(title="One"), _report(title="Two")])

    assert md.startswith("# One\n")
    assert "\n---\n\n# Two\n" in md


def test_max_batch_rows_is_fifty():
    assert MAX_BATCH_ROWS == 50
```

Append to `tests/test_prompt_builder.py` (add `load_run_column_mapping_prompt` to its import):
```python
def test_run_column_mapping_prompt_lists_run_fields():
    prompt = load_run_column_mapping_prompt()

    for field in ("status", "actual_result", "comment", "test_id", "expected_result"):
        assert field in prompt
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_batch.py tests/test_prompt_builder.py -q -p no:cacheprovider`
Expected: collection errors — `No module named 'core.bug_batch'`, `cannot import name 'load_run_column_mapping_prompt'`.

- [ ] **Step 3: Implement**

Create `core/bug_batch.py`:
```python
"""
Batch bug reports: turn the failed rows of an executed test run into bug
reports, one write_bug_report call per row.
"""
import unicodedata
from collections.abc import Callable

from core.bug_exporters import to_markdown
from core.result_utils import TEST_CASE_FIELDS

RUN_FIELDS = ("status", "actual_result", "comment")
REQUIRED_RUN_FIELDS = ("status", "actual_result")
MAX_BATCH_ROWS = 50
SEVERITIES = ("Critical", "Major", "Minor", "Trivial")
PRIORITIES = ("High", "Medium", "Low")
# "x" is left out on purpose: many teams mark executed or passed rows with it.
FAILED_STATUS_WORDS = {"fail", "failed", "failure", "ng", "ko dat", "khong dat"}
USAGE_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _normalize(value: str) -> str:
    # NFKD splits most accented letters into base + combining mark; đ/Đ have no decomposition.
    text = unicodedata.normalize("NFKD", value.replace("đ", "d").replace("Đ", "D"))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().split())


def _cell(row: dict, column: str) -> str:
    if not column:
        return ""
    value = row.get(column)
    return "" if value is None else str(value).strip()


def distinct_values(rows: list[dict], column: str) -> list[str]:
    values = []
    for row in rows:
        value = _cell(row, column)
        if value and value not in values:
            values.append(value)
    return values


def default_failed_values(values: list[str]) -> list[str]:
    selected = []
    for value in values:
        text = "" if value is None else str(value).strip()
        if text and text not in selected and _normalize(text) in FAILED_STATUS_WORDS:
            selected.append(text)
    return selected


def failed_rows(rows: list[dict], mapping: dict[str, str], failed_values: list[str]) -> list[dict]:
    wanted = {value.strip() for value in failed_values}
    selected = []
    for number, row in enumerate(rows, start=1):
        if _cell(row, mapping.get("status", "")) not in wanted:
            continue
        test_case = {}
        for field in TEST_CASE_FIELDS:
            value = _cell(row, mapping.get(field, ""))
            if value:
                test_case[field] = value
        selected.append(
            {
                "row_number": number,
                "test_case": test_case,
                "actual_result": _cell(row, mapping.get("actual_result", "")),
                "comment": _cell(row, mapping.get("comment", "")),
            }
        )
    return selected


def notes_for_row(row: dict) -> str:
    notes = f"Test case failed during a test run.\n\nActual result: {row['actual_result']}"
    if row["comment"]:
        notes += f"\n\nTester comment: {row['comment']}"
    return notes


def _sum_usage(usages: list[dict]) -> dict:
    total = {key: sum(int(usage.get(key, 0) or 0) for usage in usages) for key in USAGE_TOKEN_KEYS}
    costs = [usage.get("estimated_cost_usd") for usage in usages]
    # One unknown price makes the total unknown rather than silently too low.
    total["estimated_cost_usd"] = None if not usages or None in costs else sum(costs)
    total["model"] = usages[0].get("model", "N/A") if usages else "N/A"
    return total


def write_reports(
    client,
    system_prompt: str,
    rows: list[dict],
    source_name: str = "",
    on_progress: Callable[[int, int], None] | None = None,
) -> dict:
    reports, errors, usages = [], [], []
    for index, row in enumerate(rows, start=1):
        try:
            result = client.write_bug_report(system_prompt, notes_for_row(row), row["test_case"] or None)
        except ValueError as error:
            errors.append(
                {"row": row["row_number"], "test_id": row["test_case"].get("test_id", ""), "error": str(error)}
            )
        else:
            report = result["report"]
            location = f"row {row['row_number']}"
            report["source"] = f"{source_name}, {location}" if source_name else location
            reports.append(report)
            usages.append(result["usage"])
        if on_progress:
            on_progress(index, len(rows))
    return {"reports": reports, "errors": errors, "usage": _sum_usage(usages)}


def apply_summary_edits(reports: list[dict], rows: list[dict]) -> list[dict]:
    """Apply title/severity/priority edits from the summary table; blank or invalid edits keep the original."""
    updated = []
    for report, row in zip(reports, rows):
        report = dict(report)
        title = str(row.get("title") or "").strip()
        if title:
            report["title"] = title
        if row.get("severity") in SEVERITIES:
            report["severity"] = row["severity"]
        if row.get("priority") in PRIORITIES:
            report["priority"] = row["priority"]
        updated.append(report)
    return updated


def combined_markdown(reports: list[dict]) -> str:
    return "\n---\n\n".join(to_markdown(report) for report in reports)
```

Create `prompts/run_column_mapping_system_prompt.md`:
```
You are helping map columns from an executed test run spreadsheet (test
cases plus the result of running them) onto a fixed target schema.

TASK:
Given the uploaded file's column headers and a few sample rows, map each
target field below to the header name in the uploaded file that most
likely contains that data. If no column plausibly matches a target field,
map it to an empty string.

TARGET FIELDS:
- status: the execution result of each test (e.g. Pass/Fail, Passed/Failed,
  Đạt/Không đạt, OK/NG)
- actual_result: what actually happened when the test ran
- comment: the tester's remarks or notes about the run (optional)
- test_id, module, title, precondition, steps, test_data,
  expected_result, priority, type, platform: the test case itself
  (optional)

Do not map "status" to a priority or type column, and do not map
"actual_result" to the expected result column.

OUTPUT FORMAT:
Respond with ONLY a single valid JSON object, no markdown code fence,
no text other than the JSON:

{
  "mapping": {
    "status": "string (uploaded column name, or empty string)",
    "actual_result": "string",
    "comment": "string",
    "test_id": "string",
    "module": "string",
    "title": "string",
    "precondition": "string",
    "steps": "string",
    "test_data": "string",
    "expected_result": "string",
    "priority": "string",
    "type": "string",
    "platform": "string"
  }
}
```

`core/prompt_builder.py` — after `BUG_REPORT_PROMPT_PATH`:
```python
RUN_COLUMN_MAPPING_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "run_column_mapping_system_prompt.md"
```
and after `load_column_mapping_prompt`:
```python
def load_run_column_mapping_prompt() -> str:
    return RUN_COLUMN_MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
```

In the spec, replace `{"row": <1-based index among failed rows>, "test_id": <test_id or "">, "error": <message>}` with `{"row": <row_number in the file>, "test_id": <test_id or "">, "error": <message>}`.

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_batch.py tests/test_prompt_builder.py -q -p no:cacheprovider`
Expected: all pass.

- [ ] **Step 5: Run the full suite, then commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → all pass.
```bash
git add core/bug_batch.py prompts/run_column_mapping_system_prompt.md core/prompt_builder.py tests/test_bug_batch.py tests/test_prompt_builder.py docs/superpowers/specs/2026-09-28-batch-bug-reports-design.md
git commit -m "feat: batch bug report logic for the failed rows of a test run"
```

---

### Task 3: Tabs and the "From a test run" tab

**Files:**
- Modify: `pages/2_Bug_Reporter.py`
- Test: `tests/test_bug_reporter_page.py`

**Interfaces:**
- Consumes: everything in `core.bug_batch` (Task 2), `load_run_column_mapping_prompt` (Task 2), `parse_uploaded_file`/`FileImportError` (`core.file_import`), `AIClient.suggest_column_mapping(system_prompt, headers, sample_rows) -> {"mapping": dict}`, `TEST_CASE_FIELDS`.
- Produces: widget keys `run_file`, `run_project_select`, `run_mapping_<field>`, `run_failed_values_<status column>`, `write_batch_btn`, `batch_editor`, `download_batch_xlsx`, `download_batch_md`; session keys `run_mapped_file_name`, `run_mapping_suggestion`, `batch_result`, `batch_project`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bug_reporter_page.py` (add `import io` and `import openpyxl` at the top):
```python
RUN_MAPPING = {
    "mapping": {
        "status": "Status", "actual_result": "Actual", "comment": "Note",
        "test_id": "ID", "title": "Title", "steps": "Steps",
        "module": "", "precondition": "", "test_data": "", "expected_result": "",
        "priority": "", "type": "", "platform": "",
    }
}
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _run_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Title", "Steps", "Status", "Actual", "Note"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


RUN_ROWS = [
    ["TC_1", "Pay", "1. Pay", "Failed", "Freezes", "on Android"],
    ["TC_2", "Login", "1. Login", "Passed", "OK", ""],
    ["TC_3", "Cart", "1. Open cart", "Không đạt", "Empty", ""],
    ["TC_4", "Search", "1. Search", "Blocked", "", ""],
]


def _upload_run(at, rows=RUN_ROWS, name="run.xlsx", mapping=RUN_MAPPING):
    with patch.object(AIClient, "suggest_column_mapping", return_value=mapping):
        at.file_uploader(key="run_file").upload(name, _run_xlsx(rows), XLSX).run(timeout=30)


def test_run_upload_preselects_failed_values_and_counts_rows(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)

    assert not at.exception
    assert at.multiselect(key="run_failed_values_Status").value == ["Failed", "Không đạt"]
    assert any("**2** failed row(s)" in m.value for m in at.markdown)
    assert at.button(key="write_batch_btn").disabled is False


def test_run_button_disabled_until_status_is_mapped(monkeypatch):
    at = _new_page(monkeypatch)
    mapping = {"mapping": dict(RUN_MAPPING["mapping"], status="")}
    _upload_run(at, mapping=mapping)

    assert any("status" in w.value for w in at.warning)
    assert at.button(key="write_batch_btn").disabled is True


def test_run_changing_status_column_resets_failed_values(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)

    at.selectbox(key="run_mapping_status").select("Note").run(timeout=30)

    assert not at.exception
    assert at.multiselect(key="run_failed_values_Note").value == []


def test_run_writes_reports_and_lists_errors(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)
    responses = [_fake_result(title="Pay freezes"), ValueError("boom")]

    calls = []
    real_download_button = st.download_button

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("key"))
        return real_download_button(*args, **kwargs)

    with patch.object(AIClient, "write_bug_report", side_effect=responses), \
         patch.object(st, "download_button", _spy):
        at.button(key="write_batch_btn").click().run(timeout=30)

    assert not at.exception
    result = at.session_state["batch_result"]
    assert [r["source"] for r in result["reports"]] == ["run.xlsx, row 1"]
    assert result["errors"] == [{"row": 3, "test_id": "TC_3", "error": "boom"}]
    assert any("Row 3 (TC_3): boom" in e.value for e in at.error)
    assert "download_batch_xlsx" in calls and "download_batch_md" in calls


def test_run_all_rows_failing_shows_error_without_downloads(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)

    calls = []
    real_download_button = st.download_button

    def _spy(*args, **kwargs):
        calls.append(kwargs.get("key"))
        return real_download_button(*args, **kwargs)

    with patch.object(AIClient, "write_bug_report", side_effect=ValueError("down")), \
         patch.object(st, "download_button", _spy):
        at.button(key="write_batch_btn").click().run(timeout=30)

    assert any("No bug reports were written" in e.value for e in at.error)
    assert "download_batch_xlsx" not in calls


def test_run_over_the_limit_disables_the_button(monkeypatch):
    at = _new_page(monkeypatch)
    rows = [[f"TC_{i}", "T", "S", "Failed", "A", ""] for i in range(51)]
    _upload_run(at, rows=rows)

    assert at.button(key="write_batch_btn").disabled is True
    assert any("limit is 50" in e.value for e in at.error)


def test_run_new_upload_clears_previous_results(monkeypatch):
    at = _new_page(monkeypatch)
    _upload_run(at)
    with patch.object(AIClient, "write_bug_report", return_value=_fake_result()):
        at.button(key="write_batch_btn").click().run(timeout=30)
    assert "batch_result" in at.session_state

    _upload_run(at, name="run2.xlsx")

    assert "batch_result" not in at.session_state
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_reporter_page.py -q -p no:cacheprovider`
Expected: the 7 new tests fail (`KeyError`/missing `run_file` widget); the existing tests pass.

- [ ] **Step 3: Implement — rewrite the page as two tabs**

Replace the module body of `pages/2_Bug_Reporter.py` from the imports through the end so it reads as follows. Everything from Task 1 (`REPRODUCIBILITY`, `build_version`, the reproducibility/build form row) is kept; the notes flow moves into `_render_notes_tab` with `st.stop()` replaced by `return`.

Imports (replace the import block):
```python
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.bug_batch import (
    MAX_BATCH_ROWS,
    REQUIRED_RUN_FIELDS,
    RUN_FIELDS,
    apply_summary_edits,
    combined_markdown,
    default_failed_values,
    distinct_values,
    failed_rows,
    write_reports,
)
from core.bug_exporters import file_stem, missing_required_fields, to_excel, to_markdown
from core.file_import import FileImportError, parse_uploaded_file
from core.prompt_builder import (
    BUG_REPORT_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_project_config,
    load_run_column_mapping_prompt,
)
from core.result_utils import TEST_CASE_FIELDS
```

Add after `_current_report`:
```python
def _usage_caption(usage: dict) -> None:
    if not usage:
        return
    cost = usage.get("estimated_cost_usd")
    st.caption(
        f"Model: {usage.get('model', 'N/A')} · input {usage.get('input_tokens', 0):,} tokens"
        f" · output {usage.get('output_tokens', 0):,} tokens · estimated cost "
        + (f"${cost:.6f}" if cost is not None else "N/A")
    )
```

Wrap the existing notes flow (from `project = st.selectbox("Project", configs, key="bug_project_select")` to the end of the file) in `def _render_notes_tab(configs: list[str]) -> None:`, indent it one level, replace both `st.stop()` calls with `return`, and replace the trailing usage block with `_usage_caption(st.session_state.get("bug_usage", {}))`.

Add the run tab:
```python
def _render_batch_result() -> None:
    result = st.session_state["batch_result"]
    for error in result["errors"]:
        label = f"Row {error['row']}" + (f" ({error['test_id']})" if error["test_id"] else "")
        st.error(f"{label}: {error['error']}")
    if not result["reports"]:
        st.error("No bug reports were written. Check the errors above and try again.")
        return

    st.subheader(f"✏️ {len(result['reports'])} bug report(s)")
    summary = pd.DataFrame(
        [
            {
                "#": number,
                "related_test_id": report["related_test_id"],
                "title": report["title"],
                "severity": report["severity"],
                "priority": report["priority"],
            }
            for number, report in enumerate(result["reports"], start=1)
        ]
    )
    edited = st.data_editor(
        summary,
        key="batch_editor",
        hide_index=True,
        use_container_width=True,
        disabled=["#", "related_test_id"],
        column_config={
            "severity": st.column_config.SelectboxColumn("Severity", options=SEVERITIES, required=True),
            "priority": st.column_config.SelectboxColumn("Priority", options=PRIORITIES, required=True),
        },
    )
    reports = apply_summary_edits(result["reports"], edited.to_dict("records"))

    stem = f"bug_reports_{st.session_state.get('batch_project', 'project')}"
    col_xlsx, col_md = st.columns(2)
    with col_xlsx:
        st.download_button(
            "⬇️ Download .xlsx", to_excel(reports), f"{stem}.xlsx", XLSX_MIME, key="download_batch_xlsx"
        )
    with col_md:
        st.download_button(
            "⬇️ Download .md", combined_markdown(reports).encode("utf-8"), f"{stem}.md", "text/markdown",
            key="download_batch_md",
        )
    _usage_caption(result["usage"])


def _render_run_tab(configs: list[str]) -> None:
    uploaded = st.file_uploader("Executed test run (.xlsx or .csv)", type=["xlsx", "csv"], key="run_file")
    project = st.selectbox("Project", configs, key="run_project_select")
    if uploaded is None:
        st.info("Upload a test run with a status column and an actual result column.")
        return
    try:
        raw_rows = parse_uploaded_file(uploaded)
    except FileImportError as e:
        st.error(str(e))
        return

    headers = list(raw_rows[0].keys())
    if st.session_state.get("run_mapped_file_name") != uploaded.name:
        # A new file: suggest a mapping once and drop results that belong to the old file.
        try:
            client = AIClient(api_key=st.session_state.get("api_key") or None)
            suggestion = client.suggest_column_mapping(
                load_run_column_mapping_prompt(), headers, raw_rows[:5]
            )["mapping"]
        except ValueError as e:
            st.warning(f"Could not get a column mapping suggestion: {e}")
            suggestion = {}
        st.session_state["run_mapping_suggestion"] = suggestion
        st.session_state["run_mapped_file_name"] = uploaded.name
        st.session_state.pop("batch_result", None)

    st.markdown("**Confirm column mapping** — test case columns are optional context for the AI:")
    # Blank header names would look like "unmapped" and could silently feed a column's data.
    options = [""] + [h for h in headers if h.strip()]
    suggestion = st.session_state.get("run_mapping_suggestion", {})
    mapping = {}
    for field in (*RUN_FIELDS, *TEST_CASE_FIELDS):
        suggested = suggestion.get(field, "")
        index = options.index(suggested) if suggested in options else 0
        mapping[field] = st.selectbox(field, options, index=index, key=f"run_mapping_{field}")

    rows = []
    missing = [field for field in REQUIRED_RUN_FIELDS if not mapping[field]]
    if missing:
        st.warning("Map the required column(s): " + ", ".join(missing))
    else:
        values = distinct_values(raw_rows, mapping["status"])
        # Keyed by column: values chosen for one column are never offered against another.
        chosen = st.multiselect(
            "Status values that mean the test failed",
            values,
            default=default_failed_values(values),
            key=f"run_failed_values_{mapping['status']}",
        )
        rows = failed_rows(raw_rows, mapping, chosen)
        if not rows:
            st.info("No rows have the selected status values.")
        elif len(rows) > MAX_BATCH_ROWS:
            st.error(
                f"{len(rows)} failed rows found; the limit is {MAX_BATCH_ROWS} per run. "
                "Split the file and run each part."
            )
        else:
            st.markdown(f"**{len(rows)}** failed row(s) will get a bug report.")

    ready = 0 < len(rows) <= MAX_BATCH_ROWS
    if st.button(f"🐞 Write {len(rows)} bug report(s)", key="write_batch_btn", disabled=not ready):
        try:
            config = load_project_config(CONFIGS_DIR / f"{project}.yaml")
            client = AIClient(api_key=st.session_state.get("api_key") or None)
        except (ProjectConfigError, ValueError) as e:
            st.error(str(e))
            return
        system_prompt = build_system_prompt(config, base_prompt_path=BUG_REPORT_PROMPT_PATH)
        progress = st.progress(0.0, text="Writing bug reports...")
        st.session_state["batch_result"] = write_reports(
            client,
            system_prompt,
            rows,
            source_name=uploaded.name,
            on_progress=lambda done, total: progress.progress(done / total, text=f"Written {done} of {total}"),
        )
        st.session_state["batch_project"] = project

    if "batch_result" in st.session_state:
        _render_batch_result()
```

Replace the old top-level flow after the helpers with:
```python
configs = list_available_configs(CONFIGS_DIR)
if not configs:
    st.error("No project configs found in configs/. Add one from configs/_template.yaml.")
    st.stop()

notes_tab, run_tab = st.tabs(["From notes", "From a test run"])
with notes_tab:
    _render_notes_tab(configs)
with run_tab:
    _render_run_tab(configs)
```

Update the page docstring's second sentence to "…exported as Markdown or Excel — from notes about one defect or from the failed rows of a test run." and the caption to "Turn rough notes, or the failed rows of a test run, into bug reports you can paste into any tracker."

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_bug_reporter_page.py -q -p no:cacheprovider`
Expected: all page tests pass (existing + 7 new).

- [ ] **Step 5: Full suite and a manual check**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → all pass.
Run `.venv/Scripts/python.exe -m streamlit run app.py --server.headless true --server.port 8599`, open `http://localhost:8599/Bug_Reporter`, check both tabs render (the run tab shows the upload hint). Stop the server.

- [ ] **Step 6: Commit**

```bash
git add pages/2_Bug_Reporter.py tests/test_bug_reporter_page.py
git commit -m "feat: write bug reports from the failed rows of a test run"
```

---

### Task 4: Documentation

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

- [ ] **Step 1: README**

In "Write a bug report", change step 1 to `1. Open **Bug Reporter** in Streamlit's page navigation (tab **From notes**)`, and after the "The Markdown pastes into…" line add:

```markdown
### Write bug reports from a test run

1. Open **Bug Reporter** and the **From a test run** tab
2. Upload the executed test run (`.xlsx`/`.csv`) and confirm the AI-suggested
   columns: status and actual result are required; a tester comment column and
   the test case columns are optional context
3. Check which status values count as failed (`Failed`, `NG`, `Không đạt`… are
   pre-selected; `Blocked` and `Not run` are not defects)
4. Click **Write N bug report(s)** (up to 50 per run), adjust titles, severity
   and priority in the summary, and download one `.xlsx` or `.md` with every report

Each report records its source (file and row) and follows the defect report
content of ISTQB and ISO/IEC/IEEE 29119-3, including reproducibility and
build/version; the tracker assigns the ID, date, reporter and status.
```

In Roadmap, change `- [ ] Phase 3, step 2: Bug reports from the failed rows of an executed test run` to `- [x] Phase 3, step 2: Bug reports from the failed rows of an executed test run`. In Directory structure add `│   ├── bug_batch.py              # Bug reports from the failed rows of a test run` after the `bug_exporters.py` line (fix the tree glyphs so the last child keeps `└──`), and `│   └── run_column_mapping_system_prompt.md` under prompts (same glyph rule).

- [ ] **Step 2: CHANGELOG**

Under `## Unreleased`, append:
```markdown
- Bug Reporter: a **From a test run** tab writes one bug report per failed row of an uploaded
  test run (up to 50 per run), with AI-suggested column mapping, editable summary, a list of
  rows that failed, and one Excel or Markdown download.
- Bug reports follow ISTQB / ISO/IEC/IEEE 29119-3 defect report content more closely: new
  reproducibility and build/version fields, and a source (file and row) for batch reports.
```

- [ ] **Step 3: Verify and commit**

Run: `.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider` → all pass.
```bash
git add README.md CHANGELOG.md
git commit -m "docs: document batch bug reports and the standards alignment"
```
