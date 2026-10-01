"""
Automation — turns selected web and API test cases into a Playwright +
TypeScript project (page objects, web specs, API specs) that the user
downloads as a zip.
"""
import hashlib
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.api_automation_validate import validate_api_automation
from core.api_renderer import summarize_api
from core.automation_inputs import (
    BASE_URL,
    MAX_CASES,
    MAX_DESCRIPTION_CHARS,
    MAX_PAGES,
    api_cases,
    input_problems,
    signature,
    web_cases,
)
from core.automation_validate import validate_automation
from core.file_import import FileImportError, parse_uploaded_file
from core.playwright_renderer import build_zip, project_root, render_project, summarize
from core.prompt_builder import (
    API_AUTOMATION_PROMPT_PATH,
    AUTOMATION_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_column_mapping_prompt,
    load_project_config,
)
from core.result_utils import TEST_CASE_FIELDS
from core.review_utils import apply_column_mapping

load_dotenv()

CONFIGS_DIR = Path("configs")
SESSION_SOURCE = "Test cases in this session"
UPLOAD_SOURCE = "Upload .xlsx/.csv"
REQUIRED_UPLOAD_FIELDS = ("test_id", "title", "steps", "expected_result")
PREVIEW_LANGUAGES = {".ts": "typescript", ".json": "json", ".md": "markdown"}
NO_WEB_AUTOMATION = {"pages": [], "tests": [], "open_questions": []}

st.set_page_config(page_title="Automation — AI Test Case Generator", page_icon="🤖", layout="wide")
st.title("🤖 Playwright Automation")
st.caption("Turn web and API test cases into a Playwright + TypeScript project.")

# Streamlit forgets a widget that is not drawn in a run, and the inputs of a kind (web or API) are
# hidden while no case of that kind is selected. Re-assigning a key keeps what the user typed.
for _key in list(st.session_state):
    if _key.startswith(("automation_base_url", "automation_api_", "automation_page_")):
        st.session_state[_key] = st.session_state[_key]

# Same shared API key block as the other pages; each page renders its own sidebar.
with st.sidebar:
    st.header("⚙️ Configuration")
    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.session_state.get("api_key", ""),
        help="Can be left blank if the ANTHROPIC_API_KEY environment variable is already set",
    )
    if api_key:
        st.session_state["api_key"] = api_key
        st.caption(
            "⚠️ The API key entered here is only kept in this browser session's "
            "memory (never written to disk). If this app is deployed publicly, "
            "set the `ANTHROPIC_API_KEY` environment variable on the server "
            "instead of typing it in here."
        )


def _usage_caption(usage: dict) -> None:
    if not usage:
        return
    cost = usage.get("estimated_cost_usd")
    st.caption(
        f"Model: {usage.get('model', 'N/A')} · input {usage.get('input_tokens', 0):,} tokens"
        f" · output {usage.get('output_tokens', 0):,} tokens · estimated cost "
        + (f"${cost:.6f}" if cost is not None else "N/A")
    )


