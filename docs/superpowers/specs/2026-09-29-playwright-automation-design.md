# Playwright Test Generation — Design

Status: approved (design), pending implementation plan
Roadmap: Phase 4 of the project roadmap (README.md), step 1 of 2

## Purpose

Testers who already have manual test cases (from the Generator or from a
spreadsheet) want a starting point for automation. This step turns selected
web test cases into a runnable Playwright + TypeScript project that uses the
Page Object Model. It is meant as a starting point: when the AI cannot be
sure of something, the generated code says so with an explicit TODO or
`test.fixme` instead of guessing without saying so.

Step 2 (a later spec) adds self-healing. The user pastes a failing test's
error and fresh HTML, and the AI repairs the locators. Step 1 keeps the
locator model simple so that step 2 can reuse it.

## Decisions

- **Framework:** Playwright with `@playwright/test`, TypeScript.
- **Platform:** web only. Test cases whose `platform` is `iOS` or `Android`
  are excluded.
- **Locator source:** for each page, the user can paste HTML or a
  Playwright/DevTools ARIA snapshot. It is optional. Without it, the AI infers
  locators from the step text and marks them `confident: false`.
- **Output:** a downloadable `.zip` holding a complete project (config,
  package.json, page objects, specs).
- **Approach:** the AI returns structured JSON (pydantic `output_format`, the
  same as the other features). A deterministic Python renderer turns it into
  TypeScript. The AI never writes TypeScript source directly.

## Scope

**In scope:**
- A new page, `pages/3_Automation.py`.
- Input from the test cases in the session (`last_result`) or from an
  uploaded `.xlsx`/`.csv`. The upload goes through the existing
  `parse_uploaded_file` and the AI-suggested column mapping.
- Choosing up to 10 web test cases per generation. The call is non-streaming
  with the app's existing `max_tokens=16000`, which the Anthropic SDK
  recommends as the ceiling for non-streaming requests; 10 cases with page
  objects fit in that budget.
- Base URL, plus up to 10 pages (name, path, optional HTML/ARIA snapshot).
- A preview of the generated files and a zip download.

**Out of scope (step 1):**
- Self-healing or repairing tests (step 2).
- Editing the generated JSON or code in the UI.
- Running Playwright from the app. Mobile/Appium, Selenium, Cypress, Python output.
- Crawling a URL to capture the DOM automatically.

## Data model

Added to `core/ai_client.py` next to the existing models. All fields are
required; the AI sends empty strings for unused fields.

```python
class Locator(BaseModel):
    key: str            # camelCase, unique within the page, e.g. "emailInput"
    strategy: Literal["role", "label", "placeholder", "text", "test_id", "css"]
    role: str           # ARIA role, only when strategy == "role"
    value: str          # accessible name / label / text / test id / css selector
    confident: bool     # False -> "// TODO verify locator" in the output

class PageObject(BaseModel):
    name: str           # PascalCase, e.g. "LoginPage"
    path: str           # relative to baseURL, e.g. "/login"
    locators: list[Locator]

class Step(BaseModel):
    action: Literal["goto", "click", "fill", "select", "check", "uncheck",
                    "press", "expect_visible", "expect_hidden",
                    "expect_text", "expect_value", "expect_url", "todo"]
    page: str           # PageObject.name
    locator: str        # Locator.key
    value: str          # input text, expected text/url, key name
    source: str         # the original step sentence, rendered as a comment

class AutomatedTest(BaseModel):
    test_id: str        # matches TestCase.test_id
    title: str
    steps: list[Step]

class AutomationResult(BaseModel):
    pages: list[PageObject]
    tests: list[AutomatedTest]
    open_questions: list[str]
```

Which fields each action uses:

| action | page | locator | value |
|---|---|---|---|
| `goto` | required | — | — |
| `click`, `check`, `uncheck`, `expect_visible`, `expect_hidden` | required | required | — |
| `fill`, `select`, `expect_text`, `expect_value` | required | required | required |
| `press` | required | required | key name, e.g. `Enter` |
| `expect_url` | — | — | path or URL fragment |
| `todo` | — | — | — (`source` holds the step) |

**Secrets:** a password, OTP or token in `test_data` is not written as a
literal. The AI writes the value as `${ENV:NAME}`, where `NAME` matches
`[A-Z][A-Z0-9_]*`. The renderer emits `process.env.NAME ?? ''` and lists
`NAME` in `.env.example`.

## Validation (`core/automation_validate.py`)

