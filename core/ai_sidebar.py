"""
The sidebar block that chooses the AI provider, shared by every page.

Streamlit renders each page's sidebar separately, so each page calls
`render_ai_settings()` inside its own `with st.sidebar:`; the choices live in
the session state and follow the user from page to page.
"""
import os

import streamlit as st

from core.ai_providers import DEFAULT_PROVIDER, PROVIDERS

_KEY_LABELS = {
    "anthropic": "Anthropic API Key",
    "openai": "OpenAI API Key",
    "gemini": "Gemini API Key",
    "compatible": "API Key (if the server needs one)",
}


def _key_slot(provider_id: str) -> str:
    # One slot per provider: a key typed for one must never be sent to another.
    return "api_key" if provider_id == DEFAULT_PROVIDER else f"api_key_{provider_id}"


def _current_provider() -> str:
    chosen = st.session_state.get("ai_provider") or os.environ.get("AI_PROVIDER") or DEFAULT_PROVIDER
    return chosen if chosen in PROVIDERS else DEFAULT_PROVIDER


def render_ai_settings() -> None:
    """Draws the provider, key, model and server fields. Call inside `with st.sidebar:`."""
    provider_ids = list(PROVIDERS)
    provider_id = st.selectbox(
        "AI provider",
        provider_ids,
        index=provider_ids.index(_current_provider()),
        format_func=lambda item: PROVIDERS[item].label,
        help="Claude is the default and the one the prompts were written for. "
        "Results from other models can differ in quality.",
    )
    st.session_state["ai_provider"] = provider_id
    provider = PROVIDERS[provider_id]

    slot = _key_slot(provider_id)
    api_key = st.text_input(
        _KEY_LABELS[provider_id],
        type="password",
        value=st.session_state.get(slot, ""),
        help=f"Can be left blank if the {provider.key_env} environment variable is already set",
    )
    if api_key:
        st.session_state[slot] = api_key
        st.caption(
            "⚠️ The API key entered here is only kept in this browser session's "
            "memory (never written to disk). If this app is deployed publicly, "
            f"set the `{provider.key_env}` environment variable on the server "
            "instead of typing it in here."
        )

    model_slot = f"ai_model_{provider_id}"
    model = st.text_input(
        "Model",
        value=st.session_state.get(model_slot, ""),
        placeholder=provider.default_model or os.environ.get(provider.model_env, "") or "model name",
        help=(
            f"Leave blank to use {provider.default_model}."
            if provider.default_model
            else f"{provider.model_hint}. Can be left blank if the {provider.model_env} "
            "environment variable is set."
        ),
    )
    st.session_state[model_slot] = model.strip()

    if provider.base_url_required:
        url_slot = f"ai_base_url_{provider_id}"
        base_url = st.text_input(
            "Server address",
            value=st.session_state.get(url_slot, ""),
            placeholder="http://localhost:11434/v1",
            help="The server's OpenAI-compatible address, usually ending in /v1. Can be left blank "
            f"if the {provider.base_url_env} environment variable is set.",
        )
        st.session_state[url_slot] = base_url.strip()


def ai_client_options() -> dict:
    """The arguments for `AIClient(...)` that match what the sidebar holds."""
    provider_id = _current_provider()
    return {
        "provider": provider_id,
        "api_key": st.session_state.get(_key_slot(provider_id)) or None,
        "model": st.session_state.get(f"ai_model_{provider_id}") or None,
        "base_url": st.session_state.get(f"ai_base_url_{provider_id}") or None,
    }
