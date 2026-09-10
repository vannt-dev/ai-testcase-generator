# Test Case Reviewer / Coverage Checker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Reviewer" page that scores an existing test case set's coverage against a requirement + project config, flags gaps/duplicates, and can generate + merge test cases to fill those gaps.

**Architecture:** Streamlit multipage app — `app.py` stays the Generator (home) page; a new `pages/1_Reviewer.py` is auto-discovered by Streamlit's `pages/` convention. New business logic (file parsing, column mapping, merging) lives in small, independently-testable `core/` modules; new AI calls are added as `AIClient` methods reusing the existing retry/error-handling path (extracted into a shared `_call_ai` helper during this work).

**Tech Stack:** Python 3.10+, Streamlit (multipage `pages/` convention), Anthropic SDK (`messages.parse` Structured Outputs), Pydantic, openpyxl, pytest + `streamlit.testing.v1.AppTest`.

**Spec:** `docs/superpowers/specs/2026-09-10-test-case-reviewer-design.md`

## Global Constraints

- Python >= 3.10 syntax (`str | None`), matching the rest of the repo.
- All new user-facing strings are English (the project was fully translated to English on 2026-09-10 — do not reintroduce Vietnamese text).
- `MAX_IMPORTED_ROWS = 500` for uploaded files (spec: file_import.py section).
- Column-mapping AI calls send only the **first 5** parsed rows as sample context (spec: `suggest_column_mapping` docstring).
- No new top-level dependencies — `openpyxl`, `pydantic`, `anthropic`, `streamlit`, `pandas` are already in `requirements.txt`.
- Every new/changed function that can fail must raise a `ValueError` (or a `ValueError` subclass) with a user-facing message — this is the existing error-handling convention (`ProjectConfigError`, `AIClient`'s `ValueError`s) and is what `pages/*.py` code already knows how to catch and render via `st.error`.

---

## Task 1: `core/file_import.py` — parse uploaded files into raw rows

**Files:**
- Create: `core/file_import.py`
- Test: `tests/test_file_import.py`

**Interfaces:**
- Produces: `FileImportError(ValueError)`, `MAX_IMPORTED_ROWS: int`, `parse_uploaded_file(uploaded_file) -> list[dict]` where `uploaded_file` exposes `.name: str` and `.getvalue() -> bytes` (this matches Streamlit's `UploadedFile` and is trivial to fake in tests).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_file_import.py`:

```python
import io

import openpyxl
import pytest

from core.file_import import FileImportError, MAX_IMPORTED_ROWS, parse_uploaded_file


class FakeUploadedFile:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def _make_xlsx_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_parse_uploaded_xlsx_returns_rows_keyed_by_header():
    content = _make_xlsx_bytes(
        ["ID", "Title"],
        [["TC_001", "Login works"], ["TC_002", "Login fails"]],
    )
    uploaded = FakeUploadedFile("cases.xlsx", content)

    rows = parse_uploaded_file(uploaded)

    assert rows == [
        {"ID": "TC_001", "Title": "Login works"},
        {"ID": "TC_002", "Title": "Login fails"},
    ]


def test_parse_uploaded_csv_returns_rows_keyed_by_header():
    content = "ID,Title\nTC_001,Login works\nTC_002,Login fails\n".encode("utf-8")
    uploaded = FakeUploadedFile("cases.csv", content)

    rows = parse_uploaded_file(uploaded)

    assert rows == [
        {"ID": "TC_001", "Title": "Login works"},
        {"ID": "TC_002", "Title": "Login fails"},
    ]


def test_parse_uploaded_file_rejects_unsupported_extension():
    uploaded = FakeUploadedFile("cases.txt", b"whatever")

    with pytest.raises(FileImportError, match="Unsupported file type"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_file_rejects_empty_file():
    content = _make_xlsx_bytes(["ID", "Title"], [])
    uploaded = FakeUploadedFile("empty.xlsx", content)

    with pytest.raises(FileImportError, match="no data rows"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_file_rejects_too_many_rows():
    content = _make_xlsx_bytes(["ID"], [[f"TC_{i}"] for i in range(MAX_IMPORTED_ROWS + 1)])
    uploaded = FakeUploadedFile("huge.xlsx", content)

    with pytest.raises(FileImportError, match="row limit"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_csv_rejects_invalid_utf8():
    uploaded = FakeUploadedFile("bad.csv", b"\x80\x81\x82")

    with pytest.raises(FileImportError, match="UTF-8"):
        parse_uploaded_file(uploaded)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe -q tests/test_file_import.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.file_import'`

- [ ] **Step 3: Write the implementation**

Create `core/file_import.py`:

```python
"""Parses uploaded test case files (.xlsx/.csv) into raw rows, independent of any target schema."""
import csv
import io

import openpyxl

MAX_IMPORTED_ROWS = 500


class FileImportError(ValueError):
    """File import error with a user-friendly message for the UI."""


def parse_uploaded_file(uploaded_file) -> list[dict]:
    """
    uploaded_file: an object exposing `.name` (str) and `.getvalue()`
    (bytes) — matches Streamlit's UploadedFile.
    Returns a list of dicts keyed by the file's own column headers.
    Raises FileImportError on an unsupported extension, an empty or
    unreadable file, or more than MAX_IMPORTED_ROWS data rows.
    """
    name = getattr(uploaded_file, "name", "")
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    raw_bytes = uploaded_file.getvalue()

    if suffix == "csv":
        rows = _parse_csv(raw_bytes)
    elif suffix == "xlsx":
        rows = _parse_xlsx(raw_bytes)
    else:
        raise FileImportError(
            f"Unsupported file type '.{suffix}'. Please upload a .xlsx or .csv file."
        )

    if not rows:
        raise FileImportError("The uploaded file has no data rows.")
    if len(rows) > MAX_IMPORTED_ROWS:
        raise FileImportError(
            f"The uploaded file has {len(rows):,} rows, which exceeds the "
            f"{MAX_IMPORTED_ROWS:,} row limit. Please split it into smaller files."
        )
    return rows


def _parse_csv(raw_bytes: bytes) -> list[dict]:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FileImportError(f"Could not read the CSV file as UTF-8: {error}") from error
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_xlsx(raw_bytes: bytes) -> list[dict]:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
    except Exception as error:
        raise FileImportError(f"Could not read the Excel file: {error}") from error

    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return []

    rows = []
    for values in rows_iter:
        if all(v is None for v in values):
            continue
        rows.append({headers[i]: values[i] for i in range(len(headers))})
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_file_import.py`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add core/file_import.py tests/test_file_import.py
git commit -m "Add file_import module to parse uploaded test case files"
```

---

## Task 2: `core/review_utils.py` — column mapping normalization

**Files:**
- Create: `core/review_utils.py`
- Test: `tests/test_review_utils.py`

**Interfaces:**
- Consumes: `TEST_CASE_FIELDS: tuple[str, ...]` from `core/result_utils.py` (existing).
- Produces: `apply_column_mapping(raw_rows: list[dict], mapping: dict[str, str]) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_review_utils.py`:

```python
from core.review_utils import apply_column_mapping


def test_apply_column_mapping_rekeys_rows_to_target_fields():
    raw_rows = [{"ID": "TC_001", "Name": "Login works", "Steps": "1. Login"}]
    mapping = {"test_id": "ID", "title": "Name", "steps": "Steps"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result == [
        {
            "test_id": "TC_001",
            "module": "",
            "title": "Login works",
            "precondition": "",
            "steps": "1. Login",
            "test_data": "",
            "expected_result": "",
            "priority": "",
            "type": "",
            "platform": "",
        }
    ]


def test_apply_column_mapping_handles_unmapped_field_as_empty():
    raw_rows = [{"ID": "TC_001"}]
    mapping = {"test_id": "ID"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result[0]["title"] == ""


def test_apply_column_mapping_stringifies_non_string_values():
    raw_rows = [{"ID": 42}]
    mapping = {"test_id": "ID"}

    result = apply_column_mapping(raw_rows, mapping)

    assert result[0]["test_id"] == "42"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe -q tests/test_review_utils.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.review_utils'`

- [ ] **Step 3: Write the implementation**

Create `core/review_utils.py`:

```python
"""Business logic for the Test Case Reviewer page: column mapping and merging."""
from core.result_utils import TEST_CASE_FIELDS


def apply_column_mapping(raw_rows: list[dict], mapping: dict[str, str]) -> list[dict]:
    """
    Re-key raw uploaded rows (arbitrary column names) into TEST_CASE_FIELDS
    using a confirmed {target_field: uploaded_column_name} mapping. A
    field mapped to "" (or missing from `mapping`) becomes an empty
    string in the output.
    """
    normalized = []
    for row in raw_rows:
        normalized.append(
            {
                field: str(row.get(mapping.get(field, ""), "") or "").strip()
                for field in TEST_CASE_FIELDS
            }
        )
    return normalized
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_review_utils.py`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add core/review_utils.py tests/test_review_utils.py
git commit -m "Add apply_column_mapping to normalize uploaded rows to the TestCase schema"
```

---

## Task 3: `core/review_utils.py` — merge with test_id collision handling

**Files:**
- Modify: `core/review_utils.py`
- Test: `tests/test_review_utils.py`

**Interfaces:**
- Produces: `merge_test_cases(existing: list[dict], new: list[dict]) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_review_utils.py`:

```python
from core.review_utils import merge_test_cases


def test_merge_test_cases_appends_without_collision():
    existing = [{"test_id": "TC_001", "title": "A"}]
    new = [{"test_id": "TC_002", "title": "B"}]

    result = merge_test_cases(existing, new)

    assert [tc["test_id"] for tc in result] == ["TC_001", "TC_002"]


def test_merge_test_cases_renames_colliding_test_id():
    existing = [{"test_id": "TC_001", "title": "A"}]
    new = [{"test_id": "TC_001", "title": "B (new)"}]

    result = merge_test_cases(existing, new)

    ids = [tc["test_id"] for tc in result]
    assert ids == ["TC_001", "TC_001_2"]
    assert result[1]["title"] == "B (new)"


def test_merge_test_cases_renames_multiple_collisions_sequentially():
    existing = [{"test_id": "TC_001"}, {"test_id": "TC_001_2"}]
    new = [{"test_id": "TC_001"}]

    result = merge_test_cases(existing, new)

    assert [tc["test_id"] for tc in result] == ["TC_001", "TC_001_2", "TC_001_3"]


def test_merge_test_cases_does_not_mutate_inputs():
    existing = [{"test_id": "TC_001"}]
    new = [{"test_id": "TC_001"}]

    merge_test_cases(existing, new)

    assert new[0]["test_id"] == "TC_001"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe -q tests/test_review_utils.py`
Expected: FAIL with `ImportError: cannot import name 'merge_test_cases'`

- [ ] **Step 3: Write the implementation**

Append to `core/review_utils.py`:

```python
def merge_test_cases(existing: list[dict], new: list[dict]) -> list[dict]:
    """
    Append `new` test cases to `existing`, renaming any `test_id` that
    collides with an existing (or already-renamed) id by appending
    _2, _3, etc. Does not mutate either input list/dicts.
    """
    used_ids = {tc.get("test_id") for tc in existing}
    merged = list(existing)
    for test_case in new:
        test_case = dict(test_case)
        base_id = test_case.get("test_id", "")
        candidate = base_id
        suffix = 2
        while candidate in used_ids:
            candidate = f"{base_id}_{suffix}"
            suffix += 1
        test_case["test_id"] = candidate
        used_ids.add(candidate)
        merged.append(test_case)
    return merged
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_review_utils.py`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add core/review_utils.py tests/test_review_utils.py
git commit -m "Add merge_test_cases with test_id collision handling"
```

---

## Task 4: Prompt infrastructure for the Reviewer

**Files:**
- Modify: `core/prompt_builder.py:11, 79-80, 108-113`
- Create: `prompts/reviewer_system_prompt.md`
- Create: `prompts/column_mapping_system_prompt.md`
- Test: `tests/test_prompt_builder.py`

**Interfaces:**
- Produces: `REVIEWER_PROMPT_PATH: Path`, `COLUMN_MAPPING_PROMPT_PATH: Path`, `load_column_mapping_prompt() -> str`, and a generalized `build_system_prompt(config: dict, base_prompt_path: Path = BASE_PROMPT_PATH) -> str` (existing callers unaffected — `base_prompt_path` defaults to the current behavior).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_prompt_builder.py`:

```python
def test_build_system_prompt_accepts_custom_base_prompt_path(tmp_path):
    custom_prompt_path = tmp_path / "custom_base.md"
    custom_prompt_path.write_text("CUSTOM BASE PROMPT CONTENT", encoding="utf-8")
    config = {
        "project_name": "Demo",
        "platform": ["web"],
        "test_id_format": "TC_{MODULE}_{NUMBER}",
        "test_types_required": ["positive"],
    }

    prompt = build_system_prompt(config, base_prompt_path=custom_prompt_path)

    assert prompt.startswith("CUSTOM BASE PROMPT CONTENT")
    assert "Demo" in prompt


def test_reviewer_prompt_file_exists_and_is_non_empty():
    from core.prompt_builder import REVIEWER_PROMPT_PATH

    assert REVIEWER_PROMPT_PATH.read_text(encoding="utf-8").strip()


def test_load_column_mapping_prompt_returns_non_empty_text():
    from core.prompt_builder import load_column_mapping_prompt

    assert load_column_mapping_prompt().strip()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe -q tests/test_prompt_builder.py`
Expected: FAIL — `build_system_prompt() got an unexpected keyword argument 'base_prompt_path'`, then (once fixed) `ImportError` for `REVIEWER_PROMPT_PATH`/`load_column_mapping_prompt`

- [ ] **Step 3: Write the implementation**

In `core/prompt_builder.py`, change line 11 from:

```python
BASE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "base_system_prompt.md"
```

to:

```python
BASE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "base_system_prompt.md"
REVIEWER_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "reviewer_system_prompt.md"
COLUMN_MAPPING_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "column_mapping_system_prompt.md"
```

Change lines 79-80 from:

```python
def load_base_prompt() -> str:
    return BASE_PROMPT_PATH.read_text(encoding="utf-8")
```

to:

```python
def load_base_prompt(path: Path = BASE_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def load_column_mapping_prompt() -> str:
    return COLUMN_MAPPING_PROMPT_PATH.read_text(encoding="utf-8")
```

Change lines 108-113 from:

```python
def build_system_prompt(config: dict) -> str:
    """
    Merge the base prompt with the project config info into one final
    system prompt.
    """
    base_prompt = load_base_prompt()
```

to:

```python
def build_system_prompt(config: dict, base_prompt_path: Path = BASE_PROMPT_PATH) -> str:
    """
    Merge a base prompt with the project config info into one final
    system prompt. `base_prompt_path` defaults to the Generator's base
    prompt; pass REVIEWER_PROMPT_PATH to build the Reviewer's instead.
    """
    base_prompt = load_base_prompt(base_prompt_path)
```

Create `prompts/reviewer_system_prompt.md`:

```markdown
You are a Senior QA Lead reviewing an existing set of test cases for
completeness and quality — you are NOT writing new test cases from
scratch.

TASK:
Given a requirement/user story, a project's configuration (domain
rules, required test types), and a list of already-written test
cases, assess how well the test cases cover the requirement and flag
problems.

MANDATORY RULES:
1. Check whether every distinct behavior/condition in the requirement
   has at least one corresponding test case. List anything uncovered
   as a gap.
2. Check whether all of the project's required test types
   (test_types_required) are represented by at least one test case.
   List any missing types in "missing_test_types".
3. Check whether the domain rules are exercised by at least one test
   case where relevant.
4. Flag test cases that are logically duplicated (test the same
   condition, even if worded differently) as a duplicate group, citing
   their test_id values and the reason.
5. Score overall coverage from 0 (nothing meaningful covered) to 100
   (fully covered, no gaps, no duplicates), based on the number and
   severity of gaps found.
6. Do not rewrite, restate, or correct the existing test cases —
   only report on them.

OUTPUT FORMAT:
Respond with ONLY a single valid JSON object, no markdown code fence,
no text other than the JSON, following exactly this structure:

{
  "coverage_score": 0,
  "missing_test_types": ["string"],
  "gaps": [
    {
      "description": "string — what's missing and why it matters",
      "suggested_type": "Positive | Negative | Edge case | UI/UX | Compatibility | Performance | Security",
      "severity": "High | Medium | Low"
    }
  ],
  "duplicates": [
    {
      "test_ids": ["string", "string"],
      "reason": "string"
    }
  ],
  "summary_note": "string — one or two sentences summarizing the review"
}

If there are no gaps or duplicates, return empty arrays for "gaps" and
"duplicates" and set "coverage_score" accordingly high.
```

Create `prompts/column_mapping_system_prompt.md`:

```markdown
You are helping map columns from an arbitrary, externally-authored
test case spreadsheet onto a fixed target schema.

TASK:
Given the uploaded file's column headers and a few sample rows, map
each target field below to the header name in the uploaded file that
most likely contains that data. If no column plausibly matches a
target field, map it to an empty string.

TARGET FIELDS:
test_id, module, title, precondition, steps, test_data,
expected_result, priority, type, platform

OUTPUT FORMAT:
Respond with ONLY a single valid JSON object, no markdown code fence,
no text other than the JSON:

{
  "mapping": {
    "test_id": "string (uploaded column name, or empty string)",
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_prompt_builder.py`
Expected: 12 passed (9 existing + 3 new)

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `.venv/Scripts/pytest.exe -q`
Expected: all passing (no other file references `load_base_prompt()`/`build_system_prompt()` with incompatible args)

- [ ] **Step 6: Commit**

```bash
git add core/prompt_builder.py prompts/reviewer_system_prompt.md prompts/column_mapping_system_prompt.md tests/test_prompt_builder.py
git commit -m "Add Reviewer/column-mapping prompts and generalize build_system_prompt"
```

---

## Task 5: `AIClient` — extract shared call helper, add `review_test_cases`

**Files:**
- Modify: `core/ai_client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `CoverageGap`, `DuplicateGroup`, `ReviewResult` (Pydantic models); `AIClient.review_test_cases(self, system_prompt: str, requirement_text: str, test_cases: list[dict]) -> dict` returning `{"review": {...}, "usage": {...}}`. Internal: `AIClient._call_ai(self, system_prompt: str, user_content: str, output_format: type[BaseModel])` — used by `generate_test_cases` too after this task (refactor, no external behavior change).

This task first **refactors** `generate_test_cases` to extract its retry/error-handling loop into a private `_call_ai` helper (so later tasks don't duplicate ~40 lines of retry logic), verifies no existing test breaks, then adds the new schema + method.

- [ ] **Step 1: Run the existing ai_client tests as a baseline**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py`
Expected: 7 passed (this is the baseline the refactor in Step 2 must not break)

- [ ] **Step 2: Refactor `generate_test_cases` to use a shared `_call_ai` helper**

In `core/ai_client.py`, replace the body of `generate_test_cases` (lines 110-173) with:

```python
    def _call_ai(self, system_prompt: str, user_content: str, output_format: type[BaseModel]):
        """
        Shared retry/error-handling wrapper around client.messages.parse.
        Returns the raw `message` object (caller extracts parsed_output/
        usage). Raises ValueError with a user-facing message on failure.
        """
        attempt = 0
        while True:
            try:
                message = self.client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    # Cache the base prompt + project config: unchanged across
                    # generations within the same session/project -> lowers cost.
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_content}],
                    output_format=output_format,
                )
                break
            except anthropic.AuthenticationError:
                raise ValueError("Invalid API key. Please check your ANTHROPIC_API_KEY.")
            except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
                attempt += 1
                if attempt > self.max_retries:
                    if isinstance(e, anthropic.RateLimitError):
                        raise ValueError(
                            "Anthropic API rate limit exceeded. Please try again in a few minutes."
                        ) from e
                    raise ValueError(
                        "Could not connect to the Anthropic API. Check your network connection."
                    ) from e
                self._sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
            except anthropic.APIStatusError as e:
                raise ValueError(f"Anthropic API returned an error ({e.status_code}): {e.message}")

        if message.stop_reason == "max_tokens":
            raise ValueError(
                "The AI's response was cut off after exceeding max_tokens before "
                "finishing the JSON. Try a shorter/more specific input, or split "
                "it into multiple runs."
            )
        if message.parsed_output is None:
            raise ValueError(
                "The AI did not return a result matching the expected schema."
            )
        return message

    def generate_test_cases(self, system_prompt: str, requirement_text: str) -> dict:
        """
        Send the requirement + system prompt (already merged with the project
        config) to Claude, and return a dict {"test_cases": [...], "summary":
        {...}} validated against the schema (Structured Outputs), ready for
        excel_exporter/app.py.
        """
        message = self._call_ai(
            system_prompt,
            f"Requirement/User Story to write test cases for:\n\n{requirement_text}",
            GenerationResult,
        )
        parsed_result = message.parsed_output.model_dump()
        result = build_edited_result(parsed_result, parsed_result["test_cases"])
        result["usage"] = self._build_usage(message.usage)
        return result
```

- [ ] **Step 3: Run the existing tests to confirm the refactor changed nothing observable**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py`
Expected: 7 passed (same as Step 1's baseline)

- [ ] **Step 4: Write the failing test for `review_test_cases`**

Append to `tests/test_ai_client.py`:

```python
from core.ai_client import ReviewResult


VALID_REVIEW = ReviewResult.model_validate(
    {
        "coverage_score": 80,
        "missing_test_types": ["security"],
        "gaps": [
            {
                "description": "No test for OTP resend after expiry",
                "suggested_type": "Negative",
                "severity": "High",
            }
        ],
        "duplicates": [],
        "summary_note": "Mostly covered; missing an OTP resend case.",
    }
)


def test_review_test_cases_returns_review_and_usage():
    response = SimpleNamespace(
        parsed_output=VALID_REVIEW,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=50, output_tokens=30),
    )
    client, messages = make_client(response)

    result = client.review_test_cases("system prompt", "requirement", [{"test_id": "TC_001"}])

    assert messages.kwargs["output_format"] is ReviewResult
    assert result["review"]["coverage_score"] == 80
    assert result["review"]["gaps"][0]["severity"] == "High"
    assert "usage" in result


def test_review_test_cases_includes_test_cases_in_user_message():
    response = SimpleNamespace(
        parsed_output=VALID_REVIEW,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    client, messages = make_client(response)

    client.review_test_cases("system prompt", "req text", [{"test_id": "TC_001", "title": "X"}])

    user_content = messages.kwargs["messages"][0]["content"]
    assert "req text" in user_content
    assert "TC_001" in user_content
```

- [ ] **Step 5: Run test to verify it fails**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py -k review_test_cases`
Expected: FAIL — `ImportError: cannot import name 'ReviewResult'`

- [ ] **Step 6: Write the implementation**

In `core/ai_client.py`, add near the top of the file (after the existing imports, before `DEFAULT_MODEL`):

```python
import json
```

After the existing `class GenerationResult(BaseModel): ...` block, add:

```python
class CoverageGap(BaseModel):
    description: str = Field(min_length=1)
    suggested_type: Literal[
        "Positive", "Negative", "Edge case", "UI/UX", "Compatibility", "Performance", "Security"
    ]
    severity: Literal["High", "Medium", "Low"]


class DuplicateGroup(BaseModel):
    test_ids: list[str] = Field(min_length=2)
    reason: str = Field(min_length=1)


class ReviewResult(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    missing_test_types: list[str]
    gaps: list[CoverageGap]
    duplicates: list[DuplicateGroup]
    summary_note: str
```

At the end of the `AIClient` class (after `generate_test_cases`), add:

```python
    def review_test_cases(self, system_prompt: str, requirement_text: str, test_cases: list[dict]) -> dict:
        """
        Send the requirement + an existing test case set to Claude for a
        coverage review. Returns {"review": {...ReviewResult...}, "usage": {...}}.
        """
        test_cases_json = json.dumps(test_cases, ensure_ascii=False, indent=2)
        message = self._call_ai(
            system_prompt,
            (
                f"Requirement/User Story:\n\n{requirement_text}\n\n"
                f"Existing test cases (JSON):\n\n{test_cases_json}"
            ),
            ReviewResult,
        )
        return {
            "review": message.parsed_output.model_dump(),
            "usage": self._build_usage(message.usage),
        }
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py`
Expected: 9 passed

- [ ] **Step 8: Commit**

```bash
git add core/ai_client.py tests/test_ai_client.py
git commit -m "Extract AIClient._call_ai helper and add review_test_cases"
```

---

## Task 6: `AIClient.generate_missing_cases`

**Files:**
- Modify: `core/ai_client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Consumes: `AIClient._call_ai` (Task 5), `GenerationResult`/`TestCase` (existing).
- Produces: `AIClient.generate_missing_cases(self, system_prompt: str, requirement_text: str, gaps: list[dict]) -> dict` returning the same shape as `generate_test_cases` (`{"test_cases": [...], "summary": {...}, "usage": {...}}`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ai_client.py`:

```python
def test_generate_missing_cases_returns_same_shape_as_generate_test_cases():
    response = SimpleNamespace(
        parsed_output=VALID_RESULT,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
    )
    client, messages = make_client(response)
    gaps = [{"description": "Missing OTP resend case", "suggested_type": "Negative", "severity": "High"}]

    result = client.generate_missing_cases("system prompt", "requirement", gaps)

    assert messages.kwargs["output_format"] is GenerationResult
    assert result["test_cases"][0]["test_id"] == "TC_LOGIN_001"
    user_content = messages.kwargs["messages"][0]["content"]
    assert "Missing OTP resend case" in user_content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py -k generate_missing_cases`
Expected: FAIL — `AttributeError: 'AIClient' object has no attribute 'generate_missing_cases'`

- [ ] **Step 3: Write the implementation**

In `core/ai_client.py`, after `review_test_cases`, add:

```python
    def generate_missing_cases(self, system_prompt: str, requirement_text: str, gaps: list[dict]) -> dict:
        """
        Generate test cases to fill the given coverage gaps (the "gaps"
        list from a prior review_test_cases() result). Returns the same
        shape as generate_test_cases().
        """
        gaps_json = json.dumps(gaps, ensure_ascii=False, indent=2)
        message = self._call_ai(
            system_prompt,
            (
                f"Requirement/User Story:\n\n{requirement_text}\n\n"
                "Write test cases to fill ONLY the following coverage gaps "
                f"(one or more test cases per gap as needed):\n\n{gaps_json}"
            ),
            GenerationResult,
        )
        parsed_result = message.parsed_output.model_dump()
        result = build_edited_result(parsed_result, parsed_result["test_cases"])
        result["usage"] = self._build_usage(message.usage)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add core/ai_client.py tests/test_ai_client.py
git commit -m "Add AIClient.generate_missing_cases"
```

---

## Task 7: `AIClient.suggest_column_mapping`

**Files:**
- Modify: `core/ai_client.py`
- Test: `tests/test_ai_client.py`

**Interfaces:**
- Produces: `ColumnMappingResult` (Pydantic model), `AIClient.suggest_column_mapping(self, system_prompt: str, headers: list[str], sample_rows: list[dict]) -> dict` returning `{"mapping": {...}}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ai_client.py`:

```python
from core.ai_client import ColumnMappingResult


def test_suggest_column_mapping_returns_mapping_dict():
    parsed = ColumnMappingResult.model_validate(
        {"mapping": {"test_id": "ID", "title": "Name", "module": "", "precondition": "",
                      "steps": "", "test_data": "", "expected_result": "", "priority": "",
                      "type": "", "platform": ""}}
    )
    response = SimpleNamespace(
        parsed_output=parsed,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=5, output_tokens=5),
    )
    client, messages = make_client(response)

    result = client.suggest_column_mapping(
        "system prompt", ["ID", "Name"], [{"ID": "TC_001", "Name": "Login works"}]
    )

    assert messages.kwargs["output_format"] is ColumnMappingResult
    assert result["mapping"]["test_id"] == "ID"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py -k suggest_column_mapping`
Expected: FAIL — `ImportError: cannot import name 'ColumnMappingResult'`

- [ ] **Step 3: Write the implementation**

In `core/ai_client.py`, after the `ReviewResult`/`CoverageGap`/`DuplicateGroup` block, add:

```python
class ColumnMappingResult(BaseModel):
    mapping: dict[str, str]
```

After `generate_missing_cases`, add:

```python
    def suggest_column_mapping(self, system_prompt: str, headers: list[str], sample_rows: list[dict]) -> dict:
        """
        Ask the AI to guess which uploaded column corresponds to each
        TestCase field, given the file's headers and a few sample rows.
        Returns {"mapping": {...}} — always to be confirmed by the user
        before use.
        """
        sample_json = json.dumps(sample_rows, ensure_ascii=False, indent=2)
        message = self._call_ai(
            system_prompt,
            f"Uploaded file headers: {headers}\n\nSample rows (JSON):\n\n{sample_json}",
            ColumnMappingResult,
        )
        return message.parsed_output.model_dump()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_ai_client.py`
Expected: 11 passed

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/pytest.exe -q`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add core/ai_client.py tests/test_ai_client.py
git commit -m "Add AIClient.suggest_column_mapping"
```

---

## Task 8: `pages/1_Reviewer.py` — page skeleton + review from current session

**Files:**
- Modify: `app.py:141-143`
- Create: `pages/1_Reviewer.py`
- Modify: `tests/test_app.py`
- Create: `tests/test_reviewer_page.py`

**Interfaces:**
- Consumes: `core.ai_client.AIClient.review_test_cases` (Task 5), `core.prompt_builder.build_system_prompt`/`REVIEWER_PROMPT_PATH` (Task 4).
- Produces: two new `st.session_state` keys set by the Generator (`last_config: dict`, `last_requirement_text: str`) that the Reviewer page depends on; `pages/1_Reviewer.py` sets `review_result`, `review_test_cases`, `review_requirement_text`, `review_config` in `st.session_state` — later tasks (9, 10) read/write these same keys.

- [ ] **Step 1: Write the failing test for the new session_state keys in app.py**

In `tests/test_app.py`, extend `test_generate_flow_shows_editor_and_no_exception`:

```python
def test_generate_flow_shows_editor_and_no_exception(monkeypatch):
    at = _run_generation(monkeypatch)

    assert not at.exception
    assert at.session_state["last_result"]["summary"]["total"] == 1
    assert "test_case_editor" in at.session_state
    assert at.session_state["last_config"]["project_name"] == at.session_state["last_project_name"]
    assert at.session_state["last_requirement_text"] == "As a user, I want to log in with OTP"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest.exe -q tests/test_app.py -k test_generate_flow_shows_editor_and_no_exception`
Expected: FAIL — `KeyError: 'last_config'`

- [ ] **Step 3: Update `app.py` to store the extra session state**

In `app.py`, change lines 141-143 from:

```python
    st.session_state.pop("test_case_editor", None)
    st.session_state["last_result"] = result
    st.session_state["last_project_name"] = config["project_name"]
```

to:

```python
    st.session_state.pop("test_case_editor", None)
    st.session_state["last_result"] = result
    st.session_state["last_project_name"] = config["project_name"]
    st.session_state["last_config"] = config
    st.session_state["last_requirement_text"] = requirement_text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/pytest.exe -q tests/test_app.py`
Expected: 4 passed

- [ ] **Step 5: Commit the app.py change**

```bash
git add app.py tests/test_app.py
git commit -m "Store last_config and last_requirement_text for the Reviewer page to consume"
```

- [ ] **Step 6: Write the failing test for the Reviewer page skeleton**

Create `tests/test_reviewer_page.py`:

```python
"""Integration tests for pages/1_Reviewer.py using Streamlit AppTest."""
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient

PAGE_PATH = Path(__file__).parent.parent / "pages" / "1_Reviewer.py"

FAKE_REVIEW = {
    "review": {
        "coverage_score": 72,
        "missing_test_types": ["security"],
        "gaps": [
            {"description": "No test for OTP resend", "suggested_type": "Negative", "severity": "High"},
        ],
        "duplicates": [],
        "summary_note": "Mostly covered, missing OTP resend and security cases.",
    },
    "usage": {"model": "claude-sonnet-5", "estimated_cost_usd": 0.001},
}


def _seed_session_state(at):
    at.session_state["last_result"] = {
        "test_cases": [
            {
                "test_id": "TC_LOGIN_001", "module": "Login", "title": "Successful login",
                "precondition": "Account exists", "steps": "1. Log in", "test_data": "Valid account",
                "expected_result": "Home page opens", "priority": "High", "type": "Positive", "platform": "Web",
            }
        ],
        "summary": {"total": 1, "by_type": {}, "open_questions": []},
    }
    at.session_state["last_project_name"] = "E-commerce App Demo"
    at.session_state["last_config"] = {
        "project_name": "E-commerce App Demo",
        "platform": ["web"],
        "test_id_format": "TC_{MODULE}_{NUMBER}",
        "test_types_required": ["positive", "security"],
        "domain_rules": [],
        "glossary": {},
        "notes": "",
    }
    at.session_state["last_requirement_text"] = "As a user, I want to log in with OTP"


def test_no_session_data_shows_hint(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    assert not at.exception
    assert any("Generator" in info.value for info in at.info)


def test_review_from_session_shows_coverage_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["review_result"]["coverage_score"] == 72
    assert any("72" in m.value for m in at.metric)
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe -q tests/test_reviewer_page.py`
Expected: FAIL — `FileNotFoundError` / module not found (no `pages/1_Reviewer.py` yet)

- [ ] **Step 8: Write the implementation**

Create `pages/1_Reviewer.py`:

```python
"""
Test Case Reviewer — checks an existing test case set's coverage
against a requirement and project config, using the shared AIClient.
"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.prompt_builder import REVIEWER_PROMPT_PATH, build_system_prompt

load_dotenv()

CONFIGS_DIR = Path("configs")

st.set_page_config(page_title="Reviewer — AI Test Case Generator", page_icon="🔍", layout="wide")
st.title("🔍 Test Case Reviewer")
st.caption("Check test case coverage against a requirement and get gap-filling suggestions.")


def _run_review(requirement_text: str, config: dict, test_cases: list[dict]) -> None:
    try:
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except ValueError as e:
        st.error(str(e))
        return

    system_prompt = build_system_prompt(config, base_prompt_path=REVIEWER_PROMPT_PATH)
    with st.status("Reviewing test case coverage...", expanded=False) as status:
        try:
            result = client.review_test_cases(system_prompt, requirement_text, test_cases)
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Error calling the AI: {e}")
            return
        status.update(label="Review complete", state="complete")

    st.session_state["review_result"] = result["review"]
    st.session_state["review_test_cases"] = test_cases
    st.session_state["review_requirement_text"] = requirement_text
    st.session_state["review_config"] = config


def _render_review_result(review: dict) -> None:
    st.subheader("📊 Coverage Report")
    st.metric("Coverage score", f"{review['coverage_score']}/100")

    if review["missing_test_types"]:
        st.markdown("**Missing test types:** " + ", ".join(review["missing_test_types"]))

    if review["gaps"]:
        st.markdown("**Gaps found:**")
        severity_order = {"High": 0, "Medium": 1, "Low": 2}
        for gap in sorted(review["gaps"], key=lambda g: severity_order.get(g["severity"], 3)):
            st.markdown(f"- **[{gap['severity']}]** ({gap['suggested_type']}) {gap['description']}")
    else:
        st.success("No coverage gaps found.")

    if review["duplicates"]:
        st.markdown("**Possible duplicates:**")
        for group in review["duplicates"]:
            st.markdown(f"- {', '.join(group['test_ids'])} — {group['reason']}")

    if review.get("summary_note"):
        st.caption(review["summary_note"])


session_tab, upload_tab = st.tabs(["From current session", "Upload external file"])

with session_tab:
    if "last_result" not in st.session_state or not st.session_state["last_result"].get("test_cases"):
        st.info("No test cases generated yet this session. Go to the Generator page first, or use the Upload tab.")
    else:
        st.markdown(f"**Project:** {st.session_state.get('last_project_name', 'N/A')}")
        st.markdown(f"**Test cases in session:** {len(st.session_state['last_result']['test_cases'])}")
        if st.button("🔍 Review Coverage", key="review_session_btn"):
            _run_review(
                st.session_state.get("last_requirement_text", ""),
                st.session_state["last_config"],
                st.session_state["last_result"]["test_cases"],
            )

with upload_tab:
    st.info("Upload support is added in a later task.")

if "review_result" in st.session_state:
    _render_review_result(st.session_state["review_result"])
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_reviewer_page.py`
Expected: 2 passed

- [ ] **Step 10: Run the full suite**

Run: `.venv/Scripts/pytest.exe -q`
Expected: all passing

- [ ] **Step 11: Commit**

```bash
git add pages/1_Reviewer.py tests/test_reviewer_page.py
git commit -m "Add Reviewer page skeleton with review-from-session flow"
```

---

## Task 9: Upload tab — file upload + AI-assisted column mapping

**Files:**
- Modify: `pages/1_Reviewer.py`
- Modify: `tests/test_reviewer_page.py`

**Interfaces:**
- Consumes: `core.file_import.parse_uploaded_file`/`FileImportError` (Task 1), `core.review_utils.apply_column_mapping` (Task 2), `core.ai_client.AIClient.suggest_column_mapping` (Task 7), `core.prompt_builder.load_column_mapping_prompt`/`list_available_configs`/`load_project_config` (Task 4, existing), `core.result_utils.TEST_CASE_FIELDS` (existing).
- Produces: same `_run_review` call as Task 8, now also reachable from the upload path.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reviewer_page.py`:

```python
import io

import openpyxl


FAKE_MAPPING = {
    "mapping": {
        "test_id": "ID", "module": "Module", "title": "Title", "precondition": "Precondition",
        "steps": "Steps", "test_data": "Data", "expected_result": "Expected",
        "priority": "Priority", "type": "Type", "platform": "Platform",
    }
}


def _make_xlsx_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Module", "Title", "Precondition", "Steps", "Data", "Expected", "Priority", "Type", "Platform"])
    ws.append(["TC_001", "Login", "Login works", "Account exists", "1. Login", "Valid user", "Home shown", "High", "Positive", "Web"])
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_review_from_uploaded_file_shows_coverage_report(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    with patch.object(AIClient, "suggest_column_mapping", return_value=FAKE_MAPPING), \
         patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)
        at.selectbox(key="upload_project_select").select("example_ecommerce").run(timeout=30)
        at.text_area(key="upload_requirement_text").set_value("As a user, I want to log in").run(timeout=30)
        at.button(key="review_upload_btn").click().run(timeout=30)

    assert not at.exception
    assert at.session_state["review_result"]["coverage_score"] == 72


def test_upload_review_button_enables_once_mapping_is_confirmed(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    with patch.object(AIClient, "suggest_column_mapping", return_value=FAKE_MAPPING):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)

    assert not at.exception
    assert at.button(key="review_upload_btn").disabled is False


def test_upload_review_button_disabled_when_mapping_incomplete(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    at.run(timeout=30)

    incomplete_mapping = {"mapping": {**FAKE_MAPPING["mapping"], "expected_result": ""}}
    with patch.object(AIClient, "suggest_column_mapping", return_value=incomplete_mapping):
        at.file_uploader(key="upload_file").upload(
            "cases.xlsx", _make_xlsx_bytes(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ).run(timeout=30)

    assert not at.exception
    assert at.button(key="review_upload_btn").disabled is True
    assert any("Map every field" in w.value for w in at.warning)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/pytest.exe -q tests/test_reviewer_page.py -k upload`
Expected: FAIL — `KeyError` (no `upload_file`/`upload_project_select`/`upload_requirement_text`/`review_upload_btn` elements yet)

- [ ] **Step 3: Write the implementation**

In `pages/1_Reviewer.py`, change the imports at the top from:

```python
from core.ai_client import AIClient
from core.prompt_builder import REVIEWER_PROMPT_PATH, build_system_prompt
```

to:

```python
from core.ai_client import AIClient
from core.file_import import FileImportError, parse_uploaded_file
from core.prompt_builder import (
    REVIEWER_PROMPT_PATH,
    build_system_prompt,
    list_available_configs,
    load_column_mapping_prompt,
    load_project_config,
)
from core.result_utils import TEST_CASE_FIELDS
from core.review_utils import apply_column_mapping
```

Replace the `with upload_tab: st.info(...)` block with:

```python
with upload_tab:
    uploaded_file = st.file_uploader("Upload test cases", type=["xlsx", "csv"], key="upload_file")
    available_configs = list_available_configs(CONFIGS_DIR)
    upload_project = st.selectbox("Project", available_configs, key="upload_project_select")
    upload_requirement = st.text_area(
        "Requirement this test set should cover",
        height=150,
        key="upload_requirement_text",
    )

    if uploaded_file is not None:
        try:
            raw_rows = parse_uploaded_file(uploaded_file)
        except FileImportError as e:
            st.error(str(e))
            raw_rows = None

        if raw_rows:
            if st.session_state.get("mapped_file_name") != uploaded_file.name:
                try:
                    client = AIClient(api_key=st.session_state.get("api_key") or None)
                    headers = list(raw_rows[0].keys())
                    suggestion = client.suggest_column_mapping(
                        load_column_mapping_prompt(), headers, raw_rows[:5]
                    )
                    st.session_state["column_mapping_suggestion"] = suggestion["mapping"]
                except ValueError as e:
                    st.error(f"Could not get a column mapping suggestion: {e}")
                    st.session_state["column_mapping_suggestion"] = {}
                st.session_state["mapped_file_name"] = uploaded_file.name

            st.markdown("**Confirm column mapping:**")
            headers = list(raw_rows[0].keys())
            header_options = [""] + headers
            suggestion = st.session_state.get("column_mapping_suggestion", {})
            confirmed_mapping = {}
            for field in TEST_CASE_FIELDS:
                suggested = suggestion.get(field, "")
                default_index = header_options.index(suggested) if suggested in header_options else 0
                confirmed_mapping[field] = st.selectbox(
                    field, header_options, index=default_index, key=f"mapping_{field}"
                )

            mapping_complete = all(confirmed_mapping.values())
            if not mapping_complete:
                st.warning("Map every field above before reviewing.")

            if st.button("🔍 Review Coverage", key="review_upload_btn", disabled=not mapping_complete):
                if not upload_requirement.strip():
                    st.warning("Please enter the requirement text first.")
                else:
                    normalized = apply_column_mapping(raw_rows, confirmed_mapping)
                    project_config = load_project_config(CONFIGS_DIR / f"{upload_project}.yaml")
                    _run_review(upload_requirement, project_config, normalized)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_reviewer_page.py`
Expected: 5 passed

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/pytest.exe -q`
Expected: all passing

- [ ] **Step 6: Commit**

```bash
git add pages/1_Reviewer.py tests/test_reviewer_page.py
git commit -m "Add upload-with-column-mapping flow to the Reviewer page"
```

---

## Task 10: Generate missing cases + merge + export

**Files:**
- Modify: `pages/1_Reviewer.py`
- Modify: `tests/test_reviewer_page.py`

**Interfaces:**
- Consumes: `core.ai_client.AIClient.generate_missing_cases` (Task 6), `core.review_utils.merge_test_cases` (Task 3), `core.prompt_builder.BASE_PROMPT_PATH` (existing), `core.excel_exporter.export_to_excel` (existing).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_reviewer_page.py`:

```python
FAKE_MISSING_CASES = {
    "test_cases": [
        {
            "test_id": "TC_LOGIN_001", "module": "Login", "title": "OTP resend works",
            "precondition": "OTP expired", "steps": "1. Request resend", "test_data": "n/a",
            "expected_result": "New OTP sent", "priority": "High", "type": "Negative", "platform": "Web",
        }
    ],
    "summary": {"total": 1, "by_type": {"negative": 1}, "open_questions": []},
    "usage": {"model": "claude-sonnet-5", "estimated_cost_usd": 0.0005},
}


def test_generate_missing_cases_and_merge(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    at = AppTest.from_file(str(PAGE_PATH))
    _seed_session_state(at)
    at.run(timeout=30)

    with patch.object(AIClient, "review_test_cases", return_value=FAKE_REVIEW):
        at.button(key="review_session_btn").click().run(timeout=30)

    with patch.object(AIClient, "generate_missing_cases", return_value=FAKE_MISSING_CASES):
        at.button(key="generate_missing_btn").click().run(timeout=30)

    assert not at.exception
    assert len(at.session_state["generated_missing_cases"]) == 1

    at.button(key="merge_btn").click().run(timeout=30)

    assert not at.exception
    # The seeded existing case and the generated one both use test_id
    # "TC_LOGIN_001" — this exercises merge_test_cases' collision rename.
    merged_ids = [tc["test_id"] for tc in at.session_state["review_test_cases"]]
    assert merged_ids == ["TC_LOGIN_001", "TC_LOGIN_001_2"]
    assert at.session_state["merged_result"]["test_cases"][1]["title"] == "OTP resend works"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/pytest.exe -q tests/test_reviewer_page.py -k generate_missing_cases_and_merge`
Expected: FAIL — `KeyError` (no `generate_missing_btn`/`merge_btn` elements yet)

- [ ] **Step 3: Write the implementation**

In `pages/1_Reviewer.py`, change the imports from:

```python
from core.ai_client import AIClient
from core.file_import import FileImportError, parse_uploaded_file
from core.prompt_builder import (
    REVIEWER_PROMPT_PATH,
    build_system_prompt,
    list_available_configs,
    load_column_mapping_prompt,
    load_project_config,
)
from core.result_utils import TEST_CASE_FIELDS
from core.review_utils import apply_column_mapping
```

to:

```python
import pandas as pd
import streamlit as st

from core.ai_client import AIClient
from core.excel_exporter import export_to_excel
from core.file_import import FileImportError, parse_uploaded_file
from core.prompt_builder import (
    BASE_PROMPT_PATH,
    REVIEWER_PROMPT_PATH,
    build_system_prompt,
    list_available_configs,
    load_column_mapping_prompt,
    load_project_config,
)
from core.result_utils import TEST_CASE_FIELDS
from core.review_utils import apply_column_mapping, merge_test_cases
```

(Note: `import streamlit as st` was already present earlier in the file — keep only one; this listing shows the full consuming set for clarity. Do not duplicate the `streamlit`/`dotenv` imports already at the top of the file.)

Replace the final block:

```python
if "review_result" in st.session_state:
    _render_review_result(st.session_state["review_result"])
```

with:

```python
if "review_result" in st.session_state:
    review = st.session_state["review_result"]
    _render_review_result(review)

    if review["gaps"]:
        if st.button("✨ Generate missing cases", key="generate_missing_btn"):
            try:
                client = AIClient(api_key=st.session_state.get("api_key") or None)
            except ValueError as e:
                st.error(str(e))
                st.stop()

            system_prompt = build_system_prompt(st.session_state["review_config"], base_prompt_path=BASE_PROMPT_PATH)
            with st.status("Generating missing test cases...", expanded=False) as status:
                try:
                    generated = client.generate_missing_cases(
                        system_prompt,
                        st.session_state["review_requirement_text"],
                        review["gaps"],
                    )
                except ValueError as e:
                    status.update(label=f"Error: {e}", state="error")
                    st.error(f"Error calling the AI: {e}")
                    st.stop()
                status.update(label="Done", state="complete")
            st.session_state["generated_missing_cases"] = generated["test_cases"]

    if st.session_state.get("generated_missing_cases"):
        st.subheader("✏️ Suggested new test cases")
        df = pd.DataFrame(st.session_state["generated_missing_cases"])
        edited_df = st.data_editor(
            df, key="missing_cases_editor", use_container_width=True, hide_index=True, num_rows="dynamic"
        )

        if st.button("➕ Merge into main set", key="merge_btn"):
            merged = merge_test_cases(
                st.session_state["review_test_cases"],
                edited_df.to_dict("records"),
            )
            st.session_state["review_test_cases"] = merged
            st.session_state["merged_result"] = {
                "test_cases": merged,
                "summary": {"total": len(merged), "by_type": {}, "open_questions": []},
            }
            st.session_state.pop("generated_missing_cases", None)
            st.success(f"Merged. The set now has {len(merged)} test cases.")

    if st.session_state.get("merged_result"):
        excel_bytes = export_to_excel(st.session_state["merged_result"])
        st.download_button(
            "⬇️ Download merged set (Excel)",
            data=excel_bytes,
            file_name="reviewed_testcases.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_merged_btn",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/pytest.exe -q tests/test_reviewer_page.py`
Expected: 6 passed

- [ ] **Step 5: Run the full suite**

Run: `.venv/Scripts/pytest.exe -q`
Expected: all passing (should be 28 original + ~25 new = ~53 tests; exact count isn't load-bearing, "no failures" is)

- [ ] **Step 6: Manual smoke test**

Run: `.venv/Scripts/python.exe -m streamlit run app.py --server.headless true --server.port 8770` in the background, then `curl -s -o /dev/null -w "%{http_code}" http://localhost:8770/Reviewer` (or navigate via the sidebar in a browser) to confirm the page loads without a server-side exception. Stop the server afterward.

- [ ] **Step 7: Update README**

In `README.md`, update the roadmap checklist item for Phase 2 from:

```markdown
- [ ] Phase 2: Test Case Reviewer / Coverage Checker
```

to:

```markdown
- [x] Phase 2: Test Case Reviewer / Coverage Checker
```

- [ ] **Step 8: Commit**

```bash
git add pages/1_Reviewer.py tests/test_reviewer_page.py README.md
git commit -m "Add gap-filling generation, merge, and export to the Reviewer page"
```

---

## Post-plan checklist (not a task — do once all tasks above are complete)

- [ ] Run the full suite one final time: `.venv/Scripts/pytest.exe -q`
- [ ] `git push origin main` (rebase onto `origin/main` first if it has moved)
- [ ] Confirm GitHub Actions CI is green on the pushed commits
- [ ] Manually try the Reviewer page against a real (non-mocked) requirement + generated test set, and separately against a real uploaded `.xlsx`, to sanity-check the AI's actual review quality — the automated tests only prove the plumbing, not prompt quality
