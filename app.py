"""
AI Test Case Generator — MVP UI (Streamlit)

Run: streamlit run app.py
"""
import time
from datetime import datetime

import streamlit as st
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from core.prompt_builder import (
    REVISE_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    estimate_prompt_size_warning,
    list_available_configs,
    load_project_config,
)
from core.ai_client import AIClient
from core.ai_sidebar import ai_client_options, render_ai_settings
from core.batch_generation import MAX_SECTIONS_PER_RUN, generate_section, merge_section_results
from core.excel_exporter import export_to_excel
from core.gherkin_exporter import export_to_gherkin
from core.requirement_import import (
    MAX_REQUIREMENT_CHARS,
    SUPPORTED_SUFFIXES,
    RequirementImportError,
    Section,
    read_requirement_file,
)
from core.revision import apply_revision, revisable_ids
from core.version import __version__
from core.result_utils import (
    PLATFORM_OPTIONS,
    build_edited_result,
    find_incomplete_rows,
    normalize_edited_records,
    records_for_editor,
)
from core.traceability import build_traceability

load_dotenv()

st.set_page_config(page_title="AI Test Case Generator", page_icon="🧪", layout="wide")

CONFIGS_DIR = Path("configs")
MAX_HISTORY_ENTRIES = 10
# Selected cases per revision, so the rewrite and any new cases fit in one reply.
MAX_REVISION_CASES = 20

def _clear_result_widgets() -> None:
    """Forget the table edits and any revision of the set that is about to be replaced."""
    for key in ("test_case_editor", "pending_revision", "revise_selection", "revise_note"):
        st.session_state.pop(key, None)


st.title("🧪 AI Test Case Generator")
st.caption("Automatically generate test cases from a requirement — built for manual testers")

# ---------- Sidebar ----------
with st.sidebar:
    st.caption(f"Version {__version__}")
    st.header("⚙️ Configuration")

    available_configs = list_available_configs(CONFIGS_DIR)
    if not available_configs:
        st.error("No config files found in the configs/ directory")
        st.stop()

    selected_config = st.selectbox("Select project", available_configs)

    render_ai_settings()

    st.divider()
    try:
        config = load_project_config(CONFIGS_DIR / f"{selected_config}.yaml")
    except ProjectConfigError as error:
        st.error(str(error))
        st.stop()
    st.markdown(f"**Project:** {config.get('project_name')}")
    st.markdown(f"**Platform:** {', '.join(config.get('platform', []))}")
    with st.expander("View config details"):
        st.json(config)

    history = st.session_state.setdefault("history", [])
    if history:
        st.divider()
        st.subheader("🕘 This session's history")
        for index, entry in reversed(list(enumerate(history))):
            label = (
                f"{entry['timestamp']} · {entry['project_name']} · "
                f"{entry['test_case_count']} test cases"
            )
            with st.expander(label):
                st.caption(entry["requirement_excerpt"])
                if st.button("↩️ Restore this result", key=f"restore_history_{index}"):
                    _clear_result_widgets()
                    st.session_state["last_result"] = entry["result"]
                    st.session_state["last_project_name"] = entry["project_name"]
                    # Restore the config/requirement too, so the Reviewer page
                    # reviews this entry's test cases against *its* project
                    # config and requirement, not the most recent generation's.
                    st.session_state["last_config"] = entry["config"]
                    st.session_state["last_requirement_text"] = entry["requirement_text"]
                    st.rerun()

# ---------- Main ----------
def _store_result(result: dict, config: dict, requirement_text: str, excerpt: str) -> None:
    """Make `result` the current set and add it to this session's history."""
    _clear_result_widgets()
    st.session_state["last_result"] = result
    st.session_state["last_project_name"] = config["project_name"]
    st.session_state["last_config"] = config
    st.session_state["last_requirement_text"] = requirement_text

    history = st.session_state.setdefault("history", [])
    history.append(
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "project_name": config["project_name"],
            "requirement_excerpt": excerpt,
            "test_case_count": len(result.get("test_cases", [])),
            "result": result,
            "config": config,
            "requirement_text": requirement_text,
        }
    )
    del history[:-MAX_HISTORY_ENTRIES]


