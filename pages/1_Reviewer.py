"""
Test Case Reviewer — checks an existing test case set's coverage
against a requirement and project config, using the shared AIClient.
"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.prompt_builder import REVIEWER_PROMPT_PATH, build_system_prompt

load_dotenv()

CONFIGS_DIR = Path("configs")

st.set_page_config(page_title="Reviewer — AI Test Case Generator", page_icon="🔍", layout="wide")
st.title("🔍 Test Case Reviewer")
st.caption("Check test case coverage against a requirement and get gap-filling suggestions.")


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
    st.info("Upload support is added in a later task.")

if "review_result" in st.session_state:
    _render_review_result(st.session_state["review_result"])