`validate_automation(result: dict, modules: dict[str, str]) -> tuple[dict, list[str]]`
returns a cleaned result and a list of human-readable warnings. It never
raises on AI output. `modules` maps each selected `test_id` to its
`TestCase.module`; the validator copies it onto each test as `module` (empty
when unknown) so the renderer can group tests into files. It checks:

- Non-ASCII names (for example Vietnamese) are transliterated before
  sanitizing (`Đăng nhập` → `DangNhap`); a name with nothing left becomes
  `UnnamedPage` / `element`. Identifiers that collide with TypeScript
  reserved words or with the generated code's own names (`page`, `path`,
  `goto`, `constructor`; classes `Page`, `Locator`, `Test`, `Expect`) get a
  suffix.
- A `role` outside Playwright's ARIA role list falls back to
  `strategy = "text"` with `confident = False` and a warning, so the output
  always type-checks.
- Page names are sanitized to PascalCase identifiers and locator keys to
  camelCase identifiers. When sanitizing produces a clash, `2`, `3`, … is
  appended.
- Duplicate page names are merged: the first definition wins and a warning is
  recorded.
- A duplicate locator key within a page keeps the first definition and records a warning.
- A step whose `page`/`locator` does not exist, or that lacks a field the
  table above requires, is downgraded to `todo`. A warning such as
  `TC_003 step 4: unknown locator 'foo' on LoginPage` is recorded.
- A duplicate `test_id` gets `_2`, `_3`, … appended and a warning is recorded.
- A test with no steps gets a single `todo` step.
- `strategy == "role"` with an empty `role` falls back to `strategy = "text"`
  with `confident = False`.
- `${ENV:...}` with an invalid name is treated as a literal string.

## Renderer (`core/playwright_renderer.py`)

Pure Python with no Streamlit and no AI calls.

- `render_project(result, project_name, base_url) -> dict[str, str]` (tests carry `module` from validation)
  (a mapping from path to content)
- `build_zip(files, root_dir) -> bytes`

Zip layout:

```
<project-slug>-playwright/
├── package.json            # devDependencies pinned: @playwright/test, typescript, @types/node;
│                           # scripts test, test:ui, report, typecheck (tsc --noEmit); no lockfile
├── playwright.config.ts    # loads .env via process.loadEnvFile (Node >= 20.12) when present;
│                           # baseURL: process.env.BASE_URL ?? '<base_url>'; trace on-first-retry
├── tsconfig.json
├── .env.example            # BASE_URL plus every ${ENV:NAME} used
├── .gitignore              # node_modules, test-results, playwright-report, .env
├── README.md               # npm install, npx playwright install, npm test; list of TODOs
├── pages/<PageName>.ts
└── tests/<module-slug>.spec.ts   # tests grouped by the source TestCase.module
```

Page object: one `readonly` `Locator` field per locator, assigned in the
constructor. `readonly path`. `async goto()` navigates to `this.path`.

Action to Playwright mapping:

| action | output |
|---|---|
| `goto` | `await <pageVar>.goto();` |
| `click` | `await <pageVar>.<key>.click();` |
| `fill` | `await <pageVar>.<key>.fill(<value>);` |
| `select` | `await <pageVar>.<key>.selectOption(<value>);` |
| `check` / `uncheck` | `await <pageVar>.<key>.check();` / `.uncheck();` |
| `press` | `await <pageVar>.<key>.press(<value>);` |
| `expect_visible` / `expect_hidden` | `await expect(<pageVar>.<key>).toBeVisible();` / `.toBeHidden();` |
| `expect_text` | `await expect(<pageVar>.<key>).toContainText(<value>);` |
| `expect_value` | `await expect(<pageVar>.<key>).toHaveValue(<value>);` |
| `expect_url` | `await expect(page).toHaveURL(new RegExp(<escaped value>));` |
| `todo` | `// TODO: <source>`; the whole test becomes `test.fixme(...)` |

Locator strategies map to `getByRole(role, { name })`, `getByLabel`,
`getByPlaceholder`, `getByText`, `getByTestId` and `locator(css)`.

Rendering rules:

- Every string that goes into TypeScript is emitted as a JSON-escaped string
  literal (`json.dumps`, `ensure_ascii=False`). Quotes, backticks, `${`,
  newlines and `*/` cannot break out.
- `source` comments are reduced to one line and have `*/` removed. The line
  comments use `//`.
- File and class names come from sanitized identifiers or slugs
  (`[a-z0-9-]`). Zip entries never contain `..` or absolute paths.
