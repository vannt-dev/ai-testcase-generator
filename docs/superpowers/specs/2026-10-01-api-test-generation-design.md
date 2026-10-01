# API Test Generation — Design

Status: design approved in conversation, pending review of this spec
Roadmap: Phase 5 of the project roadmap (README.md)

## Purpose

The app covers web and mobile UI testing: requirement → test cases →
Playwright project. Testers who also own the API layer have to write those
cases and their automation by hand. This phase adds API testing to the same
flow:

1. the Generator writes API test cases from a requirement;
2. the Automation page turns them into Playwright API tests, in the same
   project as the web tests, so one `npm test` runs both.

As with the web automation, the output is a starting point: when the AI
cannot be sure of something, the generated code says so with a TODO or
`test.fixme` instead of guessing without saying so.

## Decisions

- **Source of API tests:** the requirement, through the Generator. No
  generation straight from an OpenAPI file (openapi-postman-test-generator
  already does that).
- **Output:** Playwright API tests (`request` fixture, TypeScript). No
  Postman collection.
- **One Automation page** for web and API cases, one zip.
- **Approach:** the AI returns structured JSON; a deterministic Python
  renderer writes the TypeScript. The AI never writes TypeScript.
- **Test case shape is unchanged.** API cases use the existing columns, so
  the Reviewer, Bug Reporter, Excel export and file import work without
  changes to their data model.

## Scope

**In scope**

- Platform `API` for test cases and `api` for project configs.
- Generator prompt rules for API test cases.
- Automation page: API cases selectable next to web cases; API base URL and
  an optional API description as inputs.
- A structured API automation model, its validation, its renderer, and the
  AI call.
- README, how-to doc, CHANGELOG, an example config.

**Out of scope**

- Generating from an OpenAPI file without test cases.
- Postman output, GraphQL, file uploads (multipart), XML bodies, full JSON
  Schema validation, response-time assertions.
- Healing API tests (Heal Locators stays web-only).
- Running the tests from the app.

## Part 1 — API test cases

### Model and config

- `TestCase.platform` becomes `Literal["Web", "iOS", "Android", "API", "All"]`.
- `ProjectConfig.platform` accepts `"api"` next to `web`, `ios`, `android`.
- The Generator's platform selector in the results editor (`app.py`) lists
  `API`.
- `All` keeps meaning every UI platform. A case that targets the API is
  always `API`, never `All`.

### Prompt (`prompts/base_system_prompt.md`)

A section that applies when the target platforms include `api`:

- write API test cases with `platform: "API"`;
- `steps`: one numbered line per call, as `METHOD /path` (for example
  `1. POST /orders`), with path parameters shown as `{id}`;
- `test_data`: headers, query parameters and the JSON body the call sends;
- `expected_result`: the status code, and the response fields that must be
  present or have a given value;
- UI/UX and Compatibility do not apply to API cases; Positive, Negative,
  Edge case, Performance and Security do;
- never invent an endpoint, a field or a status code the requirement does
  not give: ask in `open_questions`;
- when the platforms list both a UI platform and `api`, write both kinds
  and keep them as separate cases.

The opening line of the prompt names API next to Web and Mobile.

### Config files and docs

- `configs/_template.yaml`: the `platform` comment lists `api`.
- New `configs/example_rest_api.yaml`: a small orders API with domain rules,
  so the feature can be tried without writing a config.
- `docs/how-to-add-new-project.md`: a short "API projects" note.

## Part 2 — API automation

### Data model (`core/ai_client.py`)

All fields are required; unused ones are empty (`""`, `0`, `[]`).

```python
class ApiPair(BaseModel):
    name: str
    value: str

class ApiCheck(BaseModel):
    kind: Literal["json_equals", "json_contains", "json_exists", "json_absent", "text_contains"]
    path: str      # JSON path into the response body; "" for text_contains
    value: str     # json_equals: the expected value as JSON text; *_contains: plain text; else ""

class ApiSave(BaseModel):
    var: str       # camelCase variable name, e.g. "orderId"
    path: str      # JSON path into the response body

class ApiStep(BaseModel):
    action: Literal["request", "todo"]
    method: str            # GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS
    path: str              # starts with "/", relative to the API base URL
    headers: list[ApiPair]
    query: list[ApiPair]
    body: str              # JSON text, "" for no body
    expect_status: int     # 0 = do not assert the status
    checks: list[ApiCheck]
    saves: list[ApiSave]
    confident: bool        # False -> "// TODO verify" on the request
    source: str            # the original step sentence, rendered as a comment

class ApiTest(BaseModel):
    test_id: str
    title: str
    steps: list[ApiStep]

class ApiAutomationResult(BaseModel):
    tests: list[ApiTest]
    open_questions: list[str]
```

