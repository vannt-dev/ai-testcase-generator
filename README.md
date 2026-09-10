# AI Test Case Generator

[![Tests](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml)

**[Live demo](https://ai-testcase-gen.streamlit.app/)** · **[Demo page](https://vannt-dev.github.io/ai-testcase-generator/)**

A tool that helps **manual testers** automatically generate test cases from
a requirement/user story using AI (Claude), and export them to a
ready-to-use Excel file. Designed to be **applicable to any project** —
just add one config file, no code changes needed.

## Why use this tool

- Cuts down time spent writing test cases by hand
- Improves coverage: the AI often comes up with edge/negative cases that
  humans tend to miss
- Standardizes test case format across team members
- Easy to extend to different projects thanks to a decoupled config system
- Automatically retries transient errors (rate limit, connection loss)
  from the Anthropic API
- Keeps a per-session history of generation runs to review/restore later

## Architecture

```
Core Engine (unchanged across projects)
        +
Project Config (YAML — changes per project)
        =
Test cases tailored to that project's domain/business rules
```

## Directory structure

```
ai-testcase-generator/
├── app.py                       # Main Streamlit UI
├── core/
│   ├── ai_client.py              # Calls the Claude API (retry, pricing, structured output)
│   ├── prompt_builder.py         # Merges the base prompt + project config
│   ├── result_utils.py           # Normalizes/recomputes the summary on user edits
│   └── excel_exporter.py         # Exports results to .xlsx
├── configs/
│   ├── _template.yaml            # Copy this file when adding a new project
│   └── example_ecommerce.yaml    # Sample config
├── prompts/
│   └── base_system_prompt.md     # Base prompt shared across all projects
├── tests/                        # pytest (core logic + app.py integration tests)
├── .github/workflows/tests.yml   # CI: runs pytest on every push/PR
└── docs/
    └── how-to-add-new-project.md
```

## Setup

Requires Python >= 3.10 (the code uses the `str | None` type hint syntax).

```bash
git clone <repo-url>
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

Open your browser at `http://localhost:8501`:
1. Select a project in the sidebar (defaults to `example_ecommerce`)
2. Paste a requirement/user story into the text box
3. Click **Generate Test Cases**
4. View the results as a table, download the Excel file

## Running tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI (GitHub Actions) automatically runs the full test suite on every
push/PR to `main`.

## Security

- The API key entered in the sidebar only lives in `st.session_state`
  for the current browser session — it's never written to disk or logged.
- If deploying this app somewhere public (Streamlit Cloud, a shared
  server...), **do not** rely on the UI's API key field — set the
  `ANTHROPIC_API_KEY` environment variable on the server/secrets manager
  and hide/remove that input field, to avoid leaking the key through
  another user's session or browser logs.

## Adding your own project

See the detailed guide at
[`docs/how-to-add-new-project.md`](docs/how-to-add-new-project.md).
Quick summary:

```bash
cp configs/_template.yaml configs/your_project_name.yaml
# Fill in domain rules, glossary, platform... for your project
```

## Roadmap

- [x] Phase 1: Generate test cases from a requirement (current MVP)
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