- The output is deterministic: sorted pages, tests kept in input order, a fixed zip
  timestamp. The same input always gives the same bytes.
- Each test gets a page-object variable for every page it uses, named
  camelCase from the class name (`loginPage`).

## AI call

- `AIClient.generate_automation(system_prompt, test_cases, pages) -> dict`
  returns `{"automation": AutomationResult dict, "usage": {...}}`, the same
  as the other methods.
- A new prompt, `prompts/automation_system_prompt.md`, is combined with the
  project config by `build_system_prompt`. It covers: prefer role/label/test
  id over css; set `confident: true` only when the locator is found in the
  supplied HTML/ARIA; one `AutomatedTest` per selected test case with the
  same `test_id`; use `todo` instead of inventing behaviour; `${ENV:NAME}`
  for secrets; ask in `open_questions` rather than guess.
- In the user content, each test case goes inside `<test_case>` tags. Each
  page's snapshot goes inside `<page name="…" path="…">` tags, with the
  instruction that the content is data and not instructions. A closing
  `</page` or `</test_case` inside pasted content is neutralised
  (`<\/page`) so it cannot end its tag early.
- The call goes through the existing `_call_ai` unchanged (`max_tokens=16000`).
  On `stop_reason == "max_tokens"` the page adds a hint to select fewer test
  cases.

## UI (`pages/3_Automation.py`)

1. Sidebar: the shared API key block (same as the other pages).
2. Source radio: "Test cases in this session" (from `last_result`; if it is
   empty, an info message links to the Generator) or "Upload .xlsx/.csv"
   (the existing mapping flow; required fields are `test_id`, `title`, `steps`,
   `expected_result`).
3. Project config selectbox (`configs/*.yaml`).
4. A test case table with a selection checkbox. Only `Web`/`All` cases are
   shown, and the rest are counted in a caption. Rows from an upload without a
   platform column count as web.
5. Base URL text input, then a number-of-pages input (0–10) with name, path
   and snapshot fields per page (blank pages are ignored; a 50k-character
   snapshot does not fit a table cell).
   A caption explains how to get an ARIA snapshot and warns that
   pasted HTML is sent to Anthropic, so tokens and personal data should be removed first.
6. The Generate button is disabled, with the reason shown, when: nothing is
   selected; more than 10 selected; the Base URL is not `http(s)://`; there
   are more than 10 pages; a page name or path is empty or duplicated; a
   snapshot is over 50,000 characters.
7. Results: metrics (tests, `fixme` tests, locators to verify, token
   cost), warnings from validation, open questions, a file picker with
   `st.code(..., language="typescript")` preview, and a zip download named
   `<project-slug>-playwright-<yyyymmdd>.zip`.
8. The result is stored in `st.session_state["automation_result"]` and
   cleared when the source, the uploaded file or the selection changes.
   If no test could be generated, or every test is `fixme`, the zip is still
   offered, with a prominent warning.

## Error handling

- AI errors (rate limits, schema errors, max_tokens) use the existing retry
  and `ValueError` path, shown through `st.status`/`st.error`.
- Bad references in valid AI output are handled by validation (downgrade and
  warn), never by an exception.
- The UI validates the input before any AI call (see UI step 6).

## Testing

- `tests/test_automation_validate.py`: covers each validation rule above.
- `tests/test_playwright_renderer.py`:
  - every action and every locator strategy;
  - escaping of `'`, `"`, `` ` ``, `${`, `*/` and newlines;
  - `${ENV:NAME}` handling and `.env.example`;
  - `todo` producing `test.fixme`;
  - grouping by module;
  - deterministic zip bytes and no path traversal;
  - a golden snapshot of a small fixture project under `tests/fixtures/`.
- `tests/test_ai_client.py`, `tests/test_ai_client_schemas.py`:
  `generate_automation` passes `AutomationResult`, wraps test cases and
  snapshots in their tags (neutralising closing tags), and reports usage.
- `tests/test_automation_page.py`: `AppTest` covers both sources, the
  platform filter, the disabled-button reasons, and state reset.
- CI: a new job, `automation-smoke` (Node 20). It renders the fixture
  project with Python, then runs `npm install` and `npm run typecheck` on it to
  show that the generated TypeScript compiles. It does not start a browser.

## Documentation

README: add the Automation page to the feature list and the directory tree,
and split the Phase 4 roadmap into step 1 (done) and step 2 (self-healing).
Add a CHANGELOG entry.