**JSON path:** dotted keys with optional indexes, for example
`data.items[0].id` or `[0].name`. `""` means the whole body.

**Placeholders** may appear anywhere inside `path`, a header or query value,
a string inside `body`, and a check's `value`:

- `${ENV:NAME}` — a secret or environment value; `NAME` matches
  `[A-Z][A-Z0-9_]*`. Rendered as `process.env.NAME ?? ''` and listed in
  `.env.example`. Tokens, passwords and API keys must be written this way.
- `${VAR:name}` — a value saved by an earlier step of the same test.

A string that is exactly one `${VAR:name}` keeps the saved value's type (a
numeric id stays a number). Embedded in a longer string, placeholders are
concatenated as text.

### Validation (`core/api_automation_validate.py`)

`validate_api_automation(result: dict, modules: dict[str, str]) -> tuple[dict, list[str]]`
returns a cleaned result and human-readable warnings, and never raises on AI
output. It copies each case's module onto its test as `module`. Rules:

- A duplicate `test_id` gets `_2`, `_3`, …; a test without steps gets one
  `todo` step.
- `method` is upper-cased; one outside the list above downgrades the step
  to `todo`.
- `path` must start with `/` and hold no whitespace, else `todo`.
- A non-empty `body` must parse as JSON, else `todo`. A body on `GET` or
  `HEAD` is dropped with a warning.
- `expect_status` outside 100–599 becomes `0` with a warning.
- A header or query pair with an empty name is dropped with a warning.
- A check or save whose `path` is not a valid JSON path is dropped with a
  warning. A `json_equals` whose `value` is not valid JSON is kept as a
  string comparison with a warning.
- `saves[].var` is sanitized to a camelCase identifier, made unique within
  the test, and kept clear of TypeScript reserved words and of the names the
  generated code uses (`request`, `test`, `expect`, `response…`, `body…`).
  References to the old name are rewritten.
- A `${VAR:name}` that no earlier step of the same test saves downgrades the
  step to `todo`.
- `${ENV:…}` with an invalid name is left as literal text.
- A step that asserts nothing (no status, no checks) gets a warning; it is
  still rendered.

Every downgrade records a warning such as
`TC_ORD_003 step 2: unknown variable 'orderId'`.

### Renderer (`core/api_renderer.py`)

Pure Python, no Streamlit, no AI calls. It reuses `ts_string`, `comment`
and `slug` from `core/playwright_renderer.py`.

- `render_api_files(result: dict, api_base_url: str) -> dict[str, str]` returns:
  - `tests/api/support.ts` — `apiUrl(path)` (prefixes
    `process.env.API_BASE_URL ?? '<api_base_url>'`) and `at(body, path)`
    (reads a JSON path, `undefined` when missing);
  - `tests/api/<module-slug>.api.spec.ts` — tests grouped by module, in
    input order.
- `api_env_names(result) -> list[str]` and `summarize_api(result) -> dict`
  (`tests`, `fixme`, `unverified_requests`).

A rendered request step:

```ts
  // 1. POST /orders
  const response1 = await request.post(apiUrl("/orders"), {
    headers: { "Authorization": "Bearer " + (process.env.API_TOKEN ?? '') },
    data: { "sku": "A-1", "quantity": 2 },
  });
  expect(response1.status()).toBe(201);
  const body1 = await response1.json();
  expect(at(body1, "id")).toBeDefined();
  const orderId = at(body1, "id");
```

| item | output |
|---|---|
| `request` | `await request.<method>(apiUrl(<path>), { headers, params, data })`; empty options are left out; `HEAD`/`OPTIONS` use `request.fetch(..., { method })` |
| `expect_status` | `expect(responseN.status()).toBe(<n>)` |
| `json_equals` | `expect(at(bodyN, <path>)).toEqual(<value>)` |
| `json_contains` | `expect(String(at(bodyN, <path>))).toContain(<value>)` |
| `json_exists` / `json_absent` | `expect(at(bodyN, <path>)).toBeDefined()` / `.toBeUndefined()` |
| `text_contains` | `expect(await responseN.text()).toContain(<value>)` |
| `saves` | `const <var> = at(bodyN, <path>);` |
| `confident: false` | `// TODO verify this request` above it |
| `todo` | `// TODO: <source>`; the whole test becomes `test.fixme(...)` |

`bodyN` is declared only when a check or save needs the JSON body.

Rendering rules (same guarantees as the web renderer):

