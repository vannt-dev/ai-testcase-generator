"""
The AI providers the app can talk to, and what each needs from the user.

Claude is the default and the provider every prompt was written and tried
against. The others go through the OpenAI chat-completions wire format, which
OpenAI itself, Google Gemini (through its OpenAI-compatible endpoint) and most
local or hosted model servers (Ollama, LM Studio, OpenRouter, ...) all speak.
"""
from dataclasses import dataclass

DEFAULT_PROVIDER = "anthropic"


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    # Environment variables read when the sidebar field is left empty.
    key_env: str
    model_env: str
    base_url_env: str = ""
    # The model used when none is given. Only Claude has one: for the others
    # the app would have to guess a name that goes out of date.
    default_model: str = ""
    # A fixed endpoint, or empty when the SDK's own default or the user's applies.
    base_url: str = ""
    # A local server has no key to give.
    key_required: bool = True
    base_url_required: bool = False
    model_hint: str = ""


PROVIDERS: dict[str, Provider] = {
    "anthropic": Provider(
        id="anthropic",
        label="Claude (Anthropic)",
        key_env="ANTHROPIC_API_KEY",
        model_env="ANTHROPIC_MODEL",
        default_model="claude-sonnet-5",
    ),
    "openai": Provider(
        id="openai",
        label="OpenAI",
        key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        model_hint="The model name from your OpenAI account, for example a GPT model",
    ),
    "gemini": Provider(
        id="gemini",
        label="Google Gemini",
        key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        model_hint="The model name from Google AI Studio, for example a Gemini Flash or Pro model",
    ),
    "compatible": Provider(
        id="compatible",
        label="OpenAI-compatible server (Ollama, LM Studio, OpenRouter, ...)",
        key_env="AI_API_KEY",
        model_env="AI_MODEL",
        base_url_env="AI_BASE_URL",
        key_required=False,
        base_url_required=True,
        model_hint="The model name as the server lists it, for example llama3.1",
    ),
}


def get_provider(provider_id: str | None) -> Provider:
    try:
        return PROVIDERS[provider_id or DEFAULT_PROVIDER]
    except KeyError:
        known = ", ".join(PROVIDERS)
        raise ValueError(f"Unknown AI provider '{provider_id}'. Use one of: {known}.") from None
