"""
Heal Locators — repair the locators of a failing Playwright page object from
the error output and the page's current HTML, without touching anything else.
"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.automation_inputs import signature
from core.locator_healing import (
    HealingInputError,
    apply_fixes,
    healing_problems,
    parse_locators,
    read_page_object,
    unified_diff,
    validate_fixes,
)
from core.prompt_builder import (
    LOCATOR_HEALING_PROMPT_PATH,
    ProjectConfigError,
    build_system_prompt,
    list_available_configs,
    load_project_config,
)

load_dotenv()

CONFIGS_DIR = Path("configs")
VERDICT_WARNINGS = {
    "element_missing": (
        "The AI thinks the element is no longer on the page. This may be a real bug or an "
        "intended change in the app; check before updating the test."
    ),
    "behaviour_changed": (
        "The AI thinks the app's behaviour changed, not just its markup. This may be a real bug; "
        "check before updating the test."
    ),
    "not_a_locator_problem": "The AI thinks this failure is not caused by a locator. Look at the error itself.",
}

st.set_page_config(page_title="Heal Locators — AI Test Case Generator", page_icon="🩹", layout="wide")
st.title("🩹 Heal Locators")
st.caption("Repair the locators of a failing Playwright page object from the error and the page's current HTML.")

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


def _heal(project, file_name, locators, error_text, snapshot, current_signature) -> None:
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

    system_prompt = build_system_prompt(config, base_prompt_path=LOCATOR_HEALING_PROMPT_PATH)
    with st.status("Healing locators...", expanded=False) as status:
        try:
            response = client.heal_locators(system_prompt, file_name, locators, error_text, snapshot)
        except ValueError as e:
            status.update(label=f"Error: {e}", state="error")
            st.error(f"Error calling the AI: {e}")
            return
        status.update(label="Healing complete", state="complete")

    fixes, warnings = validate_fixes(response["healing"]["fixes"], locators)
    st.session_state["healing_result"] = {
        "healing": response["healing"],
        "fixes": fixes,
        "warnings": warnings,
        "usage": response["usage"],
        "signature": current_signature,
    }


def _render_result(stored: dict, source: str, file_name: str, locators: list[dict]) -> None:
    healing = stored["healing"]
    st.subheader("🩹 Healing result")
    st.markdown(f"**Verdict:** `{healing['verdict']}`")
    if healing["verdict"] in VERDICT_WARNINGS:
        st.warning(VERDICT_WARNINGS[healing["verdict"]])
    if healing["explanation"]:
        st.markdown(healing["explanation"])
    _usage_caption(stored["usage"])
    if stored["warnings"]:
        with st.expander(f"Warnings ({len(stored['warnings'])})", expanded=True):
            st.markdown("\n".join(f"- {warning}" for warning in stored["warnings"]))
    if not stored["fixes"]:
        st.info("The AI proposed no locator changes.")
        return

    current = {loc["key"]: loc["expression"] for loc in locators}
    chosen = []
    for fix in stored["fixes"]:
        # The signature in the key resets the checkboxes for every new result.
        checkbox_key = f"heal_fix_{stored['signature'][:12]}_{fix['key']}"
        if st.checkbox(f"Apply the fix to `{fix['key']}`", value=True, key=checkbox_key):
            chosen.append(fix)
        st.code(f"- {current[fix['key']]}\n+ {fix['expression']}", language="diff")
        st.caption(fix["reason"] + ("" if fix["confident"] else " · not confirmed by the snapshot"))

    if not chosen:
        st.info("No fix selected.")
        return
    patched = apply_fixes(source, locators, chosen)
    st.markdown("**Diff of the patched file:**")
    st.code(unified_diff(source, patched, file_name), language="diff")
    st.download_button(
        "⬇️ Download the patched file",
        data=patched.encode("utf-8"),
        file_name=Path(file_name).name,
        mime="text/plain",
        key="heal_download_btn",
    )


configs = list_available_configs(CONFIGS_DIR)
if not configs:
    st.error("No project configs found in configs/. Add one first (see docs/how-to-add-new-project.md).")
    st.stop()
project = st.selectbox("Project", configs, key="heal_project_select")

uploaded = st.file_uploader("Page object file (.ts)", type=["ts"], key="heal_file")
source, file_name, locators = "", "", None
if uploaded is not None:
    file_name = uploaded.name
    try:
        source = read_page_object(uploaded.getvalue())
    except HealingInputError as e:
        st.error(str(e))
    else:
        locators, skipped = parse_locators(source)
        if locators:
            st.dataframe(
                [{"locator": loc["key"], "current expression": loc["expression"]} for loc in locators],
                hide_index=True,
            )
        if skipped:
            st.caption(
                "Skipped lines (not a one-line `this.<name> = page.…;` locator, or a repeated name): "
                + ", ".join(str(index + 1) for index in skipped)
            )

error_text = st.text_area(
    "Playwright error", key="heal_error", height=160,
    help="Paste the failing test's output from `npx playwright test`.",
)
snapshot = st.text_area("Current HTML/ARIA snapshot", key="heal_snapshot", height=200)
st.caption("The error and the snapshot are sent to Anthropic: remove tokens and personal data first.")

current_signature = signature(file_name, source, error_text, snapshot, project)
stored = st.session_state.get("healing_result")
if stored and stored["signature"] != current_signature:
    del st.session_state["healing_result"]
    stored = None

problems = healing_problems(locators, error_text, snapshot)
if problems:
    st.warning("Before healing:\n" + "\n".join(f"- {problem}" for problem in problems))
if st.button("🩹 Heal locators", key="heal_btn", disabled=bool(problems)):
    _heal(project, file_name, locators, error_text, snapshot, current_signature)
    stored = st.session_state.get("healing_result")

if stored:
    _render_result(stored, source, file_name, locators)