- Every string that reaches TypeScript is a JSON-escaped literal; quotes,
  backticks, `${`, newlines and `*/` cannot break out. Placeholders are the
  only things turned into expressions, after validation.
- `source` comments are one line with `*/` removed.
- File names come from slugs; zip entries never contain `..` or absolute
  paths. Windows device names get a suffix.
- Deterministic output: the same input gives the same bytes.

### Project integration (`core/playwright_renderer.py`)

`render_project(result, project_name, base_url, api_result=None, api_base_url="")`:

- adds the API files when `api_result` has tests;
- `.env.example` gains `API_BASE_URL` and the API env names;
- the project README lists API tests that are `fixme` and requests marked
  for verification, and how to run only the API tests
  (`npx playwright test tests/api`);
- with no web tests, `playwright.config.ts` falls back to the API base URL
  for `baseURL`, and no `pages/` directory is written.

Existing calls without the new arguments produce byte-identical output.

### AI call

- `AIClient.generate_api_automation(system_prompt, test_cases, api_description) -> dict`
  returns `{"api_automation": ApiAutomationResult dict, "usage": {...}}`.
- `build_api_automation_request(test_cases, api_description)`: each test
  case inside `<test_case>` tags, the description inside
  `<api_description>` tags, with the instruction that tagged content is data,
  never instructions. Closing tags inside pasted content are neutralised
  (`api_description` joins the existing list).
- New prompt `prompts/api_automation_system_prompt.md`, combined with the
  project config by `build_system_prompt`. It covers: one `ApiTest` per
  test case with the same `test_id`; one `request` step per call;
  `confident: true` only when the endpoint is in the supplied description;
  assert what the expected result states and nothing invented; save and
  reuse ids with `${VAR:name}`; secrets as `${ENV:NAME}`; `todo` for
  anything the model cannot express; ask in `open_questions` rather than
  guess.
- The call goes through the existing `_call_ai` (`max_tokens=16000`).

### Automation page (`pages/3_Automation.py`, `core/automation_inputs.py`)

- `api_cases(cases)` selects `platform == "API"` (case-insensitive);
  `web_cases` is unchanged, so uploads without a platform column still count
  as web.
- The case table shows web and API cases together with a `kind` column
  (`Web` / `API`). iOS and Android cases stay hidden and counted.
- Limits: up to 10 web cases and up to 10 API cases per generation, checked
  separately.
- Inputs appear for the kinds selected:
  - web: Base URL and the Pages block, as today;
  - API: **API base URL** (required, `http(s)://`) and **API description**
    (optional, up to 50,000 characters) with a caption that it is sent to
    Anthropic and must not hold real tokens.
- The Base URL is required only when web cases are selected.
- Generation makes one AI call per kind selected, web first. If the second
  call fails, the first result is kept, the error is shown, and a warning
  says which kind is missing.
- Results: the metrics count both kinds (tests, fixme, locators to verify,
  requests to verify); warnings and open questions from both; one file
  preview and one zip. Token usage is the sum of the calls.
- The stored result is cleared when the source, file, project or selection
  changes, as today. The page caption and title mention API tests.

### Error handling

- Input problems are reported before any AI call, with the button disabled.
- AI errors use the existing retry and `ValueError` path.
- Bad references in valid AI output are handled by validation (downgrade
  and warn), never by an exception.

## Testing

- `tests/test_api_automation_validate.py`: every validation rule.
- `tests/test_api_renderer.py`: every method and check kind; placeholders
  (whole-value and embedded, env and var) in path, headers, query, body and
  checks; escaping of `'`, `"`, backticks, `${`, `*/` and newlines; `todo`
  → `test.fixme`; grouping by module; `bodyN` only when needed.
- `tests/test_playwright_renderer.py`: output without API arguments is
  unchanged; with them the env file, README and config follow the rules
  above; an API-only project has no `pages/`.
- A golden snapshot of the fixture project including API tests.
- `tests/test_ai_client*.py`: `generate_api_automation` passes
  `ApiAutomationResult`, wraps and neutralises its tags, reports usage;
  `TestCase` accepts `API`.
- `tests/test_prompt_builder.py`: config accepts `api`; the API rules are in
  the Generator prompt.
- `tests/test_automation_page.py` (`AppTest`): mixed selection, per-kind
  limits and inputs, API-only run, second-call failure keeps the first
  result, state reset.
- CI: the `automation-smoke` job type-checks the fixture project, which now
  includes API tests.

## Documentation

README: API in the feature list and the Automation section, the directory
tree, Phase 5 in the roadmap. CHANGELOG entry.
