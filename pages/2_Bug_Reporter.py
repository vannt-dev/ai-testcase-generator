"""
Bug Reporter — turns a tester's rough notes about one defect into a
structured bug report, editable here and exported as Markdown or Excel.
"""
import json
import re
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.bug_exporters import missing_required_fields, to_excel, to_markdown
from core.prompt_builder import (
    BUG_REPORT_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_project_config,
)

load_dotenv()

CONFIGS_DIR = Path("configs")
SEVERITIES = ["Critical", "Major", "Minor", "Trivial"]
PRIORITIES = ["High", "Medium", "Low"]
TEXT_FIELDS = [
    "title", "module", "environment", "preconditions",
    "expected_result", "actual_result", "test_data", "related_test_id",
]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.set_page_config(page_title="Bug Reporter — AI Test Case Generator", page_icon="🐞", layout="wide")
st.title("🐞 Bug Reporter")
st.caption("Turn rough notes about a defect into a complete bug report you can paste into any tracker.")

# Streamlit renders each page's sidebar separately; without this block the
# page is a dead end when opened first with no ANTHROPIC_API_KEY set.
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


def _related_context(text: str) -> dict | str | None:
    """A pasted JSON object is sent as data; anything else is sent as text."""
    text = text.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return text
    return value if isinstance(value, dict) else text


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _load_report(report: dict) -> None:
    # The draft lives outside widget keys: Streamlit deletes the state of widgets that
    # aren't rendered, so leaving this page would otherwise wipe the report and its edits.
    draft = {field: report[field] for field in TEXT_FIELDS}
    draft["severity"] = report["severity"]
    draft["priority"] = report["priority"]
    draft["steps"] = "\n".join(report["steps_to_reproduce"])
    draft["open_questions"] = "\n".join(report["open_questions"])
    st.session_state["bug_draft"] = draft
    # Overwrite every widget value so edits to a previous report never leak.
    for key, value in draft.items():
        st.session_state[f"bug_{key}"] = value


def _restore_widgets() -> None:
    for key, value in st.session_state["bug_draft"].items():
        st.session_state.setdefault(f"bug_{key}", value)


def _save_draft() -> None:
    st.session_state["bug_draft"] = {
        key: st.session_state[f"bug_{key}"] for key in st.session_state["bug_draft"]
    }


def _current_report() -> dict:
    draft = st.session_state["bug_draft"]
    report = {field: draft[field] for field in TEXT_FIELDS}
    report["severity"] = draft["severity"]
    report["priority"] = draft["priority"]
    report["steps_to_reproduce"] = _lines(draft["steps"])
    report["open_questions"] = _lines(draft["open_questions"])
    return report


def _file_stem(title: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", title).strip("_")[:50]
    return f"bug_{slug}" if slug else "bug_report"


configs = list_available_configs(CONFIGS_DIR)
if not configs:
    st.error("No project configs found in configs/. Add one from configs/_template.yaml.")
    st.stop()

project = st.selectbox("Project", configs, key="bug_project_select")
notes = st.text_area(
    "What went wrong? Rough notes are fine.",
    key="bug_notes",
    height=160,
    placeholder="Tapping Pay with an expired card freezes the app, no error shown",
)
related = st.text_area(
    "Related test case (optional)",
    key="bug_related_case",
    height=100,
    help="Paste the test case as JSON or as plain text; it is context for the AI.",
)

if not notes.strip():
    st.info("Enter your notes above to write a bug report.")

if st.button("🐞 Write bug report", key="write_bug_btn", disabled=not notes.strip()):
    try:
        config = load_project_config(CONFIGS_DIR / f"{project}.yaml")
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except (ProjectConfigError, ValueError) as e:
        st.error(str(e))
        st.stop()

    system_prompt = build_system_prompt(config, base_prompt_path=BUG_REPORT_PROMPT_PATH)
    with st.status("Writing the bug report...", expanded=False) as status:
        try:
            result = client.write_bug_report(system_prompt, notes, _related_context(related))
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Error calling the AI: {e}")
            st.stop()
        status.update(label="Done", state="complete")
    _load_report(result["report"])
    st.session_state["bug_usage"] = result["usage"]

if "bug_draft" in st.session_state:
    _restore_widgets()
    st.subheader("✏️ Bug report")
    questions = _lines(st.session_state["bug_open_questions"])
    if questions:
        st.warning(
            "The AI needs more information before this report is complete. Add the answers "
            "to the fields below, then remove the answered questions:\n\n"
            + "\n".join(f"- {q}" for q in questions)
        )

    st.text_input("Title", key="bug_title")
    col_module, col_severity, col_priority = st.columns(3)
    col_module.text_input("Module", key="bug_module")
    col_severity.selectbox("Severity", SEVERITIES, key="bug_severity")
    col_priority.selectbox("Priority", PRIORITIES, key="bug_priority")
    st.text_input("Environment", key="bug_environment")
    st.text_area("Preconditions", key="bug_preconditions")
    st.text_area("Steps to reproduce (one per line)", key="bug_steps")
    st.text_area("Expected result", key="bug_expected_result")
    st.text_area("Actual result", key="bug_actual_result")
    st.text_input("Test data", key="bug_test_data")
    st.text_input("Related test ID", key="bug_related_test_id")
    st.text_area("Open questions (one per line; remove the ones you answered)", key="bug_open_questions")

    _save_draft()
    report = _current_report()
    missing = missing_required_fields(report)
    if missing:
        st.error("Fill in the required field(s) before exporting: " + ", ".join(missing))

    markdown = to_markdown(report)
    st.markdown("**Markdown preview** — use the copy button in the corner of the block.")
    st.code(markdown, language="markdown")

    stem = _file_stem(report["title"])
    col_md, col_xlsx = st.columns(2)
    # Call st.download_button (not col.download_button) so tests can spy on it, as the Reviewer's do.
    with col_md:
        st.download_button(
            "⬇️ Download .md", markdown.encode("utf-8"), f"{stem}.md", "text/markdown",
            key="download_bug_md", disabled=bool(missing),
        )
    with col_xlsx:
        st.download_button(
            "⬇️ Download .xlsx", to_excel([report]), f"{stem}.xlsx", XLSX_MIME,
            key="download_bug_xlsx", disabled=bool(missing),
        )

    usage = st.session_state.get("bug_usage", {})
    if usage:
        cost = usage.get("estimated_cost_usd")
        st.caption(
            f"Model: {usage.get('model', 'N/A')} · input {usage.get('input_tokens', 0):,} tokens"
            f" · output {usage.get('output_tokens', 0):,} tokens · estimated cost "
            + (f"${cost:.6f}" if cost is not None else "N/A")
        )
