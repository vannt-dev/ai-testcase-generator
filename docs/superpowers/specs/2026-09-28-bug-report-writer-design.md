# Bug Report Writer — Design

Status: approved (design), pending implementation plan
Roadmap: Phase 3 of the project roadmap (README.md), step 1 of 2

## Purpose

Let a tester turn rough notes about a defect ("tapping Pay with an expired
card freezes the app, no error shown") into a complete, consistent bug
report that can be pasted into any tracker. The AI structures the report
and asks for what is missing instead of inventing it.

Jira integration from the original roadmap is replaced by tracker-neutral
exports: the owner does not use Jira, and Markdown pastes into GitHub,
GitLab, Azure DevOps and Jira Cloud alike. A tracker integration can be
added later as one more exporter.

## Scope

**In scope (step 1):**
- A new Streamlit page, `pages/2_Bug_Reporter.py`.
- One bug per run: rough notes in, one structured `BugReport` out, with an
  optional related test case pasted as context.
- Editing the generated report before export.
- Exports: Markdown (one report) and Excel (one row per report).

**Step 2 (separate spec, not part of this one):** upload an executed test
run (`.xlsx`/`.csv`), keep the failed rows, and write one report per row by
calling the same `write_bug_report` core; export all of them to one Excel
file. Step 1 must not need changes for that beyond new callers.

**Out of scope:**
- Posting to a tracker API (Jira, GitHub Issues, Azure DevOps).
- Screenshots, attachments or log files as input.
- Persisting reports outside the current browser session.

## Architecture

The core works on one bug; inputs and outputs are adapters around it.

```
rough notes (+ related test case) ──► AIClient.write_bug_report ──► BugReport
                                                                       │
                                              core/bug_exporters.py ◄──┘
                                              ├─ to_markdown(report) -> str
                                              └─ to_excel(reports)   -> bytes
```

- The system prompt is `prompts/bug_report_system_prompt.md`, combined with
  the project config by the existing `build_system_prompt`, as the
  Reviewer does.
- `write_bug_report` goes through the existing `_call_ai`, so it inherits
  retries, error messages, the max-tokens guard, prompt caching and usage
  and cost reporting.

## Components

### `core/ai_client.py` additions

```python
class BugReport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1)
    module: str = Field(min_length=1)
    severity: Literal["Critical", "Major", "Minor", "Trivial"]
    priority: Literal["High", "Medium", "Low"]
    environment: str            # "" when the notes don't say
    preconditions: str          # "" when none
    steps_to_reproduce: list[str] = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    actual_result: str = Field(min_length=1)
    test_data: str              # "" when none
    related_test_id: str        # "" when no related test case was given
    open_questions: list[str]
```

`AIClient.write_bug_report(system_prompt, notes, related_test_case=None)`
returns `{"report": {...BugReport...}, "usage": {...}}`, the same envelope
as `review_test_cases`. `related_test_case` is a dict of `TestCase` fields
serialized with `json.dumps(..., default=str)`, as the Reviewer does for
uploaded rows.

### `core/prompt_builder.py`

Add `BUG_REPORT_PROMPT_PATH` next to `REVIEWER_PROMPT_PATH`.

### `prompts/bug_report_system_prompt.md`

Role: Senior QA Lead writing a bug report from a tester's notes. Rules:
1. Use only facts in the notes, the related test case and the project
   config. Never invent steps, environments, versions or data.
2. Anything a developer needs but the notes lack (build, device, account,
   exact input) goes into `open_questions`, and the related field stays
   empty rather than guessed.
3. `steps_to_reproduce` are numbered-ready, one action each, starting from
   the preconditions.
4. `title` states the observed failure and where it happens, in under
   100 characters.
5. `severity` reflects user impact (Critical: crash, data loss or security
   issue with no workaround; Major: a main flow is broken; Minor: a
   workaround exists; Trivial: cosmetic). `priority` reflects how urgently
   it should be fixed and may differ from severity.
6. Use the project's `glossary` terms and `domain_rules` where relevant.

### `core/bug_exporters.py`

- `to_markdown(report: dict) -> str`: a title heading; a severity,
  priority, module and environment line; Preconditions; a numbered Steps
  to Reproduce list; Expected; Actual; Test Data; Related Test Case; and
  Open Questions only when non-empty. Empty optional sections are left out.
  User text is escaped so it can't break the Markdown structure (for
  example a line starting with `#`).
- `to_excel(reports: list[dict]) -> bytes`: one sheet, "Bug Reports", one
  row per report, steps joined with numbered lines, header style and
  column widths matching `excel_exporter.py`, severity cell colored.

### `pages/2_Bug_Reporter.py`

1. Sidebar: the same API key block as the Reviewer page.
2. Project config select (`list_available_configs`, `load_project_config`).
3. Text area for the notes (required) and an optional text area for the
   related test case, as free text or a pasted row.
4. "Write bug report" calls `write_bug_report`; errors show `st.error`,
   as on the other pages.
5. The result shows as editable fields (`st.text_input`, `st.selectbox`
   for severity and priority, `st.data_editor` for steps), stored in
   `st.session_state["bug_report"]`.
6. A warning lists `open_questions` when present.
7. Actions: a Markdown preview with `st.code(..., language="markdown")`,
   whose copy button copies it; "Download .md"; "Download .xlsx"; and the
   token usage and cost line used on the Generator page.

## Data Flow

notes + optional related test case → `build_system_prompt(config,
BUG_REPORT_PROMPT_PATH)` → `write_bug_report` → `BugReport` dict in
session state → user edits → exporters → downloads. Nothing is written to
disk on the server.

## Error Handling

- Empty notes: the button is disabled and a hint explains why.
- API and schema errors: the `ValueError` messages from `_call_ai` are
  shown as they are for the other pages.
- A related test case that isn't valid JSON is sent as plain text; it is
  context, not a contract.
- Edits that clear a required field (title, expected, actual, all steps)
  block the exports with a message naming the field.

## Testing

No test calls the real API; all use the fake client pattern in
`tests/test_ai_client.py`.

- `tests/test_ai_client.py`: `write_bug_report` sends the notes and the
  related test case, returns the envelope with usage, and rejects output
  that fails the `BugReport` schema; schema tests for the severity and
  priority enums and non-empty steps.
- `tests/test_bug_exporters.py`: Markdown section order, omitted empty
  sections, numbered steps, escaping of Markdown control characters;
  Excel headers, one row per report, severity fill.
- `tests/test_bug_reporter_page.py` (`streamlit.testing.AppTest`, as in
  `test_reviewer_page.py`): disabled button on empty notes, a successful
  run renders the fields and open-questions warning, and an edit that
  clears a required field blocks the downloads.
- `tests/test_prompt_builder.py`: the bug report prompt loads and merges
  the project config.

## Documentation

- README: the Bug Reporter under features and usage; the roadmap marks
  Phase 3 step 1 done and replaces "Jira integration" with tracker-neutral
  export.
- CHANGELOG: an Unreleased entry.

## Open Questions

None.
