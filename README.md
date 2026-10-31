# AI Test Case Generator

[![Tests](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml)

**[Live demo](https://ai-testcase-gen.streamlit.app/)** · **[Demo page](https://vannt-dev.github.io/ai-testcase-generator/)**

A free, open-source (MIT) tool that helps **manual testers** write test cases
from a requirement or user story and export them to an **Excel file** they can
work from directly: one row per test case with steps, test data, expected
result and priority. You use **your own API key** for Claude (the default),
OpenAI or Google Gemini, or a **local model server** such as Ollama or LM
Studio, which needs no key. It can also review an existing test set for
coverage gaps and duplicates and generate the missing cases, and it is designed
to be **applicable to any project** — just add one config file, no code changes
needed.

## Why use this tool

- Cuts down time spent writing test cases by hand
- Improves coverage: the AI often comes up with edge/negative cases that
  humans tend to miss
- Standardizes test case format across team members
- Easy to extend to different projects thanks to a decoupled config system
- Automatically retries transient errors (rate limit, server error, connection loss)
  from whichever AI provider is chosen, with increasing waits
- Shows the tokens used on the Generator, Bug Reporter, Automation and Heal Locators
  pages; the cost in USD is estimated for the Claude models priced in the app (see
  [Other AI providers](#other-ai-providers))
- Reads requirement documents (`.docx`, `.pdf`, `.md`, `.txt`) or a `.csv` backlog of
  user stories, generates each section separately and merges the results into one set
- Links each test case to the acceptance criteria it covers, and shows which
  criteria have no test case yet (in the app, the Excel file and as Gherkin tags)
- Keeps a per-session history of generation runs to review/restore later
- Reviews either the current generated set or an uploaded `.xlsx`/`.csv`
- Suggests and lets the user confirm column mappings for external files
- Scores coverage, flags gaps/duplicates, and generates cases for selected gaps
- Turns web test cases into a runnable Playwright + TypeScript project (page objects, specs, zip download)
- Writes API test cases for projects that list `api` as a platform, and turns them into Playwright API tests in the same project
- Repairs broken locators in a Playwright page object from the error and the page's current HTML, and shows a diff before you download

## Architecture

```
Generator, Reviewer, Bug Reporter or Automation workflow
            +
Shared Core Engine + task-specific prompt
            +
Project Config (YAML)
            =
Project-aware test cases, coverage reports, bug reports and Playwright web and API tests
```

## Directory structure

```
ai-testcase-generator/
├── app.py                       # Generator page and session history
├── pages/
│   ├── 1_Reviewer.py            # Coverage review, gap generation, merge/export
│   ├── 2_Bug_Reporter.py        # Bug reports from rough notes, Markdown/Excel export
│   ├── 3_Automation.py          # Playwright project from web and API test cases
│   └── 4_Heal_Locators.py       # Repairs broken locators in a page object
├── core/
│   ├── ai_client.py              # Calls the AI provider (retry, pricing, structured output)
│   ├── ai_providers.py           # The providers and what each needs (key, model, address)
│   ├── ai_sidebar.py             # The sidebar block that chooses the provider, on every page
│   ├── file_import.py            # Safely parses uploaded .xlsx/.csv files
│   ├── requirement_import.py     # Reads requirement files and splits them into sections
│   ├── batch_generation.py       # Generates per section and merges into one suite
│   ├── prompt_builder.py         # Builds Generator/Reviewer prompts + project config
│   ├── review_utils.py           # Column mapping and collision-safe merging
│   ├── revision.py               # Checks and merges a revision of selected test cases
│   ├── result_utils.py           # Normalizes/recomputes the summary on user edits
│   ├── excel_exporter.py         # Exports results to .xlsx
│   ├── gherkin_exporter.py       # Exports results to a Gherkin .feature file
│   ├── traceability.py           # Maps acceptance criteria to the test cases covering them
│   ├── bug_exporters.py          # Bug report Markdown/Excel export
│   ├── bug_batch.py              # Bug reports from the failed rows of a test run
│   ├── automation_inputs.py      # Checks Automation page input before the AI call
│   ├── automation_validate.py    # Cleans AI automation output (names, references)
│   ├── playwright_renderer.py    # Renders page objects, specs and the project zip
│   ├── api_automation_validate.py # Cleans AI API automation output (requests, variables)
│   ├── api_renderer.py           # Renders API specs and their support file
│   └── locator_healing.py        # Finds, validates and patches page object locators
├── configs/
│   ├── _template.yaml            # Copy this file when adding a new project
│   ├── example_ecommerce.yaml    # Sample config
│   └── example_rest_api.yaml     # Sample config for an API project
├── prompts/
│   ├── base_system_prompt.md     # Generates complete test cases
│   ├── reviewer_system_prompt.md # Reviews coverage without rewriting cases
│   ├── revise_system_prompt.md   # Rewrites selected test cases from a tester's note
│   ├── column_mapping_system_prompt.md
│   ├── bug_report_system_prompt.md # Writes one bug report from notes
│   ├── run_column_mapping_system_prompt.md
│   ├── automation_system_prompt.md # Turns web test cases into Playwright steps
│   ├── api_automation_system_prompt.md # Turns API test cases into request steps
│   └── locator_healing_system_prompt.md # Repairs broken locators, flags possible bugs
├── scripts/render_automation_fixture.py # Renders the fixture project CI type-checks
├── tests/                        # pytest (core logic + all Streamlit pages)
├── .github/workflows/tests.yml   # CI: pytest, plus tsc on a generated Playwright project
└── docs/
    └── how-to-add-new-project.md
```

## Setup

Requires Python >= 3.10 (the code uses the `str | None` type hint syntax).

```bash
git clone --branch v0.6.0 --depth 1 https://github.com/vannt-dev/ai-testcase-generator.git
cd ai-testcase-generator
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Get an API key from your AI provider (for Claude, the default:
https://console.anthropic.com/), then:

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY, or another provider's settings (see below), in the .env file
```

(Or skip this step and enter the API key directly in the sidebar when
running the app.)

### Other AI providers

Claude is the default, and the provider the prompts were written and tried
with. The sidebar's **AI provider** list offers three more; each needs a
model name, typed in the sidebar or set in `.env`:

| Provider | Key | Model | Address |
| --- | --- | --- | --- |
| Claude (Anthropic) | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL`, optional (default `claude-sonnet-5`) | |
| OpenAI | `OPENAI_API_KEY` | `OPENAI_MODEL` | |
| Google Gemini | `GEMINI_API_KEY` | `GEMINI_MODEL` | |
| OpenAI-compatible server (Ollama, LM Studio, OpenRouter, ...) | `AI_API_KEY`, only if the server needs one | `AI_MODEL` | `AI_BASE_URL`, for example `http://localhost:11434/v1` |

`AI_PROVIDER` (`anthropic`, `openai`, `gemini` or `compatible`) sets which
one the sidebar starts on. A key typed for one provider is kept apart from
the others and is never sent to them.

The three other providers are reached through the OpenAI chat-completions
format. The app asks for JSON that follows the result's schema, falls back to
plain JSON mode on a server that does not know schema-constrained output, and
checks every reply against the schema before using it, so a model that cannot
keep to the structure fails with a message that names the field instead of
producing a broken table. Expect the quality of test cases, reviews and
generated automation to vary with the model: a small local model may need
several tries. The token counts are shown for every provider; the cost in USD is
estimated only for Claude models listed in `MODEL_PRICING` (`core/ai_client.py`,
currently `claude-sonnet-5`) and shows as N/A for any other model.

With a local server such as Ollama nothing leaves your machine.

## Try it out

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

### Generate test cases

1. Select a project in the sidebar (defaults to `example_ecommerce`)
2. Paste a requirement/user story into the text box, or upload a file on the **Upload a file**
   tab (see below)
3. Click **Generate Test Cases**
4. Edit the result table and download the Excel file, or a Gherkin `.feature` file with one
   `Scenario` per test case for Cucumber, Behave, SpecFlow or pytest-bdd

The AI lists the requirement's acceptance criteria first, keeping ids the text already
gives (`AC-1`, `REQ-12`...) or numbering them `AC-1`, `AC-2`..., and fills each test
case's **Covers** column with the criteria it verifies. The **Traceability** panel under
the table, and the **Traceability** sheet of the Excel file, list the test cases for each
criterion and flag a criterion that has none. In the `.feature` file each scenario is
tagged with its criteria (`@AC-1`), so `--tags @AC-1` runs one criterion's scenarios.
Edit the Covers cells (comma-separated) to fix a link; the panel follows your edits.

#### Revise selected test cases

To have the AI rework some cases instead of editing them by hand, open **Revise selected
test cases with AI** under the table, pick the test ids (up to 20), and write what should
change, for example "add negative cases for an empty email" or "steps too vague, split
step 3". Click **Revise selected**: the AI gets those cases as they are in the table (with
your edits), the requirement and the acceptance criteria, and rewrites only them. Every
selected case comes back under its own test id; new cases the note asks for get ids no case
in the set uses (a clash becomes `_2`, `_3`...) and are placed after the last selected case.
The other cases are not sent and stay exactly as they were.

The proposal is shown before and after, with any questions the AI raised. **Accept
revision** puts it in the table and adds it to the session history, so **Restore** on the
earlier entry undoes it; **Discard revision** drops it. Nothing changes until you accept: an
AI error, or a reply that leaves out, renames or repeats a selected case, is shown as an
error and the table stays as it was. Edit the table after revising and the proposal can no
longer be accepted; discard it and revise again. To delete a case, delete its row. This
works with every AI provider in the sidebar; a requirement longer than 40,000 characters
(a large uploaded file) is cut to that length for the revision.

#### From a requirement file

On the **Upload a file** tab, upload a Word (`.docx`), PDF, Markdown or text file, or a
`.csv` backlog with one user story per row (Jira and Azure DevOps exports work; an
`Issue key`/`ID` and `Summary`/`Title` column name each story). The file is split into
sections:

- Word: at its heading styles (Heading 1, Heading 2...); tables and lists are kept.
- Markdown and text: at `#` headings.
- PDF: at its bookmarks; a PDF without bookmarks is split by size only, and a scanned PDF
  has no text to read.
- CSV: one section per row.

The split uses the highest heading level that occurs more than once, so a document whose
only Heading 1 is its title splits at its Heading 2s; a section over 40,000 characters is
cut at paragraphs. Untick the sections that need no test cases, then generate: each section
is one AI call (up to 50 per run), with a progress bar. The results are merged into one set:
test ids that collide get `_2`, `_3`..., criterion ids that two sections share are prefixed
with the section (`S2.AC-1`, or the story's key such as `US-12.AC-1`), and open questions
name their section. A section that fails is listed with its error while the others stay in
the result; **Retry failed sections** runs only those again.

### Review coverage

1. Open **Reviewer** in Streamlit's page navigation
2. Choose the current generated set, or upload an `.xlsx`/`.csv` file
3. For uploads, select a project, enter the source requirement, and confirm
   the AI-suggested column mapping
4. Click **Review Coverage** to see the score, missing test types, gaps, and
   possible duplicate cases
5. Generate suggested missing cases, edit them, merge them into the original
   set, and download the merged Excel file

The live Reviewer page is available at
**[ai-testcase-gen.streamlit.app/Reviewer](https://ai-testcase-gen.streamlit.app/Reviewer)**.

### Write a bug report

1. Open **Bug Reporter** in Streamlit's page navigation (tab **From notes**)
2. Select a project and paste your rough notes about the defect; optionally
   paste the related test case (JSON or plain text)
3. Click **Write bug report**; answer any open questions the AI lists
4. Edit the fields, then copy the Markdown or download `.md`/`.xlsx`

The Markdown pastes into GitHub, GitLab, Azure DevOps and Jira Cloud.

### Write bug reports from a test run

1. Open **Bug Reporter** and the **From a test run** tab
2. Upload the executed test run (`.xlsx`/`.csv`) and confirm the AI-suggested
   columns: status and actual result are required; a tester comment column and
   the test case columns are optional context
3. Check which status values count as failed (`Failed`, `NG`, `Không đạt`… are
   pre-selected; `Blocked` and `Not run` are not defects)
4. Click **Write N bug report(s)** (up to 50 per run), adjust titles, severity
   and priority in the summary, and download one `.xlsx` or `.md` with every report

Each report records its source (the file and the row number the spreadsheet
shows) and covers the core defect report fields of ISTQB and ISO/IEC/IEEE
29119-3, including reproducibility and build/version. Evidence such as logs,
screenshots and recordings is attached in the tracker, which also assigns the
ID, date, reporter and status.

### Generate Playwright tests

1. Open **Automation** in Streamlit's page navigation
2. Use the test cases from this session or upload a `.xlsx`/`.csv` (test ID,
   title, steps and expected result are required columns); only Web/All
   cases are listed, and up to 10 are automated per run
3. Enter the Base URL of the app under test and, optionally, each page's name,
   path and HTML or ARIA snapshot — with a snapshot the AI picks locators that
   exist; without one it infers them and marks each for review
4. Click **Generate Playwright project**, preview the files and download the zip
5. In the unzipped folder: `npm install`, `npx playwright install`,
   `cp .env.example .env` (fill in passwords and tokens), then `npm test`

Steps the AI cannot express become `test.fixme` with a TODO, and the
project's README lists every test and locator that still needs a human.

### Generate API tests

1. Use a project whose config lists `api` under `platform`
   (`configs/example_rest_api.yaml` is a sample). The Generator then writes
   API test cases: steps as `METHOD /path`, test data with headers and body,
   and an expected result with the status code and response fields.
2. On the **Automation** page, API cases appear next to web cases with their
   kind; choose up to 10 of each.
3. Enter the **API base URL** and, optionally, paste an **API description**
   (an endpoint list or an OpenAPI excerpt). With it the AI uses the real
   endpoints; without it each request is marked for review.
4. Generate. API tests land in `tests/api/` of the same project and use
   Playwright's `request` fixture; `npx playwright test tests/api` runs only
   them. Tokens and keys are read from `.env` (`${ENV:NAME}` placeholders),
   and an id returned by one request can feed the next.

Anything a request cannot express — an email, a database check, a file
upload — becomes `test.fixme` with a TODO.

### Heal broken locators

1. Open **Heal Locators** in Streamlit's page navigation
2. Upload the failing page object (`pages/<Name>.ts` from the generated project,
   hand-edited files work too), paste the Playwright error and the page's current
   HTML or ARIA snapshot
3. Click **Heal locators**, read the verdict, untick any fix you don't want and
   download the patched file

Only the locator lines change; each healed line gets a `// healed:` comment.
When the AI says the element is gone or the app's behaviour changed, check the
app before touching the test: it may be a real bug.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI (GitHub Actions) automatically runs the full test suite on every
push/PR to `main`. Release 0.6.0 includes 486 tests.

## Releases and upgrades

Version **0.6.0** is distributed as a Streamlit application, not a PyPI library.
Download the source archive from [GitHub Releases](https://github.com/vannt-dev/ai-testcase-generator/releases)
or use the versioned clone command above, install `requirements.txt`, then run `streamlit run app.py`.
For an upgrade, use a fresh checkout of the selected tag and copy only your own project YAML
configuration into `configs/`. Keep API keys in your local environment or the sidebar, outside Git.

The hosted demo may update independently of a tagged release. The sidebar identifies the running
application version. See [CHANGELOG.md](CHANGELOG.md) for changes and upload limits.

## Security

- The API key entered in the sidebar only lives in `st.session_state`
  for the current browser session — it's never written to disk or logged.
- If deploying this app somewhere public (Streamlit Cloud, a shared
  server...), **do not** rely on the UI's API key field — set the
  `ANTHROPIC_API_KEY` environment variable (or the chosen provider's own) on the server/secrets manager
  and hide/remove that input field, to avoid leaking the key through
  another user's session or browser logs.
- Requirement files on the Generator are sent to the chosen AI provider section by section,
  like pasted text; they are limited to 10 MiB, and a PDF to 500 pages.
- Uploaded files are limited to 10 MiB, 500 data rows, 256 columns, and
  131,072 characters per field (the CSV parser may impose a lower field limit).
  Ambiguous headers, malformed rows, and lazy Excel parsing errors produce
  import errors. Exported text, including generated/editor values and summary
  questions, stays literal even when it begins with a spreadsheet formula prefix.
- Page HTML/ARIA snapshots pasted on the Automation page are sent to
  the chosen AI provider (Anthropic by default) with the test cases; remove tokens and personal data first. The
  Heal Locators page sends the pasted error and snapshot the same way. The
  Base URL stays local: it is written to `playwright.config.ts` only. The AI is
  told to write passwords and tokens as `${ENV:NAME}`, read from `.env`; still
  review the generated test data before sharing the project.

## Adding your own project

See the detailed guide at
[`docs/how-to-add-new-project.md`](docs/how-to-add-new-project.md).
Quick summary:

```bash
cp configs/_template.yaml configs/your_project_name.yaml
# Fill in domain rules, glossary, platform... for your project
```

## Roadmap

- [x] Phase 1: Generate test cases from a requirement
- [x] Phase 2: Test Case Reviewer / Coverage Checker
- [x] Phase 3, step 1: Bug Report Writer with tracker-neutral Markdown/Excel export
- [x] Phase 3, step 2: Bug reports from the failed rows of an executed test run
- [x] Phase 4, step 1: Playwright + TypeScript project generated from web test cases
- [x] Phase 4, step 2: Self-healing — repair locators from a failing test's error and fresh HTML
- [x] Phase 5: API test cases from a requirement, and Playwright API tests from them

## Notes

- The AI will ask for clarification instead of guessing if the
  requirement is missing important information — if you see an
  "Needs confirmation from BA/Dev" section appear, add the missing
  details and run it again.
- Test case quality depends heavily on the quality of `domain_rules`
  in the config file — it's worth investing time to flesh out the
  config for each project.

## License

[MIT](LICENSE)
