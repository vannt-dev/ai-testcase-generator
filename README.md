# AI Test Case Generator

[![Tests](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml)

**[Live demo](https://ai-testcase-gen.streamlit.app/)** · **[Demo page](https://vannt-dev.github.io/ai-testcase-generator/)**

A tool that helps **manual testers** generate test cases from a
requirement/user story, review an existing test set for coverage gaps and
duplicates, generate the missing cases, and export a ready-to-use Excel file.
It uses Claude by default, can use OpenAI, Google Gemini or a local model
server instead, and is designed to be **applicable to any project** — just add
one config file, no code changes needed.

## Why use this tool

- Cuts down time spent writing test cases by hand
- Improves coverage: the AI often comes up with edge/negative cases that
  humans tend to miss
- Standardizes test case format across team members
- Easy to extend to different projects thanks to a decoupled config system
- Automatically retries transient errors (rate limit, connection loss)
  from the Anthropic API
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
│   ├── prompt_builder.py         # Builds Generator/Reviewer prompts + project config
│   ├── review_utils.py           # Column mapping and collision-safe merging
│   ├── result_utils.py           # Normalizes/recomputes the summary on user edits
│   ├── excel_exporter.py         # Exports results to .xlsx
│   ├── gherkin_exporter.py       # Exports results to a Gherkin .feature file
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
git clone --branch v0.3.0 --depth 1 https://github.com/vannt-dev/ai-testcase-generator.git
cd ai-testcase-generator
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Get an Anthropic API key at https://console.anthropic.com/, then:

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY in the .env file
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
several tries. Cost is estimated for Claude only.

With a local server such as Ollama nothing leaves your machine.

## Try it out

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

### Generate test cases

1. Select a project in the sidebar (defaults to `example_ecommerce`)
2. Paste a requirement/user story into the text box
3. Click **Generate Test Cases**
4. Edit the result table and download the Excel file, or a Gherkin `.feature` file with one
   `Scenario` per test case for Cucumber, Behave, SpecFlow or pytest-bdd

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
push/PR to `main`. Release 0.3.0 includes 396 tests.

## Releases and upgrades

Version **0.3.0** is distributed as a Streamlit application, not a PyPI library.
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