def _new_client() -> AIClient | None:
    try:
        return AIClient(**ai_client_options())
    except ValueError as e:
        st.error(str(e))
        return None


def _run_sections(batch: dict, keys: list[str]) -> None:
    """
    Generate the given sections of the uploaded file one by one. Each result
    or error is kept in the batch as soon as it arrives, so a failure or an
    interrupted run never loses a finished section; the merged suite then
    becomes the current set.
    """
    client = _new_client()
    if client is None:
        return
    config = batch["config"]
    system_prompt = build_system_prompt(config)
    prompt_warning = estimate_prompt_size_warning(system_prompt)
    if prompt_warning:
        st.warning(prompt_warning)

    sections = [Section(**section) for section in batch["sections"]]
    chosen = [section for section in sections if section.key in keys]
    progress = st.progress(0.0, text="Starting...")
    start_time = time.time()
    for number, section in enumerate(chosen, start=1):
        progress.progress(
            (number - 1) / len(chosen), text=f"Section {number} of {len(chosen)}: {section.title}"
        )
        result, error = generate_section(
            client, system_prompt, section, number, len(chosen), batch["source_name"]
        )
        if error:
            batch["errors"][section.key] = error
        else:
            batch["results"][section.key] = result
            batch["errors"].pop(section.key, None)
    elapsed = time.time() - start_time
    progress.progress(1.0, text=f"Done in {elapsed:.1f}s")

    if not batch["results"]:
        st.error("No section produced test cases. See the errors below.")
        return
    merged = merge_section_results(sections, batch["results"])
    done = [section for section in sections if section.key in batch["results"]]
    requirement = "\n\n".join(f"{section.title}\n{section.text}" for section in done)
    _store_result(
        merged,
        config,
        requirement,
        f"{batch['source_name']}: {len(done)} of {len(sections)} section(s)",
    )


def _revise_selected(result: dict, test_cases: list[dict], selected_ids: list[str], note: str) -> None:
    """
    Ask the AI to rewrite the selected cases as the note says and keep the
    merged set as a proposal. Any error is shown and leaves the table as it is.
    """
    client = _new_client()
    if client is None:
        return
    selected_cases = [case for case in test_cases if case["test_id"] in selected_ids]
    system_prompt = build_system_prompt(st.session_state["last_config"], REVISE_PROMPT_PATH)
    with st.status("AI is revising the selected test cases...", expanded=False) as status:
        try:
            reply = client.revise_test_cases(
                system_prompt,
                st.session_state.get("last_requirement_text", ""),
                result.get("acceptance_criteria", []),
                selected_cases,
                note,
                [case["test_id"] for case in test_cases if case["test_id"]],
                MAX_REQUIREMENT_CHARS,
            )
            outcome = apply_revision(test_cases, selected_ids, reply)
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Could not revise the test cases: {e} The table was not changed.")
            return
        status.update(label="Revision ready: review it below", state="complete")
    st.session_state["pending_revision"] = {
        "base": test_cases,
        "before": selected_cases,
        "outcome": outcome,
        "note": note,
        "open_questions": reply.get("open_questions", []),
        "usage": reply.get("usage", {}),
    }