def _uploaded_cases() -> tuple[list[dict], str]:
    uploaded = st.file_uploader("Upload test cases", type=["xlsx", "csv"], key="automation_file")
    if uploaded is None:
        return [], ""
    try:
        raw_rows = parse_uploaded_file(uploaded)
    except FileImportError as e:
        st.error(str(e))
        return [], ""
    if not raw_rows:
        st.warning("The file has no data rows.")
        return [], ""

    headers = list(raw_rows[0].keys())
    # Name plus content: a re-exported file often keeps the same name.
    file_id = f"{uploaded.name}:{hashlib.sha256(uploaded.getvalue()).hexdigest()}"
    if st.session_state.get("automation_mapped_file_id") != file_id:
        # Keyed widgets ignore new defaults once they hold state, so clear the per-file ones.
        for key in [k for k in st.session_state if k.startswith("automation_mapping_")]:
            del st.session_state[key]
        try:
            client = AIClient(api_key=st.session_state.get("api_key") or None)
            suggestion = client.suggest_column_mapping(load_column_mapping_prompt(), headers, raw_rows[:5])["mapping"]
        except ValueError as e:
            st.warning(f"Could not get a column mapping suggestion: {e}")
            suggestion = {}
        st.session_state["automation_column_suggestion"] = suggestion
        st.session_state["automation_mapped_file_id"] = file_id

    st.markdown("**Confirm column mapping** — test_id, title, steps and expected_result are required:")
    # Blank header names would look like "unmapped" and could silently feed a column's data.
    options = [""] + [h for h in headers if h.strip()]
    suggestion = st.session_state.get("automation_column_suggestion", {})
    mapping = {}
    for field in TEST_CASE_FIELDS:
        suggested = suggestion.get(field, "")
        index = options.index(suggested) if suggested in options else 0
        mapping[field] = st.selectbox(field, options, index=index, key=f"automation_mapping_{field}")
    missing = [field for field in REQUIRED_UPLOAD_FIELDS if not mapping[field]]
    if missing:
        st.warning("Map the required fields: " + ", ".join(missing))
        return [], file_id
    return apply_column_mapping(raw_rows, mapping), file_id


def _select_cases(cases: list[dict], editor_key: str) -> tuple[list[dict], list[dict]]:
    """The chosen web cases and the chosen API cases."""
    api_ids = {id(case) for case in api_cases(cases)}
    web_ids = {id(case) for case in web_cases(cases)}
    eligible = [case for case in cases if id(case) in api_ids or id(case) in web_ids]
    hidden = len(cases) - len(eligible)
    if hidden:
        st.caption(f"{hidden} mobile test case(s) hidden: only Web, All and API cases can be automated here.")
    if not eligible:
        st.info("None of these test cases target the web or an API.")
        return [], []
    kinds = ["API" if id(case) in api_ids else "Web" for case in eligible]
    # The first MAX_CASES of each kind start selected.
    seen = {"Web": 0, "API": 0}
    preselected = []
    for kind in kinds:
        preselected.append(seen[kind] < MAX_CASES)
        seen[kind] += 1
    table = pd.DataFrame(
        {
            "automate": preselected,
            "kind": kinds,
            "test_id": [c.get("test_id", "") for c in eligible],
            "module": [c.get("module", "") for c in eligible],
            "title": [c.get("title", "") for c in eligible],
        }
    )
    st.markdown(f"**Choose up to {MAX_CASES} web and {MAX_CASES} API test cases:**")
    edited = st.data_editor(
        table,
        key=editor_key,
        hide_index=True,
        disabled=["kind", "test_id", "module", "title"],
        column_config={"automate": st.column_config.CheckboxColumn("Automate")},
    )
    chosen = [(case, kind) for case, kind, keep in zip(eligible, kinds, edited["automate"]) if keep]
    return [case for case, kind in chosen if kind == "Web"], [case for case, kind in chosen if kind == "API"]


def _page_inputs() -> list[dict]:
    st.markdown("**Pages** — optional. Paste each page's HTML or ARIA snapshot so locators match the real app.")
    st.caption(
        "ARIA snapshot: open the page with `npx playwright open <url>` or use DevTools → "
        "Accessibility tree. Pasted content is sent to Anthropic: remove tokens and personal data first."
    )
    count = st.number_input("Number of pages", min_value=0, max_value=MAX_PAGES, value=1, key="automation_page_count")
    pages = []
    for index in range(int(count)):
        name_col, path_col = st.columns(2)
        name = name_col.text_input(f"Page {index + 1} name", key=f"automation_page_name_{index}")
        path = path_col.text_input(f"Page {index + 1} path", key=f"automation_page_path_{index}", placeholder="/login")
        snapshot = st.text_area(f"Page {index + 1} HTML/ARIA snapshot", key=f"automation_page_snapshot_{index}", height=120)
        if name.strip() or path.strip() or snapshot.strip():
            pages.append({"name": name.strip(), "path": path.strip(), "snapshot": snapshot})
    return pages


