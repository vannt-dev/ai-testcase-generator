# AI Test Case Generator

[![Tests](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml)

**[Live demo](https://ai-testcase-gen.streamlit.app/)** · **[Demo page](https://vannt-dev.github.io/ai-testcase-generator/)**

A tool that helps **manual testers** generate test cases from a
requirement/user story, review an existing test set for coverage gaps and
duplicates, generate the missing cases, and export a ready-to-use Excel file.
It uses Claude and is designed to be **applicable to any project** — just add
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

## Architecture

```
Generator or Reviewer workflow
            +
Shared Core Engine + task-specific prompt
            +
Project Config (YAML)
            =
Project-aware test cases and coverage reports
```

## Directory structure

```
ai-testcase-generator/
├── app.py                       # Generator page and session history
├── pages/
│   └── 1_Reviewer.py            # Coverage review, gap generation, merge/export
├── core/
│   ├── ai_client.py              # Calls the Claude API (retry, pricing, structured output)
│   ├── file_import.py            # Safely parses uploaded .xlsx/.csv files
│   ├── prompt_builder.py         # Builds Generator/Reviewer prompts + project config
│   ├── review_utils.py           # Column mapping and collision-safe merging
│   ├── result_utils.py           # Normalizes/recomputes the summary on user edits
│   └── excel_exporter.py         # Exports results to .xlsx
├── configs/
│   ├── _template.yaml            # Copy this file when adding a new project
│   └── example_ecommerce.yaml    # Sample config
├── prompts/
│   ├── base_system_prompt.md     # Generates complete test cases
│   ├── reviewer_system_prompt.md # Reviews coverage without rewriting cases
│   └── column_mapping_system_prompt.md
├── tests/                        # pytest (core logic + both Streamlit pages)
├── .github/workflows/tests.yml   # CI: runs pytest on every push/PR
└── docs/
    └── how-to-add-new-project.md
```

## Setup

Requires Python >= 3.10 (the code uses the `str | None` type hint syntax).

```bash
git clone --branch v0.1.0 --depth 1 https://github.com/vannt-dev/ai-testcase-generator.git
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

## Try it out

```bash
streamlit run app.py
```

Open your browser at `http://localhost:8501`.

### Generate test cases

1. Select a project in the sidebar (defaults to `example_ecommerce`)
2. Paste a requirement/user story into the text box
3. Click **Generate Test Cases**
4. Edit the result table and download the Excel file

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

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI (GitHub Actions) automatically runs the full test suite on every
push/PR to `main`. Release 0.1.0 includes 106 tests.

## Releases and upgrades

Version **0.1.0** is distributed as a Streamlit application, not a PyPI library.
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
  `ANTHROPIC_API_KEY` environment variable on the server/secrets manager
  and hide/remove that input field, to avoid leaking the key through
  another user's session or browser logs.
- Uploaded files are limited to 10 MiB, 500 data rows, 256 columns, and
  131,072 characters per field (the CSV parser may impose a lower field limit).
  Ambiguous headers, malformed rows, and lazy Excel parsing errors produce
  import errors. Exported text, including generated/editor values and summary
  questions, stays literal even when it begins with a spreadsheet formula prefix.

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
- [ ] Phase 3: AI-assisted Bug Report Writer + Jira integration
- [ ] Phase 4: Expand into automation (self-healing scripts, generated test code)

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