def _render_revision(result: dict, test_cases: list[dict]) -> None:
    """Select cases, describe the change, then accept or discard the AI's rewrite."""
    with st.expander(
        "✍️ Revise selected test cases with AI", expanded="pending_revision" in st.session_state
    ):
        st.caption(
            "Pick test cases, say what should change (for example \"add negative cases for an "
            "empty email\" or \"steps too vague, split step 3\"), and the AI rewrites only "
            "those. Their ids stay the same, new cases get new ids, and nothing changes until "
            "you accept."
        )
        options = revisable_ids(test_cases)
        if len(options) < len(test_cases):
            st.caption("Rows with an empty or repeated test id cannot be selected.")
        # A selected id that an edit removed from the table is dropped, not kept as stale state.
        kept = [test_id for test_id in st.session_state.get("revise_selection", []) if test_id in options]
        st.session_state["revise_selection"] = kept
        selected_ids = st.multiselect(
            "Test cases to revise",
            options,
            key="revise_selection",
            max_selections=MAX_REVISION_CASES,
        )
        note = st.text_area(
            "What should change?",
            key="revise_note",
            height=100,
            placeholder="E.g.: Add negative cases for an empty email. Step 3 is too vague: split it.",
        )
        if st.button(
            "✨ Revise selected",
            key="revise_btn",
            disabled=not selected_ids or not note.strip(),
        ):
            _revise_selected(result, test_cases, selected_ids, note.strip())

        pending = st.session_state.get("pending_revision")
        if not pending:
            return
        outcome = pending["outcome"]
        changes = {test_id: "Revised" for test_id in outcome["revised_ids"]}
        changes.update({test_id: "Added" for test_id in outcome["added_ids"]})
        st.markdown(
            f"**Proposed revision:** {len(outcome['revised_ids'])} revised, "
            f"{len(outcome['added_ids'])} added. Note: _{pending['note']}_"
        )
        st.caption("Before")
        st.dataframe(
            pd.DataFrame(records_for_editor(pending["before"])), width="stretch", hide_index=True
        )
        st.caption("After")
        st.dataframe(
            pd.DataFrame(
                [
                    {"change": changes[case["test_id"]], **case}
                    for case in records_for_editor(outcome["test_cases"])
                    if case["test_id"] in changes
                ]
            ),
            width="stretch",
            hide_index=True,
        )
        for question in pending["open_questions"]:
            st.markdown(f"- ❓ {question}")
        stale = pending["base"] != test_cases
        if stale:
            st.warning(
                "The table changed after this revision was made. Discard it and revise again."
            )
        accept_column, discard_column = st.columns(2)
        if accept_column.button(
            "✅ Accept revision", key="accept_revision_btn", type="primary", disabled=stale
        ):
            revised = build_edited_result(result, outcome["test_cases"])
            questions = revised["summary"]["open_questions"] + pending["open_questions"]
            revised["summary"]["open_questions"] = list(dict.fromkeys(questions))
            revised["usage"] = dict(pending["usage"])
            _store_result(
                revised,
                st.session_state["last_config"],
                st.session_state.get("last_requirement_text", ""),
                f"Revised {len(outcome['revised_ids'])} test case(s): {pending['note'][:150]}",
            )
            st.rerun()
        if discard_column.button("🗑️ Discard revision", key="discard_revision_btn"):
            st.session_state.pop("pending_revision", None)
            st.rerun()


paste_tab, upload_tab = st.tabs(["📋 Paste text", "📄 Upload a file"])

with paste_tab:
    requirement_text = st.text_area(
        "📋 Paste your Requirement / User Story / Jira ticket here",
        height=250,
        placeholder="E.g.: As a user, I want to log in with my phone number and OTP so that...",
    )

    generate_btn = st.button("🚀 Generate Test Cases", type="primary", key="generate_btn")