def _api_inputs() -> tuple[str, str]:
    api_base_url = st.text_input(
        "API base URL", key="automation_api_base_url", placeholder="https://api.staging.example.com",
        help="Written to tests/api/support.ts; it is not sent to the AI.",
    ).strip()
    st.markdown(
        "**API description** — optional. Paste the endpoint list or an OpenAPI excerpt "
        "so requests match the real API."
    )
    st.caption(
        f"Up to {MAX_DESCRIPTION_CHARS:,} characters. Pasted content is sent to Anthropic: "
        "remove real tokens and personal data first."
    )
    description = st.text_area("API description", key="automation_api_description", height=160)
    return api_base_url, description


def _sum_usage(usages: list[dict]) -> dict:
    if len(usages) == 1:
        return usages[0]
    costs = [usage.get("estimated_cost_usd") for usage in usages]
    return {
        "model": usages[0].get("model", "N/A"),
        "input_tokens": sum(usage.get("input_tokens", 0) for usage in usages),
        "output_tokens": sum(usage.get("output_tokens", 0) for usage in usages),
        "estimated_cost_usd": None if any(cost is None for cost in costs) else sum(costs),
    }


def _generate(
    selected: list[dict], pages: list[dict], api_selected: list[dict], api_description: str,
    project: str, current_signature: str,
) -> None:
    try:
        config = load_project_config(CONFIGS_DIR / f"{project}.yaml")
    except ProjectConfigError as e:
        st.error(str(e))
        return
    try:
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except ValueError as e:
        st.error(str(e))
        return

    automation, api_automation = NO_WEB_AUTOMATION, None
    warnings: list[str] = []
    usages: list[dict] = []
    with st.status("Generating Playwright tests...", expanded=False) as status:
        if selected:
            system_prompt = build_system_prompt(config, base_prompt_path=AUTOMATION_PROMPT_PATH)
            try:
                response = client.generate_automation(system_prompt, selected, pages)
            except ValueError as e:
                status.update(label=f"Error: {e}", state="error")
                hint = " Try again and select fewer test cases." if "max_tokens" in str(e) else ""
                st.error(f"Error calling the AI: {e}{hint}")
                return
            modules = {case.get("test_id", ""): case.get("module", "") for case in selected}
            automation, warnings = validate_automation(response["automation"], modules)
            usages.append(response["usage"])
        if api_selected:
            system_prompt = build_system_prompt(config, base_prompt_path=API_AUTOMATION_PROMPT_PATH)
            try:
                response = client.generate_api_automation(system_prompt, api_selected, api_description)
            except ValueError as e:
                hint = " Try again and select fewer API test cases." if "max_tokens" in str(e) else ""
                st.error(f"Error calling the AI for the API tests: {e}{hint}")
                if not selected:
                    status.update(label=f"Error: {e}", state="error")
                    return
                # The web call is already paid for: keep its result and say what is missing.
                warnings.append(f"API tests were not generated: {e}. Generate again to retry them.")
            else:
                modules = {case.get("test_id", ""): case.get("module", "") for case in api_selected}
                api_automation, api_warnings = validate_api_automation(response["api_automation"], modules)
                warnings += api_warnings
                usages.append(response["usage"])
        status.update(label="Generation complete", state="complete")

    st.session_state["automation_result"] = {
        "automation": automation,
        "api_automation": api_automation,
        "warnings": warnings,
        "usage": _sum_usage(usages),
        "signature": current_signature,
        "project_name": config["project_name"],
    }


