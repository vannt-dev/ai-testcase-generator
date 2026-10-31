# Changelog

## 0.7.0 - 2026-11-01

- The generation history now survives a restart. Each result is saved as a JSON file in a
  Git-ignored `history/` folder, which keeps the newest 50 runs. The sidebar list, now called
  **History**, shows the newest 10 and loads them when a session starts. **Restore** works as
  before. Timestamps include the date. A history file that can't be read is skipped with a
  warning, and a failed save only shows a warning; the result stays on screen.
  **Clear history** deletes the files after you confirm. `TESTCASE_HISTORY_DIR` moves the
  folder.
- When the AI call fails, the progress box now opens and shows the error. It used to stay
  collapsed, so only a short "Error" label was visible and messages such as "The table was
  not changed" were hidden. This applies to every page that calls the AI.

## 0.6.0 - 2026-10-31

- Revise selected test cases. Under the Generator's table, pick up to 20 test cases and write
  a note ("add negative cases for an empty email", "steps too vague, split step 3"); the AI
  rewrites only those, using the requirement and acceptance criteria, keeps their test ids,
  and gives any new case an unused id. The proposal is shown before and after and replaces
  the old cases only when you accept it (it is added to the session history, so Restore
  undoes it); the other cases stay exactly as they were. An AI error, or a reply that leaves
  out, renames or repeats a selected case, leaves the table untouched. Works with every AI
  provider.
- README and landing page: open with what sets the tool apart: free and MIT, your own
  API key or a local model server, and an Excel file manual testers can work from.

## 0.5.0 - 2026-10-21

- Traceability. The Generator lists the requirement's acceptance criteria, keeping the ids
  the text gives (`AC-1`, `REQ-12`...) or numbering them `AC-1`, `AC-2`..., and each test
  case names the criteria it covers in a new, editable **Covers** column. A panel under the
  table shows which test cases cover each criterion and warns about criteria with none. The
  Excel file gets a **Covers** column and a **Traceability** sheet that flags uncovered
  criteria in red; the Gherkin file tags each scenario with its criteria (`@AC-1`). The
  Reviewer takes the links into account when it looks for gaps. A reply without the links
  still works, without the panel and sheet.
- Requirement files. The Generator's new **Upload a file** tab reads a Word (`.docx`), PDF,
  Markdown or text document, or a `.csv` backlog with one user story per row, splits it into
  sections (headings, PDF bookmarks or rows, each under the 40,000-character limit) and
  generates test cases for each ticked section in turn, with a progress bar. The results are
  merged into one set with unique test ids and criterion links that stay correct across
  sections; a failed section is listed with its error, the finished ones are kept, and
  **Retry failed sections** runs only the failed ones. Pasting text works as before.
- Requires the `python-docx` and `pypdf` packages (`pip install -r requirements.txt`).
- README: retries and token counts apply to every AI provider; the USD cost estimate covers
  the Claude models priced in the app.

## 0.4.0 - 2026-10-10

- Other AI providers. The sidebar of every page has an **AI provider** list: Claude (the
  default), OpenAI, Google Gemini, or any server that speaks the OpenAI chat-completions
  format (Ollama, LM Studio, OpenRouter, ...), each with its own key, model name and, for a
  server, address; `.env` can hold them too (`AI_PROVIDER`, `OPENAI_*`, `GEMINI_*`, `AI_*`).
  Replies from these providers are checked against the same schemas as Claude's before they
  are used, and a reply that does not fit is reported with the field that is wrong. Cost is
  estimated for Claude only. Claude's model can now be changed in the sidebar or with
  `ANTHROPIC_MODEL`.
- Requires the `openai` package (`pip install -r requirements.txt`).

## 0.3.0 - 2026-10-08

- Generator: a **Download Gherkin (.feature)** button next to the Excel one. Each test case
  becomes a `Scenario` (precondition as `Given`, steps as `When`, expected result as `Then`),
  tagged with its test id, module, priority, type and platform; test data and the open
  questions are kept as comments. The conversion is mechanical and makes no AI call.

## 0.2.0 - 2026-10-05

- Require `streamlit>=1.50.0`. The tables use `width="stretch"` in place of the deprecated
  `use_container_width`, which older Streamlit versions do not accept.
- Bug reports from a test run: an unexpected error on one row no longer aborts the batch and
  loses the reports already written; each report's open questions are listed under the summary;
  and results that belong to another file, project, mapping or status selection are marked as
  such instead of looking current.
- Add API testing: a project config with `api` under `platform` makes the Generator write API
  test cases, and the Automation page turns up to 10 of them into Playwright API tests
  (`request` fixture) in the same project as the web tests. Paste an endpoint list or an OpenAPI
  excerpt for accurate requests; ids saved from one response feed later requests, secrets go to
  `.env`, and anything a request cannot express becomes a `test.fixme` with a TODO.
- Add the Heal Locators page: upload a failing Playwright page object with the error and the
  page's current HTML, and get only its broken locators repaired, with a verdict that flags
  possible app bugs, a per-fix choice, a diff, and a download that keeps every other line.
- Add the Automation page: turn up to 10 web test cases into a Playwright + TypeScript project
  with page objects, downloadable as a zip. Paste each page's HTML or ARIA snapshot for accurate
  locators; anything the AI cannot express becomes a `test.fixme` with a TODO instead of a guess.
  Secrets go to `.env` through `${ENV:NAME}` placeholders. CI type-checks a rendered fixture project.
- Add the Bug Reporter page: turn rough notes about a defect into a structured bug report
  (severity, priority, steps, expected/actual, open questions), edit it, and export it as
  Markdown or Excel. The AI asks for missing details instead of inventing them.
- Bug Reporter: a **From a test run** tab writes one bug report per failed row of an uploaded
  test run (up to 50 per run), with AI-suggested column mapping, editable summary, a list of
  rows that failed, and one Excel or Markdown download.
- Bug reports cover more of the ISTQB / ISO/IEC/IEEE 29119-3 defect report fields: new
  reproducibility and build/version fields, and a source (file and row) for batch reports.

## 0.1.2 - 2026-09-25

- Require `anthropic>=1.0.0`. The client and tests use the 1.x SDK (`httpx2`); the previous
  `>=0.83.0` floor allowed installs that could not run the test suite.

## 0.1.1 - 2026-09-24

- Keep uploaded review values literal. Values such as `-1`, `- Open the app` and `+84 ...` were
  previously stored with a leading `'`, corrupting the review prompt, editor and export. Excel
  export still writes every string as a literal text cell.
- Retry transient 5xx/overloaded API errors in the app's single retry loop; the SDK's own retries
  are disabled so one generation no longer makes up to 12 attempts.

## 0.1.0 - 2026-09-22

- First versioned public Streamlit application release, with configurable project requirements,
  test generation, editable results, session history, coverage review and Excel export.
- Review uploaded CSV/XLSX files, confirm column mappings, generate missing cases, and merge results.
- Export all text as literal Excel cells, including formula-like text and summary questions.
- Bound upload bytes, rows, columns and field lengths; report CSV/lazy-XLSX parsing errors in the UI.
  Limits are 10 MiB per file, 500 data rows, 256 columns, and 131,072 characters per field.
- Include 106 regression and Streamlit-page tests. AI generation requires an Anthropic API key;
  deterministic tests do not validate the quality of live model responses.

Install with Python 3.10+ and `pip install -r requirements.txt`, then `streamlit run app.py`.
Use a fresh tagged checkout when upgrading and retain your project YAML files separately.