with upload_tab:
    uploaded = st.file_uploader(
        "Requirement document (.docx, .pdf, .md, .txt) or a backlog of user stories (.csv)",
        type=list(SUPPORTED_SUFFIXES),
        key="requirement_file",
        help="Documents are split at their headings, a CSV backlog one story per row. Each "
        "section is sent to the AI on its own and the results are merged into one set.",
    )
    sections: list[Section] = []
    if uploaded is not None:
        try:
            sections = read_requirement_file(uploaded, MAX_REQUIREMENT_CHARS)
        except RequirementImportError as e:
            st.error(str(e))

    if sections:
        st.caption(
            f"{len(sections)} section(s) found in {uploaded.name}. Untick the ones that need no "
            f"test cases (table of contents, revision history...); up to {MAX_SECTIONS_PER_RUN} "
            "per run, one AI call each."
        )
        picked = st.data_editor(
            pd.DataFrame(
                [
                    {"generate": True, "section": section.title, "characters": len(section.text)}
                    for section in sections
                ]
            ),
            key=f"section_picker_{uploaded.name}_{len(sections)}",
            width="stretch",
            hide_index=True,
            disabled=["section", "characters"],
            column_config={
                "generate": st.column_config.CheckboxColumn("Generate"),
                "section": st.column_config.TextColumn("Section"),
                "characters": st.column_config.NumberColumn("Characters"),
            },
        )
        chosen_keys = [
            section.key for section, keep in zip(sections, picked["generate"].tolist()) if keep
        ]
        too_many = len(chosen_keys) > MAX_SECTIONS_PER_RUN
        if too_many:
            st.warning(
                f"{len(chosen_keys)} sections are ticked; generate at most {MAX_SECTIONS_PER_RUN} "
                "per run."
            )
        if st.button(
            f"🚀 Generate test cases for {len(chosen_keys)} section(s)",
            type="primary",
            key="generate_sections_btn",
            disabled=not chosen_keys or too_many,
        ):
            st.session_state["section_batch"] = {
                "source_name": uploaded.name,
                "sections": [vars(section).copy() for section in sections],
                "config": config,
                "results": {},
                "errors": {},
            }
            _run_sections(st.session_state["section_batch"], chosen_keys)

    batch = st.session_state.get("section_batch")
    if batch and batch["errors"]:
        titles = {section["key"]: section["title"] for section in batch["sections"]}
        st.error(
            f"{len(batch['errors'])} section(s) of {batch['source_name']} failed; the others are "
            "kept in the result."
        )
        for key, error in batch["errors"].items():
            st.markdown(f"- **{titles.get(key, key)}**: {error}")
        if st.button("🔁 Retry failed sections", key="retry_sections_btn"):
            _run_sections(batch, list(batch["errors"]))
            st.rerun()

if generate_btn:
    if not requirement_text.strip():
        st.warning("Please enter a requirement first.")
        st.stop()

    if len(requirement_text) > MAX_REQUIREMENT_CHARS:
        st.error(
            f"Requirement is too long ({len(requirement_text):,} characters, limit "
            f"{MAX_REQUIREMENT_CHARS:,}). Split it into smaller parts, or save it as a file "
            "and use **Upload a file**, which generates each section separately."
        )
        st.stop()

    client = _new_client()
    if client is None:
        st.stop()

    system_prompt = build_system_prompt(config)
    prompt_warning = estimate_prompt_size_warning(system_prompt)
    if prompt_warning:
        st.warning(prompt_warning)

    start_time = time.time()
    with st.status("AI is analyzing the requirement and generating test cases...", expanded=False) as status:
        try:
            result = client.generate_test_cases(system_prompt, requirement_text)
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Error calling the AI: {e}")
            st.stop()
        elapsed = time.time() - start_time
        status.update(label=f"Done in {elapsed:.1f}s", state="complete")

    st.session_state.pop("section_batch", None)
    _store_result(result, config, requirement_text, requirement_text.strip()[:200])

