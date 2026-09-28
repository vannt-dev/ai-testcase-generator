# Batch Bug Reports from a Test Run — Design

Status: approved (design), pending implementation plan
Roadmap: Phase 3 of the project roadmap (README.md), step 2 of 2
Builds on: `docs/superpowers/specs/2026-09-28-bug-report-writer-design.md`

## Purpose

After running a test suite, a tester has a spreadsheet with a status and
an actual result per test case. Writing one bug report per failed row by
hand is repetitive. This step turns the failed rows of that file into bug
reports in one run, using the one-bug core from step 1.

## Standards alignment

Checked against the defect report content in the ISTQB Foundation syllabus and the
incident report in ISO/IEC/IEEE 29119-3. Already aligned: separate severity and priority,
a Critical/Major/Minor/Trivial scale, title, steps, expected and actual results, test data,
environment and the related test case; only `Failed` rows become reports (`Blocked` and
`Not run` are not defects). This step closes the gaps that matter outside a tracker:

- **Reproducibility** (`Always`, `Intermittent`, `Once`, `Unknown`) is added to `BugReport`.
- **Build / version** is split out of `environment` into `build_version`.
- **Source**: every batch report records which test run and row it came from.
- `x` is not a default failed value: many teams mark executed or passed rows with it.

Identifier, report date, reporter and defect status are left to the tracker, which
assigns them when the issue is created.

## Scope

**In scope:**
- A second tab on `pages/2_Bug_Reporter.py`, "From a test run". The
  existing flow becomes the first tab, "From notes", and is unchanged.
- Upload `.xlsx`/`.csv` through the existing `parse_uploaded_file`, with the
  same limits (10 MiB, 500 rows).
- AI-suggested column mapping, confirmed by the user, for `status` and
  `actual_result` (required), `comment` (optional) and the test case fields
  (optional context).
- Choosing which status values count as failed, with defaults filled in.
- Writing one report per failed row through `AIClient.write_bug_report`,
  at most 50 rows per run, with progress; a row that fails doesn't stop
  the run.
- A summary table whose title, severity and priority can be edited; a list
  of rows that failed; the total usage and cost.
- Downloads: one Excel file with every report (`to_excel`) and one Markdown
  file with the reports separated by `---`.
- Standards alignment changes to the step 1 core (see below): `reproducibility`
  and `build_version` in `BugReport`, the prompt, both exporters and the
  "From notes" form; an optional `source` shown by both exporters.

**Out of scope:**
- Editing every field of each report in the batch view. To polish one
  report, paste it into the "From notes" tab.
- Merging duplicate bugs across rows.
- Running more than 50 rows in one go (the user splits the file).

## Architecture

```
upload ─► parse_uploaded_file ─► suggest_column_mapping(RUN prompt) ─► user confirms mapping
      ─► default_failed_values ─► user confirms failed values ─► failed_rows
      ─► write_reports ──(per row)──► AIClient.write_bug_report ─► reports + errors + usage
      ─► summary editor ─► to_excel / combined_markdown ─► downloads
```

The logic lives in a new module, `core/bug_batch.py`, so it can be tested
without Streamlit. `write_bug_report`, `to_markdown` and `to_excel` are
reused unchanged.

## Components

### Step 1 core changes (standards alignment)

