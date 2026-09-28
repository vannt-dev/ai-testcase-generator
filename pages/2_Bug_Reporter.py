"""
Bug Reporter — turns a tester's rough notes about one defect, or the failed
rows of an executed test run, into structured bug reports, exported as
Markdown or Excel.
"""
import hashlib
import json
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.bug_batch import (
    MAX_BATCH_ROWS,
    REQUIRED_RUN_FIELDS,
    RUN_FIELDS,
    apply_summary_edits,
    combined_markdown,
    default_failed_values,
    distinct_values,
    failed_rows,
    write_reports,
)
from core.bug_exporters import file_stem, missing_required_fields, to_excel, to_markdown
from core.file_import import FileImportError, parse_uploaded_rows
from core.prompt_builder import (
    BUG_REPORT_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_project_config,
    load_run_column_mapping_prompt,
)
from core.result_utils import TEST_CASE_FIELDS

load_dotenv()

CONFIGS_DIR = Path("configs")
SEVERITIES = ["Critical", "Major", "Minor", "Trivial"]
PRIORITIES = ["High", "Medium", "Low"]
REPRODUCIBILITY = ["Always", "Intermittent", "Once", "Unknown"]
TEXT_FIELDS = [
    "title", "module", "build_version", "environment", "preconditions",
    "expected_result", "actual_result", "test_data", "related_test_id",
]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.set_page_config(page_title="Bug Reporter — AI Test Case Generator", page_icon="🐞", layout="wide")
st.title("🐞 Bug Reporter")
st.caption("Turn rough notes, or the failed rows of a test run, into bug reports you can paste into any tracker.")

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
    draft["reproducibility"] = report["reproducibility"]
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
    report["reproducibility"] = draft["reproducibility"]
    report["steps_to_reproduce"] = _lines(draft["steps"])
    report["open_questions"] = _lines(draft["open_questions"])
    return report


def _usage_caption(usage: dict) -> None:
    if not usage:
        return
    cost = usage.get("estimated_cost_usd")
    st.caption(
        f"Model: {usage.get('model', 'N/A')} · input {usage.get('input_tokens', 0):,} tokens"
        f" · output {usage.get('output_tokens', 0):,} tokens · estimated cost "
        + (f"${cost:.6f}" if cost is not None else "N/A")
    )


def _render_notes_tab(configs: list[str]) -> None:
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
            return

        system_prompt = build_system_prompt(config, base_prompt_path=BUG_REPORT_PROMPT_PATH)
        with st.status("Writing the bug report...", expanded=False) as status:
            try:
                result = client.write_bug_report(system_prompt, notes, _related_context(related))
            except ValueError as e:
                status.update(label=f"Error: {e}", state="error")
                st.error(f"Error calling the AI: {e}")
                return
            status.update(label="Done", state="complete")
        _load_report(result["report"])
        st.session_state["bug_usage"] = result["usage"]

    if "bug_draft" not in st.session_state:
        return

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
    col_repro, col_build = st.columns(2)
    col_repro.selectbox("Reproducibility", REPRODUCIBILITY, key="bug_reproducibility")
    col_build.text_input("Build / version", key="bug_build_version")
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

    stem = file_stem(report["title"])
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

    _usage_caption(st.session_state.get("bug_usage", {}))


def _render_batch_result() -> None:
    result = st.session_state["batch_result"]
    for error in result["errors"]:
        label = f"Row {error['row']}" + (f" ({error['test_id']})" if error["test_id"] else "")
        st.error(f"{label}: {error['error']}")
    if not result["reports"]:
        st.error("No bug reports were written. Check the errors above and try again.")
        return

    st.subheader(f"✏️ {len(result['reports'])} bug report(s)")
    summary = pd.DataFrame(
        [
            {
                "#": number,
                "related_test_id": report["related_test_id"],
                "title": report["title"],
                "severity": report["severity"],
                "priority": report["priority"],
            }
            for number, report in enumerate(result["reports"], start=1)
        ]
    )
    edited = st.data_editor(
        summary,
        key="batch_editor",
        hide_index=True,
        use_container_width=True,
        disabled=["#", "related_test_id"],
        column_config={
            "severity": st.column_config.SelectboxColumn("Severity", options=SEVERITIES, required=True),
            "priority": st.column_config.SelectboxColumn("Priority", options=PRIORITIES, required=True),
        },
    )
    reports = apply_summary_edits(result["reports"], edited.to_dict("records"))
    # Keep the edits outside the widget: its state is dropped when the user leaves the page.
    result["reports"] = reports

    stem = f"bug_reports_{st.session_state.get('batch_project', 'project')}"
    col_xlsx, col_md = st.columns(2)
    with col_xlsx:
        st.download_button(
            "⬇️ Download .xlsx", to_excel(reports), f"{stem}.xlsx", XLSX_MIME, key="download_batch_xlsx"
        )
    with col_md:
        st.download_button(
            "⬇️ Download .md", combined_markdown(reports).encode("utf-8"), f"{stem}.md", "text/markdown",
            key="download_batch_md",
        )
    _usage_caption(result["usage"])
    st.caption(f"Built from {st.session_state.get('batch_source', 'the uploaded file')}.")


