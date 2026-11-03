"""
History — every generation run saved on this computer: view one, download it again as
Excel or Gherkin, open it in the Generator, delete it or clear them all.
"""
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.excel_exporter import export_to_excel
from core.gherkin_exporter import export_to_gherkin
from core.history_store import (
    DEFAULT_KEEP,
    clear_entries,
    delete_entry,
    history_dir,
    load_entries,
    provider_and_model,
)
from core.result_utils import find_incomplete_rows, records_for_editor

# TESTCASE_HISTORY_DIR may be set in .env, and this page can be the first one opened.
load_dotenv()

st.set_page_config(page_title="History — AI Test Case Generator", page_icon="🕘", layout="wide")
st.title("🕘 History")

folder = history_dir()
st.caption(
    f"Each generation run is saved as a JSON file in `{folder}` on this computer; the newest "
    f"{DEFAULT_KEEP} are kept. API keys are never saved. Set `TESTCASE_HISTORY_DIR` to use "
    "another folder."
)


def _forget_in_session(entry_id: str | None) -> None:
    """Keep the Generator's sidebar list in step with the files (None: everything is gone)."""
    if entry_id is None:
        st.session_state.pop("history_file_warning", None)
    if "history" not in st.session_state:
        return
    if entry_id is None:
        st.session_state["history"] = []
        st.session_state["history_load_warnings"] = []
    else:
        st.session_state["history"] = [
            entry for entry in st.session_state["history"] if entry.get("id") != entry_id
        ]


def _open_in_generator(entry: dict) -> None:
    """Make the entry the Generator's current set, as the sidebar's Restore does."""
    for key in ("test_case_editor", "pending_revision", "revise_selection", "revise_note"):
        st.session_state.pop(key, None)
    st.session_state["last_result"] = entry["result"]
    st.session_state["last_project_name"] = entry["project_name"]
    st.session_state["last_config"] = entry["config"]
    st.session_state["last_requirement_text"] = entry["requirement_text"]


def _render_clear_all() -> None:
    """Clear all history, after a confirmation."""
    if not st.session_state.get("history_confirm_clear"):
        if st.button("🗑️ Clear all history", key="history_clear"):
            st.session_state["history_confirm_clear"] = True
            st.rerun()
    else:
        st.warning("Delete every file in the history folder? This can't be undone.")
        confirm_column, cancel_column = st.columns(2)
        if confirm_column.button("Yes, delete all", key="history_clear_confirm", type="primary"):
            st.session_state.pop("history_confirm_clear", None)
            try:
                removed = clear_entries(folder)
            except OSError as error:
                st.error(f"Couldn't delete the history files in {folder}: {error}")
            else:
                _forget_in_session(None)
                st.session_state.pop("history_selected", None)
                st.session_state["history_page_notice"] = f"Deleted {removed} saved run(s)."
                st.rerun()
        if cancel_column.button("Cancel", key="history_clear_cancel"):
            st.session_state.pop("history_confirm_clear", None)
            st.rerun()


entries, warnings = load_entries(folder, DEFAULT_KEEP)
entries.reverse()  # newest first

notice = st.session_state.pop("history_page_notice", None)
if notice:
    st.success(notice)
for warning in warnings:
    st.warning(warning)

if not entries:
    st.info("No saved runs yet. Generated test cases appear here as soon as they are made.")
    if warnings:
        # Only unreadable files are left; let them be removed from here too.
        _render_clear_all()
    st.stop()

rows = []
for entry in entries:
    provider, model = provider_and_model(entry)
    rows.append(
        {
            "Date": entry["timestamp"],
            "Source": entry["requirement_excerpt"].replace("\n", " ")[:120],
            "Project": entry["project_name"],
            "Model": f"{provider} / {model}" if model else "—",
            "Test cases": entry["test_case_count"],
        }
    )
st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

ids = [entry["id"] for entry in entries]
by_id = {entry["id"]: entry for entry in entries}
# Set after a delete. Only dropping the old choice left the browser showing the deleted run's
# label while the page below showed the next one; a value set here is sent to the browser.
next_id = st.session_state.pop("history_select_next", None)
if next_id in by_id:
    st.session_state["history_selected"] = next_id
entry_id = st.selectbox(
    "Open a run",
    ids,
    key="history_selected",
    format_func=lambda item: (
        f"{by_id[item]['timestamp']} · {by_id[item]['project_name']} · "
        f"{by_id[item]['test_case_count']} test cases"
    ),
)
entry = by_id[entry_id]
provider, model = provider_and_model(entry)
result = entry["result"]
test_cases = result.get("test_cases", [])

st.subheader(f"{entry['timestamp']} · {entry['project_name']}")
st.markdown(f"**Source:** {entry['requirement_excerpt']}")
st.markdown(f"**Model:** {f'{provider} / {model}' if model else 'not recorded'}")
if entry.get("note"):
    st.markdown(f"**Revision note:** {entry['note']}")
with st.expander("Requirement"):
    st.text(entry["requirement_text"])

if test_cases:
    st.dataframe(
        pd.DataFrame(records_for_editor(test_cases)), width="stretch", hide_index=True
    )
else:
    st.warning("This run has no test cases.")
open_questions = result.get("summary", {}).get("open_questions", [])
if open_questions:
    st.markdown("**Needs confirmation from BA/Dev**")
    for question in open_questions:
        st.markdown(f"- {question}")

export_stem = f"testcases_{entry['project_name'].replace(' ', '_')}_{entry_id[:15]}"
export_disabled = not test_cases or bool(find_incomplete_rows(test_cases))
excel_column, gherkin_column, open_column = st.columns(3)
excel_column.download_button(
    "⬇️ Download Excel",
    data=export_to_excel(result),
    file_name=f"{export_stem}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    disabled=export_disabled,
    key=f"history_excel_{entry_id}",
)
gherkin_column.download_button(
    "⬇️ Download Gherkin (.feature)",
    data=export_to_gherkin(result, feature_name=entry["project_name"]),
    file_name=f"{export_stem}.feature",
    mime="text/plain",
    disabled=export_disabled,
    key=f"history_gherkin_{entry_id}",
)
if open_column.button(
    "↩️ Open in the Generator",
    key=f"history_open_{entry_id}",
    help="Puts this run back in the Generator's table, to edit, revise or review it.",
):
    _open_in_generator(entry)
    st.switch_page("app.py")

# Delete one run, then everything; each asks first.
st.divider()
if st.session_state.get("history_confirm_delete") != entry_id:
    if st.button("🗑️ Delete this run", key=f"history_delete_{entry_id}"):
        st.session_state["history_confirm_delete"] = entry_id
        st.rerun()
else:
    st.warning(f"Delete the run from {entry['timestamp']}? This can't be undone.")
    confirm_column, cancel_column = st.columns(2)
    if confirm_column.button("Yes, delete it", key="history_delete_confirm", type="primary"):
        st.session_state.pop("history_confirm_delete", None)
        try:
            delete_entry(folder, entry_id)
        except OSError as error:
            st.error(f"Couldn't delete the history file in {folder}: {error}")
        else:
            _forget_in_session(entry_id)
            st.session_state.pop("history_selected", None)
            remaining = [item for item in ids if item != entry_id]
            if remaining:
                st.session_state["history_select_next"] = remaining[0]
            st.session_state["history_page_notice"] = f"Deleted the run from {entry['timestamp']}."
            st.rerun()
    if cancel_column.button("Cancel", key="history_delete_cancel"):
        st.session_state.pop("history_confirm_delete", None)
        st.rerun()

_render_clear_all()
