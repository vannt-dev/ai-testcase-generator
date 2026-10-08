"""
Heal Locators — repair the locators of a failing Playwright page object from
the error output and the page's current HTML, without touching anything else.
"""
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from core.ai_client import AIClient
from core.ai_sidebar import ai_client_options, render_ai_settings
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

# Same shared AI settings block as the other pages; each page renders its own sidebar.
with st.sidebar:
    st.header("⚙️ Configuration")
    render_ai_settings()


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
        client = AIClient(**ai_client_options())
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
    # Counts runs, so healing again with the same inputs starts from fresh checkboxes.
    st.session_state["healing_runs"] = st.session_state.get("healing_runs", 0) + 1
    st.session_state["healing_result"] = {
        "healing": response["healing"],
        "fixes": fixes,
        "warnings": warnings,
        "usage": response["usage"],
        "signature": current_signature,
        "run": st.session_state["healing_runs"],
    }


def _render_result(stored: dict, source: str, file_name: str, locators: list[dict]) -> None:
    healing = stored["healing"]
    st.subheader("🩹 Healing result")
    st.markdown(f"**Verdict:** `{healing['verdict']}`")
    if healing["verdict"] in VERDICT_WARNINGS:
        st.warning(VERDICT_WARNINGS[healing["verdict"]])
    # AI-written text is shown as plain text: a prompt-injected snapshot must not
    # be able to render links or load remote images through Markdown.
    if healing["explanation"]:
        st.text(healing["explanation"])
    _usage_caption(stored["usage"])
    if stored["warnings"]:
        with st.expander(f"Warnings ({len(stored['warnings'])})", expanded=True):
            st.text("\n".join(f"- {warning}" for warning in stored["warnings"]))
    if not stored["fixes"]:
        st.info("The AI proposed no locator changes.")
        return

    current = {loc["key"]: loc["expression"] for loc in locators}
    chosen = []
    for fix in stored["fixes"]:
        # The run number in the key resets the checkboxes for every new result.
        checkbox_key = f"heal_fix_{stored['run']}_{fix['key']}"
        # A fix that would drop a chain or options starts unticked.
        if st.checkbox(f"Apply the fix to `{fix['key']}`", value=not fix["drops_detail"], key=checkbox_key):
            chosen.append(fix)
        st.code(f"- {current[fix['key']]}\n+ {fix['expression']}", language="diff")
        st.text(fix["reason"] + ("" if fix["confident"] else " · not confirmed by the snapshot"))

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
        else:
            st.error("The file has no one-line `this.<name> = page.…;` locators. Is it a page object?")
        if skipped:
            st.caption(
                "Skipped lines (not a one-line `this.<name> = page.…;` locator, a repeated name, "
                "or a regex literal): "
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
