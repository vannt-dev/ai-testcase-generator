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
    ProjectConfigError,
    build_system_prompt,
    estimate_prompt_size_warning,
    list_available_configs,
    load_project_config,
)
from core.ai_client import AIClient
from core.excel_exporter import export_to_excel
from core.result_utils import (
    build_edited_result,
    find_incomplete_rows,
    normalize_edited_records,
)

load_dotenv()

st.set_page_config(page_title="AI Test Case Generator", page_icon="🧪", layout="wide")

CONFIGS_DIR = Path("configs")
# Cap requirement length to avoid exceeding the model's context/token limit
# with a confusing error — ~40,000 characters is roughly ~10,000 tokens.
MAX_REQUIREMENT_CHARS = 40000
MAX_HISTORY_ENTRIES = 10

st.title("🧪 AI Test Case Generator")
st.caption("Automatically generate test cases from a requirement — built for manual testers")

# ---------- Sidebar ----------
with st.sidebar:
    st.header("⚙️ Configuration")

    available_configs = list_available_configs(CONFIGS_DIR)
    if not available_configs:
        st.error("No config files found in the configs/ directory")
        st.stop()

    selected_config = st.selectbox("Select project", available_configs)

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
                    st.session_state.pop("test_case_editor", None)
                    st.session_state["last_result"] = entry["result"]
                    st.session_state["last_project_name"] = entry["project_name"]
                    st.rerun()

# ---------- Main ----------
requirement_text = st.text_area(
    "📋 Paste your Requirement / User Story / Jira ticket here",
    height=250,
    placeholder="E.g.: As a user, I want to log in with my phone number and OTP so that...",
)

generate_btn = st.button("🚀 Generate Test Cases", type="primary", use_container_width=False)

if generate_btn:
    if not requirement_text.strip():
        st.warning("Please enter a requirement first.")
        st.stop()

    if len(requirement_text) > MAX_REQUIREMENT_CHARS:
        st.error(
            f"Requirement is too long ({len(requirement_text):,} characters, limit "
            f"{MAX_REQUIREMENT_CHARS:,}). Split it into smaller parts and generate "
            "test cases for each part separately."
        )
        st.stop()

    try:
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except ValueError as e:
        st.error(str(e))
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

    st.session_state.pop("test_case_editor", None)
    st.session_state["last_result"] = result
    st.session_state["last_project_name"] = config["project_name"]
    st.session_state["last_config"] = config
    st.session_state["last_requirement_text"] = requirement_text

    history = st.session_state.setdefault("history", [])
    history.append(
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "project_name": config["project_name"],
            "requirement_excerpt": requirement_text.strip()[:200],
            "test_case_count": len(result.get("test_cases", [])),
            "result": result,
        }
    )
    del history[:-MAX_HISTORY_ENTRIES]

# ---------- Display results ----------
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    test_cases = result.get("test_cases", [])

    if not test_cases:
        st.warning("The AI did not generate any test cases — the requirement may be missing information.")
    else:
        st.subheader("✏️ Edit test cases")
        st.caption("You can edit cells directly, add or delete rows before downloading the Excel file.")

        df = pd.DataFrame(test_cases)
        edited_df = st.data_editor(
            df,
            key="test_case_editor",
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
        edited_test_cases = normalize_edited_records(edited_df.to_dict("records"))
        edited_result = build_edited_result(result, edited_test_cases)
        summary = edited_result["summary"]

        st.success(f"Current dataset has {len(edited_test_cases)} test cases.")

        with st.expander("View stats by type", expanded=True):
            st.metric("Total test cases", summary.get("total", len(test_cases)))
            for k, v in summary.get("by_type", {}).items():
                if v:
                    st.write(f"**{k}**: {v}")

        incomplete_rows = find_incomplete_rows(edited_test_cases)
        if incomplete_rows:
            st.error(
                "Cannot export yet: the following rows are missing required data: "
                + ", ".join(map(str, incomplete_rows))
            )

        excel_bytes = export_to_excel(edited_result)
        export_project_name = st.session_state.get("last_project_name", "project")
        st.download_button(
            "⬇️ Download Excel",
            data=excel_bytes,
            file_name=f"testcases_{export_project_name.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=bool(incomplete_rows) or not edited_test_cases,
        )

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
        st.caption(
            f"Model: {usage.get('model', 'N/A')}. Cost is an estimate based on "
            "Claude API pricing and may differ from your actual invoice."
        )
        if estimated_cost is None:
            st.caption(
                f"⚠️ No pricing found for model `{usage.get('model', 'N/A')}` in "
                "`MODEL_PRICING` (core/ai_client.py), so cost could not be estimated."
            )