# ---------- Display results ----------
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    test_cases = result.get("test_cases", [])

    if not test_cases:
        st.warning("The AI did not generate any test cases — the requirement may be missing information.")
    else:
        st.subheader("✏️ Edit test cases")
        st.caption("You can edit cells directly, add or delete rows before downloading the Excel file.")

        df = pd.DataFrame(records_for_editor(test_cases))
        edited_df = st.data_editor(
            df,
            key="test_case_editor",
            width="stretch",
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "priority": st.column_config.SelectboxColumn(
                    "Priority", options=["High", "Medium", "Low"], required=True
                ),
                "type": st.column_config.SelectboxColumn(
                    "Type",
                    options=[
                        "Positive", "Negative", "Edge case", "UI/UX",
                        "Compatibility", "Performance", "Security",
                    ],
                    required=True,
                ),
                "platform": st.column_config.SelectboxColumn(
                    "Platform", options=PLATFORM_OPTIONS, required=True
                ),
                "covers": st.column_config.TextColumn(
                    "Covers",
                    help="The acceptance criteria this test case verifies, separated by commas "
                    "(for example AC-1, AC-3).",
                ),
            },
        )
        edited_test_cases = normalize_edited_records(edited_df.to_dict("records"))
        edited_result = build_edited_result(result, edited_test_cases)
        summary = edited_result["summary"]

        st.success(f"Current dataset has {len(edited_test_cases)} test cases.")

        with st.expander("View stats by type", expanded=True):
            st.metric("Total test cases", summary.get("total", len(test_cases)))
            for k, v in summary.get("by_type", {}).items():
                if v:
                    st.write(f"**{k}**: {v}")

        trace = build_traceability(edited_result)
        if trace["criteria"]:
            uncovered = [row["id"] for row in trace["criteria"] if not row["test_ids"]]
            unknown = [row["id"] for row in trace["criteria"] if not row["listed"]]
            label = f"Traceability: {len(trace['criteria']) - len(uncovered)} of "                 f"{len(trace['criteria'])} acceptance criteria covered"
            with st.expander(label, expanded=bool(uncovered)):
                if uncovered:
                    st.warning("No test case covers: " + ", ".join(uncovered))
                if unknown:
                    st.caption(
                        "Cited by a test case but not in the criteria list: " + ", ".join(unknown)
                    )
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "Criterion": row["id"],
                                "Description": row["text"],
                                "Test IDs": ", ".join(row["test_ids"]),
                            }
                            for row in trace["criteria"]
                        ]
                    ),
                    width="stretch",
                    hide_index=True,
                )

        incomplete_rows = find_incomplete_rows(edited_test_cases)
        if incomplete_rows:
            st.error(
                "Cannot export yet: the following rows are missing required data: "
                + ", ".join(map(str, incomplete_rows))
            )

        excel_bytes = export_to_excel(edited_result)
        export_project_name = st.session_state.get("last_project_name", "project")
        export_disabled = bool(incomplete_rows) or not edited_test_cases
        export_file_stem = f"testcases_{export_project_name.replace(' ', '_')}"
        excel_column, gherkin_column = st.columns(2)
        excel_column.download_button(
            "⬇️ Download Excel",
            data=excel_bytes,
            file_name=f"{export_file_stem}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=export_disabled,
        )
        gherkin_column.download_button(
            "⬇️ Download Gherkin (.feature)",
            data=export_to_gherkin(edited_result, feature_name=export_project_name),
            file_name=f"{export_file_stem}.feature",
            mime="text/plain",
            disabled=export_disabled,
            help="One Scenario per test case: precondition as Given, steps as When, "
            "expected result as Then. Tagged with test id, module, priority, type, platform "
            "and the acceptance criteria it covers.",
        )

        _render_revision(result, edited_test_cases)

    summary = result.get("summary", {})
    open_questions = summary.get("open_questions", [])
    if open_questions:
        st.divider()
        st.subheader("❓ Needs confirmation from BA/Dev")
        for q in open_questions:
            st.markdown(f"- {q}")

    usage = result.get("usage", {})
    if usage:
        st.divider()
        st.subheader("📊 Token usage & estimated cost")
        usage_cols = st.columns(5)
        usage_cols[0].metric("New input", f"{usage.get('input_tokens', 0):,}")
        usage_cols[1].metric("Output", f"{usage.get('output_tokens', 0):,}")
        usage_cols[2].metric(
            "Cache write", f"{usage.get('cache_creation_input_tokens', 0):,}"
        )
        usage_cols[3].metric(
            "Cache hit", f"{usage.get('cache_read_input_tokens', 0):,}"
        )
        estimated_cost = usage.get("estimated_cost_usd")
        usage_cols[4].metric(
            "Estimated (USD)",
            f"${estimated_cost:.6f}" if estimated_cost is not None else "N/A",
        )
        if usage.get("provider", "anthropic") != "anthropic":
            # Prices are only kept for Claude; another provider's bill is its own to read.
            st.caption(
                f"Model: {usage.get('model', 'N/A')}. Cost is not estimated for this provider; "
                "see its own pricing."
            )
        else:
            st.caption(
                f"Model: {usage.get('model', 'N/A')}. Cost is an estimate based on "
                "Claude API pricing and may differ from your actual invoice."
            )
            if estimated_cost is None:
                st.caption(
                    f"⚠️ No pricing found for model `{usage.get('model', 'N/A')}` in "
                    "`MODEL_PRICING` (core/ai_client.py), so cost could not be estimated."
                )
