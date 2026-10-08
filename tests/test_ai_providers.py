"""
The providers other than Claude: the OpenAI SDK pointed at a local server that
answers in the chat-completions format, so the real request and response path
is exercised without a key or a network.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from streamlit.testing.v1 import AppTest

from core.ai_client import AIClient, GenerationResult, _extract_json
from core.ai_providers import PROVIDERS, get_provider

CASE = {
    "test_id": "TC_LOGIN_001",
    "module": "Login",
    "title": "Valid login",
    "precondition": "User exists",
    "steps": "1. Open login\n2. Submit",
    "test_data": "user@example.com",
    "expected_result": "Dashboard opens",
    "priority": "High",
    "type": "Positive",
    "platform": "Web",
}
RESULT = {"test_cases": [CASE], "summary": {"total": 1, "by_type": {"Positive": 1}, "open_questions": []}}


def _completion(content: str, finish_reason: str = "stop", usage: dict | None = None, refusal: str | None = None) -> dict:
    message = {"role": "assistant", "content": content}
    if refusal:
        message["refusal"] = refusal
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage or {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    }


class _Server:
    """Answers each request with the next queued (status, body) and records what it was sent."""

    def __init__(self, responses: list[tuple[int, dict]]):
        self.responses = list(responses)
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - the name http.server calls
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": body})
                status, payload = outer.responses.pop(0) if outer.responses else (500, {"error": {"message": "no more responses"}})
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def serve():
    servers = []

    def start(*responses):
        server = _Server(list(responses))
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.close()


def _client(server: _Server, **kwargs) -> AIClient:
    options = {"provider": "compatible", "model": "test-model", "base_url": server.base_url, "sleep_fn": lambda _s: None}
    return AIClient(**{**options, **kwargs})


def test_generates_through_a_chat_completions_server(serve):
    server = serve((200, _completion(json.dumps(RESULT), usage={
        "prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150,
        "prompt_tokens_details": {"cached_tokens": 100},
    })))

    result = _client(server, api_key="local-key").generate_test_cases("SYSTEM PROMPT", "Login requirement")

    assert result["test_cases"][0]["test_id"] == "TC_LOGIN_001"
    assert result["summary"]["total"] == 1
    # The cached part of the prompt is reported apart from the new input, as for Claude.
    assert result["usage"] == {
        "provider": "compatible", "model": "test-model",
        "input_tokens": 20, "output_tokens": 30,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 100,
        "total_input_tokens": 120, "estimated_cost_usd": None,
    }

    request = server.requests[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["authorization"] == "Bearer local-key"
    body = request["body"]
    assert body["model"] == "test-model"
    system, user = body["messages"]
    assert system["role"] == "system" and system["content"].startswith("SYSTEM PROMPT\n\n")
    # The schema is in the prompt, for servers that do not enforce a response format.
    assert '"test_cases"' in system["content"] and "JSON Schema" in system["content"]
    assert user == {"role": "user", "content": "Requirement/User Story to write test cases for:\n\nLogin requirement"}
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "GenerationResult"
    assert body["response_format"]["json_schema"]["schema"] == GenerationResult.model_json_schema()


def test_a_local_server_needs_no_key(serve):
    server = serve((200, _completion(json.dumps(RESULT))))
    _client(server).generate_test_cases("S", "R")
    # The SDK cannot be built without a key, so a stand-in is sent.
    assert server.requests[0]["authorization"] == "Bearer not-needed"


def test_falls_back_to_json_mode_when_the_schema_format_is_refused(serve):
    server = serve(
        (400, {"error": {"message": "response_format json_schema is not supported", "type": "invalid_request_error"}}),
        (200, _completion(f"```json\n{json.dumps(RESULT)}\n```")),
    )

    result = _client(server).generate_test_cases("S", "R")

    assert result["summary"]["total"] == 1
    assert [request["body"]["response_format"]["type"] for request in server.requests] == ["json_schema", "json_object"]


def test_another_bad_request_is_reported_and_not_retried(serve):
    server = serve((400, {"error": {"message": "model `nope` does not exist", "type": "invalid_request_error"}}))
    with pytest.raises(ValueError, match=r"returned an error \(400\).*nope"):
        _client(server).generate_test_cases("S", "R")
    assert len(server.requests) == 1


def test_a_reply_that_does_not_match_the_schema_names_the_field(serve):
    broken = json.loads(json.dumps(RESULT))
    broken["test_cases"][0]["priority"] = "Urgent"
    server = serve((200, _completion(json.dumps(broken))))
    with pytest.raises(ValueError, match=r"expected schema \(test_cases\.0\.priority"):
        _client(server).generate_test_cases("S", "R")


def test_a_reply_that_is_not_json_is_a_schema_error(serve):
    server = serve((200, _completion("Sure! Here are your test cases.")))
    with pytest.raises(ValueError, match="did not return a result matching the expected schema"):
        _client(server).generate_test_cases("S", "R")


def test_a_cut_off_reply_and_a_refusal_have_their_own_messages(serve):
    cut = serve((200, _completion('{"test_cases": [', finish_reason="length")))
    with pytest.raises(ValueError, match="cut off"):
        _client(cut).generate_test_cases("S", "R")

    refused = serve((200, _completion("", refusal="I can't help with that.")))
    with pytest.raises(ValueError, match="declined to answer: I can't help with that"):
        _client(refused).generate_test_cases("S", "R")


def test_a_wrong_key_names_the_variable_of_the_provider(serve):
    server = serve((401, {"error": {"message": "bad key", "type": "invalid_api_key"}}))
    with pytest.raises(ValueError, match="Invalid API key. Please check your AI_API_KEY"):
        _client(server, api_key="wrong").generate_test_cases("S", "R")


def test_rate_limits_and_server_errors_are_retried_with_backoff(serve):
    waits = []
    server = serve(
        (429, {"error": {"message": "slow down"}}),
        (503, {"error": {"message": "busy"}}),
        (200, _completion(json.dumps(RESULT))),
    )
    result = _client(server, sleep_fn=waits.append, retry_backoff_seconds=0.5).generate_test_cases("S", "R")
    assert result["summary"]["total"] == 1
    assert waits == [0.5, 1.0]

    always_limited = serve(*[(429, {"error": {"message": "slow down"}})] * 3)
    with pytest.raises(ValueError, match="rate limit exceeded"):
        _client(always_limited, max_retries=2).generate_test_cases("S", "R")
    assert len(always_limited.requests) == 3


def test_an_unreachable_server_says_where_it_looked():
    client = AIClient(
        provider="compatible", model="m", base_url="http://127.0.0.1:9/v1", max_retries=1, sleep_fn=lambda _s: None,
    )
    with pytest.raises(ValueError, match=r"Could not connect to .* at http://127\.0\.0\.1:9/v1"):
        client.generate_test_cases("S", "R")


def test_every_other_result_type_goes_through_the_same_path(serve):
    review = {"coverage_score": 70, "missing_test_types": ["Security"], "gaps": [], "duplicates": [], "summary_note": "ok"}
    server = serve((200, _completion(json.dumps(review))), (200, _completion(json.dumps({"mapping": {"ID": "test_id"}}))))
    client = _client(server)
    assert client.review_test_cases("S", "R", [CASE])["review"]["coverage_score"] == 70
    assert client.suggest_column_mapping("S", ["ID"], [{"ID": "1"}]) == {"mapping": {"ID": "test_id"}}
    assert server.requests[0]["body"]["response_format"]["json_schema"]["name"] == "ReviewResult"


def test_what_each_provider_needs_before_it_can_be_used(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "GEMINI_API_KEY", "GEMINI_MODEL", "AI_API_KEY", "AI_MODEL", "AI_BASE_URL", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY is missing"):
        AIClient(provider="openai", model="some-model")
    with pytest.raises(ValueError, match="No model was given for OpenAI.*OPENAI_MODEL"):
        AIClient(provider="openai", api_key="k")
    with pytest.raises(ValueError, match="No server address was given.*AI_BASE_URL"):
        AIClient(provider="compatible", model="m")
    with pytest.raises(ValueError, match="Unknown AI provider 'cohere'"):
        AIClient(provider="cohere")

    # Environment variables stand in for what the sidebar leaves empty.
    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    gemini = AIClient(provider="gemini")
    assert (gemini.api_key, gemini.model) == ("g-key", "gemini-test")
    assert str(gemini.client.base_url) == "https://generativelanguage.googleapis.com/v1beta/openai/"
    # The SDK's own retries stay off: this class counts the attempts.
    assert gemini.client.max_retries == 0

    monkeypatch.setenv("AI_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("AI_MODEL", "llama-test")
    local = AIClient(provider="compatible")
    assert (local.model, local.base_url) == ("llama-test", "http://localhost:11434/v1")

    # Claude stays the default, with its own default model and key variable.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a-key")
    claude = AIClient()
    assert (claude.provider.id, claude.model) == ("anthropic", "claude-sonnet-5")
    assert get_provider(None) is PROVIDERS["anthropic"]


def test_a_claude_price_is_never_applied_to_another_provider(serve):
    server = serve((200, _completion(json.dumps(RESULT))))
    # Same name as the priced Claude model, on a different provider.
    result = _client(server, model="claude-sonnet-5").generate_test_cases("S", "R")
    assert result["usage"]["estimated_cost_usd"] is None


def test_extract_json_takes_the_object_out_of_a_fence_or_a_sentence():
    assert _extract_json('{"a": 1}') == '{"a": 1}'
    assert _extract_json('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _extract_json('```\n{"a": 1}\n```\n') == '{"a": 1}'
    assert _extract_json('Here you go: {"a": {"b": 2}} Hope it helps.') == '{"a": {"b": 2}}'
    assert _extract_json("no json here") == "no json here"


def _sidebar_app():
    import streamlit as st

    from core.ai_sidebar import ai_client_options, render_ai_settings

    with st.sidebar:
        render_ai_settings()
    st.json(ai_client_options())


def test_the_sidebar_keeps_a_key_and_a_model_per_provider(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    at = AppTest.from_function(_sidebar_app).run(timeout=30)

    assert at.sidebar.selectbox[0].value == "anthropic"
    assert [field.label for field in at.sidebar.text_input] == ["Anthropic API Key", "Model"]
    at.sidebar.text_input[0].set_value("sk-claude").run(timeout=30)
    assert at.session_state["api_key"] == "sk-claude"
    assert json.loads(at.json[0].value) == {"provider": "anthropic", "api_key": "sk-claude", "model": None, "base_url": None}

    at.sidebar.selectbox[0].set_value("compatible").run(timeout=30)
    assert [field.label for field in at.sidebar.text_input] == ["API Key (if the server needs one)", "Model", "Server address"]
    # The key typed for Claude is not offered to, or sent to, the other provider.
    assert at.sidebar.text_input[0].value == ""
    at.sidebar.text_input[1].set_value(" llama3.1 ").run(timeout=30)
    at.sidebar.text_input[2].set_value("http://localhost:11434/v1").run(timeout=30)
    assert json.loads(at.json[0].value) == {
        "provider": "compatible", "api_key": None, "model": "llama3.1", "base_url": "http://localhost:11434/v1",
    }

    # Going back finds the Claude key where it was left.
    at.sidebar.selectbox[0].set_value("anthropic").run(timeout=30)
    assert at.sidebar.text_input[0].value == "sk-claude"
    assert json.loads(at.json[0].value)["api_key"] == "sk-claude"


def test_the_sidebar_starts_on_the_provider_named_in_the_environment(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    at = AppTest.from_function(_sidebar_app).run(timeout=30)
    assert at.sidebar.selectbox[0].value == "gemini"
    assert at.sidebar.text_input[0].label == "Gemini API Key"

    monkeypatch.setenv("AI_PROVIDER", "nonsense")
    at = AppTest.from_function(_sidebar_app).run(timeout=30)
    assert at.sidebar.selectbox[0].value == "anthropic"