def _render_run_tab(configs: list[str]) -> None:
    uploaded = st.file_uploader("Executed test run (.xlsx or .csv)", type=["xlsx", "csv"], key="run_file")
    project = st.selectbox("Project", configs, key="run_project_select")
    if uploaded is None:
        st.info("Upload a test run with a status column and an actual result column.")
        # The uploader forgets its file when the user leaves the page; the paid results must not.
        if "batch_result" in st.session_state:
            _render_batch_result()
        return
    try:
        raw_rows, row_numbers = parse_uploaded_rows(uploaded)
    except FileImportError as e:
        st.error(str(e))
        return

    headers = list(raw_rows[0].keys())
    # Name plus content: a re-exported run often keeps the same file name.
    file_id = f"{uploaded.name}:{hashlib.sha256(uploaded.getvalue()).hexdigest()}"
    if st.session_state.get("run_mapped_file_id") != file_id:
        # A new file: suggest a mapping once and drop results that belong to the old file.
        # Keyed widgets ignore new defaults once they hold state, so clear the per-file ones.
        for key in [k for k in st.session_state if k.startswith(("run_mapping_", "run_failed_values_"))]:
            del st.session_state[key]
        try:
            client = AIClient(api_key=st.session_state.get("api_key") or None)
            suggestion = client.suggest_column_mapping(
                load_run_column_mapping_prompt(), headers, raw_rows[:5]
            )["mapping"]
        except ValueError as e:
            st.warning(f"Could not get a column mapping suggestion: {e}")
            suggestion = {}
        st.session_state["run_mapping_suggestion"] = suggestion
        st.session_state["run_mapped_file_id"] = file_id
        st.session_state.pop("batch_result", None)

    st.markdown("**Confirm column mapping** — test case columns are optional context for the AI:")
    # Blank header names would look like "unmapped" and could silently feed a column's data.
    options = [""] + [h for h in headers if h.strip()]
    suggestion = st.session_state.get("run_mapping_suggestion", {})
    mapping = {}
    for field in (*RUN_FIELDS, *TEST_CASE_FIELDS):
        suggested = suggestion.get(field, "")
        index = options.index(suggested) if suggested in options else 0
        mapping[field] = st.selectbox(field, options, index=index, key=f"run_mapping_{field}")

    rows = []
    missing = [field for field in REQUIRED_RUN_FIELDS if not mapping[field]]
    if missing:
        st.warning("Map the required column(s): " + ", ".join(missing))
    else:
        values = distinct_values(raw_rows, mapping["status"])
        # Keyed by column: values chosen for one column are never offered against another.
        chosen = st.multiselect(
            "Status values that mean the test failed",
            values,
            default=default_failed_values(values),
            key=f"run_failed_values_{mapping['status']}",
        )
        rows = failed_rows(raw_rows, mapping, chosen, row_numbers=row_numbers)
        if not rows:
            st.info("No rows have the selected status values.")
        elif len(rows) > MAX_BATCH_ROWS:
            st.error(
                f"{len(rows)} failed rows found; the limit is {MAX_BATCH_ROWS} per run. "
                "Split the file and run each part."
            )
        else:
            st.markdown(f"**{len(rows)}** failed row(s) will get a bug report.")

    ready = 0 < len(rows) <= MAX_BATCH_ROWS
    if st.button(f"🐞 Write {len(rows)} bug report(s)", key="write_batch_btn", disabled=not ready):
        try:
            config = load_project_config(CONFIGS_DIR / f"{project}.yaml")
            client = AIClient(api_key=st.session_state.get("api_key") or None)
        except (ProjectConfigError, ValueError) as e:
            st.error(str(e))
            return
        system_prompt = build_system_prompt(config, base_prompt_path=BUG_REPORT_PROMPT_PATH)
        progress = st.progress(0.0, text="Writing bug reports...")
        st.session_state["batch_result"] = write_reports(
            client,
            system_prompt,
            rows,
            source_name=uploaded.name,
            on_progress=lambda done, total: progress.progress(done / total, text=f"Written {done} of {total}"),
        )
        st.session_state["batch_project"] = project
        st.session_state["batch_source"] = uploaded.name

    if "batch_result" in st.session_state:
        _render_batch_result()


configs = list_available_configs(CONFIGS_DIR)
if not configs:
    st.error("No project configs found in configs/. Add one from configs/_template.yaml.")
    st.stop()

notes_tab, run_tab = st.tabs(["From notes", "From a test run"])
with notes_tab:
    _render_notes_tab(configs)
with run_tab:
    _render_run_tab(configs)