- `core/ai_client.py` `BugReport` gains
  `build_version: str` (`""` when the notes don't say) and
  `reproducibility: Literal["Always", "Intermittent", "Once", "Unknown"]`.
- `prompts/bug_report_system_prompt.md` gains two rules. `build_version` is
  the app or build version only when the notes or test case state it;
  otherwise it is empty and a question is asked. `reproducibility` is
  `Unknown` unless the notes say how often it happens (for example
  "every time" or "sometimes"); when it is `Unknown`, ask. The output list
  names both fields.
- `core/bug_exporters.py`:
  - The Markdown meta line adds `**Reproducibility:**` after priority, and
    `**Build:**` before environment when it is non-empty.
  - A `**Source:**` line follows when `report.get("source")` is non-empty.
  - Excel adds the columns "Reproducibility" after Priority, "Build / Version"
    before Environment, and "Source" last.
  - `source` is not part of `BugReport`; it is set by the batch after generation.
- `pages/2_Bug_Reporter.py` "From notes" adds a "Build / version" text input
  (`bug_build_version`) and a "Reproducibility" select (`bug_reproducibility`)
  to the draft and the form.

### `core/bug_batch.py`

```python
RUN_FIELDS = ("status", "actual_result", "comment")
REQUIRED_RUN_FIELDS = ("status", "actual_result")
MAX_BATCH_ROWS = 50
FAILED_STATUS_WORDS = {"fail", "failed", "failure", "ng", "ko dat", "khong dat"}
```

- `default_failed_values(values: list[str]) -> list[str]`: the distinct
  non-blank values whose normalized form is in `FAILED_STATUS_WORDS`, in
  first-seen order. Normalizing lowercases, strips, and removes
  Vietnamese diacritics (đ → d), so `Không đạt`, `KO ĐẠT` and `Failed`
  all match.
- `failed_rows(rows, mapping, failed_values) -> list[dict]`: for each raw
  row whose mapped status (stripped) is in `failed_values`, returns
  `{"test_case": {field: value for mapped TEST_CASE_FIELDS with a non-blank value},
  "actual_result": str, "comment": str}`, keeping file order. Cell values
  go through `str(...).strip()`; `None` becomes `""`.
- `notes_for_row(row) -> str`: `"Test case failed during a test run.\n\nActual result: {actual_result}"`,
  plus `"\n\nTester comment: {comment}"` when a comment is present.
- `failed_rows` also returns `"row_number"`: the 1-based data row number in the
  uploaded file (the header is not counted), used for `source`.
- `write_reports(client, system_prompt, rows, source_name="", on_progress=None) -> dict`:
  calls `client.write_bug_report(system_prompt, notes_for_row(row), row["test_case"] or None)`
  for each row, in order. A `ValueError` from one row is recorded as
  `{"row": <1-based index among failed rows>, "test_id": <test_id or "">, "error": <message>}`
  and the run continues. Each report gets
  `report["source"] = f"{source_name}, row {row_number}"` (just `f"row {row_number}"`
  when `source_name` is empty). `on_progress(done, total)` is called after
  each row. Returns `{"reports": [...], "errors": [...], "usage": {...}}`.
  The usage sums `input_tokens`, `output_tokens`, `cache_creation_input_tokens`
  and `cache_read_input_tokens`, and `estimated_cost_usd` (which is `None` if
  any row has no estimate), and keeps the model name.
- `combined_markdown(reports: list[dict]) -> str`: `to_markdown` of each
  report joined by `"\n---\n\n"`.

### `prompts/run_column_mapping_system_prompt.md`

This is the same prompt as `column_mapping_system_prompt.md`, with three
more target fields:
- `status`: the pass/fail result column.
- `actual_result`: what actually happened.
- `comment`: the tester's remarks or notes.

The test case fields are optional here. Because `suggest_column_mapping`
already takes the system prompt as a parameter, it is reused as is.
`core/prompt_builder.py` gets `RUN_COLUMN_MAPPING_PROMPT_PATH` and
`load_run_column_mapping_prompt()`.

### `pages/2_Bug_Reporter.py`

The page gets two tabs: "From notes" (the existing flow, moved inside the
tab) and "From a test run". The second tab:

1. Uploader (`key="run_file"`), a project select (`key="run_project_select"`).
2. When the file name changes, suggest a mapping once, the way the Reviewer
   does (session keys `run_mapped_file_name`, `run_mapping_suggestion`).
3. One mapping select per field, `key=f"run_mapping_{field}"`, for
   `RUN_FIELDS` then `TEST_CASE_FIELDS`. Blank header names aren't offered.
   A warning names any missing required field.
4. When `status` is mapped: a multiselect (`key="run_failed_values"`) of the
   distinct status values, defaulting to `default_failed_values`. It is
   followed by a line saying how many rows will be reported.
5. "Write N bug reports" (`key="write_batch_btn"`) is disabled until the
   required fields are mapped, at least one failed value is chosen, and
   there are 1 to 50 failed rows. An error explains the 50-row limit when
   it's exceeded.
6. The run shows an `st.progress` bar, then stores the result in
   `st.session_state["batch_result"]`.
7. Results:
   - A `st.data_editor` (`key="batch_editor"`) with #, related test ID,
     title, severity (selectbox column) and priority (selectbox column).
     Title, severity and priority can be edited, and the edits are applied
     to the reports that are exported.
   - An error list for the rows that failed.
   - A usage caption with the summed tokens and cost.
   - "Download .xlsx" (`key="download_batch_xlsx"`) and "Download .md"
     (`key="download_batch_md"`), named `bug_reports_<project>.xlsx|md`.

## Error Handling

- Parse errors from `parse_uploaded_file` are shown as they are on the
  Reviewer page.
- If the mapping suggestion fails, a warning is shown and every field
  starts unmapped.
- No failed rows: an info message and no button.
- More than 50 failed rows: an error with the count and a request to split
  the file. The button stays disabled.
- An AI error on one row: that row goes to the error list, and the other
  reports are still exported.
- Every row failed: an error message and no downloads.
- An edit that clears a title: that report is exported with its original
  title.

## Testing

No test calls the real API.

- `tests/test_bug_batch.py`:
  - `default_failed_values`: Vietnamese forms with and without
    diacritics, mixed case, blanks ignored, first-seen order, `x`/`Passed`/
    `Blocked` not selected.
  - `failed_rows`: filtering by the chosen values, unmapped optional
    fields, `None` cells, file order.
  - `notes_for_row`: with and without a comment.
  - `write_reports`: using a fake client. One row raises `ValueError` and
    the others still run. Checks the order of progress callbacks, the
    usage sums, and that the cost is `None` when any row has no estimate.
  - `combined_markdown`: the separator.
  - `write_reports` sets `source` from the file name and row number.
- Step 1 tests updated: `BugReport` accepts the new fields and rejects an
  unknown reproducibility; the exporters show reproducibility, build and
  source, and leave out empty build and source; the "From notes" form loads
  and exports both new fields.
- `tests/test_prompt_builder.py`: the run mapping prompt lists `status`,
  `actual_result` and `comment`.
- `tests/test_bug_reporter_page.py` (AppTest):
  - An upload with a mocked mapping pre-selects the failed values and
    shows the row count.
  - The button is disabled while `status` is unmapped.
  - A run with a mocked `write_bug_report` (one row raising) shows the
    summary and the error, and enables both downloads.
  - More than 50 failed rows disables the button with the limit error.
  - The existing single-report tests still pass inside the "From notes" tab.

## Documentation

- README: add "Write bug reports from a test run" under usage, and mark
  roadmap Phase 3 step 2 done.
- CHANGELOG: add an entry under Unreleased.

## Open Questions

None.