def _render_result(stored: dict, base_url: str, api_base_url: str) -> None:
    automation, api_automation = stored["automation"], stored.get("api_automation")
    # Rendered on every run from the stored result, so a URL edit needs no new AI call.
    files = render_project(automation, stored["project_name"], base_url, api_automation, api_base_url)
    stats = summarize(automation)
    api_stats = summarize_api(api_automation) if api_automation else None
    tests = stats["tests"] + (api_stats["tests"] if api_stats else 0)
    fixme = stats["fixme"] + (api_stats["fixme"] if api_stats else 0)

    st.subheader("🧪 Generated project")
    columns = st.columns(4 if api_stats else 3)
    columns[0].metric("Tests", tests)
    columns[1].metric("Marked fixme", fixme)
    columns[2].metric("Locators to verify", stats["unverified_locators"])
    if api_stats:
        columns[3].metric("Requests to verify", api_stats["unverified_requests"])
    _usage_caption(stored["usage"])

    if tests == 0 or fixme == tests:
        st.warning(
            "No test could be fully automated: every test needs manual work. "
            "The project is still available below; see the TODOs in its README."
        )
    if stored["warnings"]:
        with st.expander(f"Warnings ({len(stored['warnings'])})", expanded=True):
            st.markdown("\n".join(f"- {warning}" for warning in stored["warnings"]))
    questions = automation["open_questions"] + (api_automation["open_questions"] if api_automation else [])
    if questions:
        st.markdown("**Open questions:**\n" + "\n".join(f"- {q}" for q in questions))

    preview = st.selectbox("Preview file", list(files), key="automation_preview_file")
    st.code(files[preview], language=PREVIEW_LANGUAGES.get(Path(preview).suffix, "text"))

    # The zip would bake these URLs in as fallbacks; don't hand out one that can't run.
    if automation["tests"] and not BASE_URL.match(base_url):
        st.warning("Enter a valid Base URL to download the project.")
        return
    if api_automation and not BASE_URL.match(api_base_url):
        st.warning("Enter a valid API base URL to download the project.")
        return
    root = project_root(stored["project_name"])
    st.download_button(
        "⬇️ Download project (.zip)",
        data=build_zip(files, root),
        file_name=f"{root}-{date.today():%Y%m%d}.zip",
        mime="application/zip",
        key="automation_download_btn",
    )


source = st.radio("Test cases", [SESSION_SOURCE, UPLOAD_SOURCE], key="automation_source", horizontal=True)
if source == SESSION_SOURCE:
    cases = list((st.session_state.get("last_result") or {}).get("test_cases") or [])
    file_id = ""
    if not cases:
        st.info("No test cases generated yet this session. Go to the Generator page first, or upload a file.")
else:
    cases, file_id = _uploaded_cases()

configs = list_available_configs(CONFIGS_DIR)
if not configs:
    st.error("No project configs found in configs/. Add one first (see docs/how-to-add-new-project.md).")
    st.stop()
project = st.selectbox("Project", configs, key="automation_project_select")

# Keyed on the full cases: regenerated cases often reuse the same test IDs.
editor_key = "automation_cases_" + signature(source, file_id, cases)[:12]
selected, api_selected = _select_cases(cases, editor_key) if cases else ([], [])

# Inputs follow the kinds selected; with nothing selected the web inputs stay, as before.
base_url, pages = "", []
if selected or not api_selected:
    base_url = st.text_input(
        "Base URL", key="automation_base_url", placeholder="https://staging.example.com",
        help="Written to playwright.config.ts; it is not sent to the AI.",
    ).strip()
    pages = _page_inputs()
api_base_url, api_description = _api_inputs() if api_selected else ("", "")

current_signature = signature(source, file_id, project, selected, api_selected)
stored = st.session_state.get("automation_result")
if stored and stored["signature"] != current_signature:
    del st.session_state["automation_result"]
    stored = None

problems = input_problems(selected, base_url, pages, api_selected, api_base_url, api_description)
if cases and problems:
    st.warning("Before generating:\n" + "\n".join(f"- {problem}" for problem in problems))
if st.button("🤖 Generate Playwright project", key="automation_generate_btn", disabled=bool(problems)):
    _generate(selected, pages, api_selected, api_description, project, current_signature)
    stored = st.session_state.get("automation_result")

if stored:
    _render_result(stored, base_url, api_base_url)
