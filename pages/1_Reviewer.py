"""
Test Case Reviewer — checks an existing test case set's coverage
against a requirement and project config, using the shared AIClient.
"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

import pandas as pd

from core.ai_client import AIClient
from core.excel_exporter import export_to_excel
from core.file_import import FileImportError, parse_uploaded_file
from core.prompt_builder import (
    BASE_PROMPT_PATH,
    REVIEWER_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_column_mapping_prompt,
    load_project_config,
)
from core.result_utils import (
    TEST_CASE_FIELDS,
    build_edited_result,
    find_incomplete_rows,
    normalize_edited_records,
)
from core.review_utils import apply_column_mapping, merge_test_cases

load_dotenv()

CONFIGS_DIR = Path("configs")

st.set_page_config(page_title="Reviewer — AI Test Case Generator", page_icon="🔍", layout="wide")
st.title("🔍 Test Case Reviewer")
st.caption("Check test case coverage against a requirement and get gap-filling suggestions.")

# The API key lives in st.session_state and is shared with the Generator
# page, but Streamlit renders each page's sidebar independently — without
# this block the page is a dead end when opened first with no
# ANTHROPIC_API_KEY environment variable set.
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
    if api_key:
        st.caption(
            "⚠️ The API key entered here is only kept in this browser session's "
            "memory (never written to disk). If this app is deployed publicly, "
            "set the `ANTHROPIC_API_KEY` environment variable on the server "
            "instead of typing it in here."
        )


def _run_review(requirement_text: str, config: dict, test_cases: list[dict]) -> None:
    try:
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except ValueError as e:
        st.error(str(e))
        return

    system_prompt = build_system_prompt(config, base_prompt_path=REVIEWER_PROMPT_PATH)
    with st.status("Reviewing test case coverage...", expanded=False) as status:
        try:
            result = client.review_test_cases(system_prompt, requirement_text, test_cases)
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Error calling the AI: {e}")
            return
        status.update(label="Review complete", state="complete")

    # Drop any gap-fill/merge state from a previous review, otherwise the
    # previously generated cases stay in the editor and can be merged into
    # this (different) test case set.
    st.session_state.pop("generated_missing_cases", None)
    st.session_state.pop("merged_result", None)
    st.session_state.pop("missing_cases_editor", None)

    st.session_state["review_result"] = result["review"]
    st.session_state["review_test_cases"] = test_cases
    st.session_state["review_requirement_text"] = requirement_text
    st.session_state["review_config"] = config


def _render_review_result(review: dict) -> None:
    st.subheader("📊 Coverage Report")
    st.metric("Coverage score", f"{review['coverage_score']}/100")

    if review["missing_test_types"]:
        st.markdown("**Missing test types:** " + ", ".join(review["missing_test_types"]))

    if review["gaps"]:
        st.markdown("**Gaps found:**")
        severity_order = {"High": 0, "Medium": 1, "Low": 2}
        for gap in sorted(review["gaps"], key=lambda g: severity_order.get(g["severity"], 3)):
            st.markdown(f"- **[{gap['severity']}]** ({gap['suggested_type']}) {gap['description']}")
    else:
        st.success("No coverage gaps found.")

    if review["duplicates"]:
        st.markdown("**Possible duplicates:**")
        for group in review["duplicates"]:
            st.markdown(f"- {', '.join(group['test_ids'])} — {group['reason']}")

    if review.get("summary_note"):
        st.caption(review["summary_note"])


session_tab, upload_tab = st.tabs(["From current session", "Upload external file"])

with session_tab:
    if "last_result" not in st.session_state or not st.session_state["last_result"].get("test_cases"):
        st.info("No test cases generated yet this session. Go to the Generator page first, or use the Upload tab.")
    else:
        st.markdown(f"**Project:** {st.session_state.get('last_project_name', 'N/A')}")
        st.markdown(f"**Test cases in session:** {len(st.session_state['last_result']['test_cases'])}")
        if st.button("🔍 Review Coverage", key="review_session_btn"):
            _run_review(
                st.session_state.get("last_requirement_text", ""),
                st.session_state["last_config"],
                st.session_state["last_result"]["test_cases"],
            )

with upload_tab:
    uploaded_file = st.file_uploader("Upload test cases", type=["xlsx", "csv"], key="upload_file")
    available_configs = list_available_configs(CONFIGS_DIR)
    upload_project = st.selectbox("Project", available_configs, key="upload_project_select")
    upload_requirement = st.text_area(
        "Requirement this test set should cover",
        height=150,
        key="upload_requirement_text",
    )

    if uploaded_file is not None:
        try:
            raw_rows = parse_uploaded_file(uploaded_file)
        except FileImportError as e:
            st.error(str(e))
            raw_rows = None

        if raw_rows:
            if st.session_state.get("mapped_file_name") != uploaded_file.name:
                try:
                    client = AIClient(api_key=st.session_state.get("api_key") or None)
                    headers = list(raw_rows[0].keys())
                    suggestion = client.suggest_column_mapping(
                        load_column_mapping_prompt(), headers, raw_rows[:5]
                    )
                    st.session_state["column_mapping_suggestion"] = suggestion["mapping"]
                except ValueError as e:
                    st.error(f"Could not get a column mapping suggestion: {e}")
                    st.session_state["column_mapping_suggestion"] = {}
                st.session_state["mapped_file_name"] = uploaded_file.name

            st.markdown("**Confirm column mapping:**")
            headers = list(raw_rows[0].keys())
            # Skip blank/whitespace-only header names: they would render as a
            # second empty entry indistinguishable from "unmapped", and an
            # unmapped field could then silently read that column's data.
            header_options = [""] + [h for h in headers if h.strip()]
            suggestion = st.session_state.get("column_mapping_suggestion", {})
            confirmed_mapping = {}
            for field in TEST_CASE_FIELDS:
                suggested = suggestion.get(field, "")
                default_index = header_options.index(suggested) if suggested in header_options else 0
                confirmed_mapping[field] = st.selectbox(
                    field, header_options, index=default_index, key=f"mapping_{field}"
                )

            mapping_complete = all(confirmed_mapping.values())
            if not mapping_complete:
                st.warning("Map every field above before reviewing.")

            if not upload_requirement.strip():
                st.warning("Enter the requirement text above before reviewing.")

            review_upload_ready = mapping_complete and bool(upload_requirement.strip())
            if st.button(
                "🔍 Review Coverage", key="review_upload_btn", disabled=not review_upload_ready
            ):
                normalized = apply_column_mapping(raw_rows, confirmed_mapping)
                try:
                    project_config = load_project_config(CONFIGS_DIR / f"{upload_project}.yaml")
                except ProjectConfigError as e:
                    st.error(str(e))
                else:
                    _run_review(upload_requirement, project_config, normalized)

if "review_result" in st.session_state:
    review = st.session_state["review_result"]
    _render_review_result(review)

    if review["gaps"]:
        if st.button("✨ Generate missing cases", key="generate_missing_btn"):
            try:
                client = AIClient(api_key=st.session_state.get("api_key") or None)
            except ValueError as e:
                st.error(str(e))
                st.stop()

            system_prompt = build_system_prompt(st.session_state["review_config"], base_prompt_path=BASE_PROMPT_PATH)
            with st.status("Generating missing test cases...", expanded=False) as status:
                try:
                    generated = client.generate_missing_cases(
                        system_prompt,
                        st.session_state["review_requirement_text"],
                        review["gaps"],
                    )
                except ValueError as e:
                    status.update(label=f"Error: {e}", state="error")
                    st.error(f"Error calling the AI: {e}")
                    st.stop()
                status.update(label="Done", state="complete")
            st.session_state["generated_missing_cases"] = generated["test_cases"]

    if st.session_state.get("generated_missing_cases"):
        st.subheader("✏️ Suggested new test cases")
        df = pd.DataFrame(st.session_state["generated_missing_cases"])
        edited_df = st.data_editor(
            df,
            key="missing_cases_editor",
            use_container_width=True,
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
                    "Platform", options=["Web", "iOS", "Android", "All"], required=True
                ),
            },
        )

        if st.button("➕ Merge into main set", key="merge_btn"):
            # normalize_edited_records drops blank rows the dynamic editor
            # allows; build_edited_result recomputes total/by_type so the
            # exported Summary sheet matches the Generator's.
            edited_generated = normalize_edited_records(edited_df.to_dict("records"))
            merged = merge_test_cases(st.session_state["review_test_cases"], edited_generated)
            st.session_state["review_test_cases"] = merged
            st.session_state["merged_result"] = build_edited_result({}, merged)
            st.session_state.pop("generated_missing_cases", None)
            st.success(f"Merged. The set now has {len(merged)} test cases.")

    if st.session_state.get("merged_result"):
        merged_test_cases = st.session_state["merged_result"]["test_cases"]
        incomplete_rows = find_incomplete_rows(merged_test_cases)
        if incomplete_rows:
            st.error(
                "Cannot export yet: the following rows are missing required data: "
                + ", ".join(map(str, incomplete_rows))
            )

        excel_bytes = export_to_excel(st.session_state["merged_result"])
        export_project_name = st.session_state.get("review_config", {}).get(
            "project_name", "project"
        )
        st.download_button(
            "⬇️ Download merged set (Excel)",
            data=excel_bytes,
            file_name=f"reviewed_testcases_{export_project_name.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_merged_btn",
            disabled=bool(incomplete_rows) or not merged_test_cases,
        )
