from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from core.ai_client import AIClient, GenerationResult, ReviewResult, ColumnMappingResult


VALID_RESULT = GenerationResult.model_validate(
    {
        "test_cases": [
            {
                "test_id": "TC_LOGIN_001",
                "module": "Login",
                "title": "Successful login",
                "precondition": "Account exists",
                "steps": "1. Log in",
                "test_data": "Valid account",
                "expected_result": "Home page opens",
                "priority": "High",
                "type": "Positive",
                "platform": "Web",
            }
        ],
        "summary": {"total": 99, "by_type": {}, "open_questions": []},
    }
)


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def make_client(response, model="claude-sonnet-5", **client_kwargs):
    messages = FakeMessages(response)
    sdk_client = SimpleNamespace(messages=messages)
    return AIClient(model=model, client=sdk_client, **client_kwargs), messages


class FlakyMessages:
    """Raises `error` on the first `fail_times` calls, then returns `response`."""

    def __init__(self, error, fail_times, response=None):
        self.error = error
        self.fail_times = fail_times
        self.response = response
        self.calls = 0

    def parse(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.error
        return self.response


def _rate_limit_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(429, request=request)
    return anthropic.RateLimitError("rate limited", response=response, body=None)


def _connection_error():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.APIConnectionError(message="conn error", request=request)


def test_generate_uses_structured_output_and_prompt_cache():
    response = SimpleNamespace(
        parsed_output=VALID_RESULT,
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_creation_input_tokens=1000,
            cache_read_input_tokens=2000,
        ),
    )
    client, messages = make_client(response)

    result = client.generate_test_cases("system prompt", "requirement")

    assert messages.kwargs["output_format"] is GenerationResult
    assert messages.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert result["summary"]["total"] == 1
    assert result["summary"]["by_type"]["positive"] == 1
    assert result["usage"]["total_input_tokens"] == 3100
    assert result["usage"]["estimated_cost_usd"] == pytest.approx(0.0036)


def test_unknown_model_returns_no_cost_estimate():
    response = SimpleNamespace(
        parsed_output=VALID_RESULT,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    client, _ = make_client(response, model="custom-model")

    result = client.generate_test_cases("system", "requirement")

    assert result["usage"]["estimated_cost_usd"] is None


def test_max_tokens_response_has_clear_error():
    response = SimpleNamespace(
        parsed_output=None,
        stop_reason="max_tokens",
        usage=SimpleNamespace(input_tokens=10, output_tokens=16000),
    )
    client, _ = make_client(response)

    with pytest.raises(ValueError, match="cut off"):
        client.generate_test_cases("system", "requirement")


def test_client_requires_api_key_without_injected_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AIClient()


def test_retries_transient_errors_then_succeeds():
    response = SimpleNamespace(
        parsed_output=VALID_RESULT,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    messages = FlakyMessages(_rate_limit_error(), fail_times=2, response=response)
    sdk_client = SimpleNamespace(messages=messages)
    sleeps = []
    client = AIClient(
        model="claude-sonnet-5",
        client=sdk_client,
        max_retries=3,
        retry_backoff_seconds=1.0,
        sleep_fn=sleeps.append,
    )

    result = client.generate_test_cases("system", "requirement")

    assert result["summary"]["total"] == 1
    assert messages.calls == 3
    assert sleeps == [1.0, 2.0]  # increasing backoff: 1s then 2s before the 3rd attempt


def test_gives_up_after_max_retries_on_rate_limit():
    messages = FlakyMessages(_rate_limit_error(), fail_times=99)
    sdk_client = SimpleNamespace(messages=messages)
    client = AIClient(
        model="claude-sonnet-5",
        client=sdk_client,
        max_retries=2,
        retry_backoff_seconds=0.0,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(ValueError, match="rate limit"):
        client.generate_test_cases("system", "requirement")

    assert messages.calls == 3  # 1 initial attempt + 2 retries


def test_gives_up_after_max_retries_on_connection_error():
    messages = FlakyMessages(_connection_error(), fail_times=99)
    sdk_client = SimpleNamespace(messages=messages)
    client = AIClient(
        model="claude-sonnet-5",
        client=sdk_client,
        max_retries=1,
        retry_backoff_seconds=0.0,
        sleep_fn=lambda _seconds: None,
    )

    with pytest.raises(ValueError, match="connect"):
        client.generate_test_cases("system", "requirement")

    assert messages.calls == 2  # 1 initial attempt + 1 retry


VALID_REVIEW = ReviewResult.model_validate(
    {
        "coverage_score": 80,
        "missing_test_types": ["security"],
        "gaps": [
            {
                "description": "No test for OTP resend after expiry",
                "suggested_type": "Negative",
                "severity": "High",
            }
        ],
        "duplicates": [],
        "summary_note": "Mostly covered; missing an OTP resend case.",
    }
)


def test_review_test_cases_returns_review_and_usage():
    response = SimpleNamespace(
        parsed_output=VALID_REVIEW,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=50, output_tokens=30),
    )
    client, messages = make_client(response)

    result = client.review_test_cases("system prompt", "requirement", [{"test_id": "TC_001"}])

    assert messages.kwargs["output_format"] is ReviewResult
    assert result["review"]["coverage_score"] == 80
    assert result["review"]["gaps"][0]["severity"] == "High"
    assert "usage" in result


def test_review_test_cases_includes_test_cases_in_user_message():
    response = SimpleNamespace(
        parsed_output=VALID_REVIEW,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=10),
    )
    client, messages = make_client(response)

    client.review_test_cases("system prompt", "req text", [{"test_id": "TC_001", "title": "X"}])

    user_content = messages.kwargs["messages"][0]["content"]
    assert "req text" in user_content
    assert "TC_001" in user_content


def test_generate_missing_cases_returns_same_shape_as_generate_test_cases():
    response = SimpleNamespace(
        parsed_output=VALID_RESULT,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=20, output_tokens=15),
    )
    client, messages = make_client(response)
    gaps = [{"description": "Missing OTP resend case", "suggested_type": "Negative", "severity": "High"}]

    result = client.generate_missing_cases("system prompt", "requirement", gaps)

    assert messages.kwargs["output_format"] is GenerationResult
    assert result["test_cases"][0]["test_id"] == "TC_LOGIN_001"
    user_content = messages.kwargs["messages"][0]["content"]
    assert "Missing OTP resend case" in user_content


def test_suggest_column_mapping_returns_mapping_dict():
    parsed = ColumnMappingResult.model_validate(
        {"mapping": {"test_id": "ID", "title": "Name", "module": "", "precondition": "",
                      "steps": "", "test_data": "", "expected_result": "", "priority": "",
                      "type": "", "platform": ""}}
    )
    response = SimpleNamespace(
        parsed_output=parsed,
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=5, output_tokens=5),
    )
    client, messages = make_client(response)

    result = client.suggest_column_mapping(
        "system prompt", ["ID", "Name"], [{"ID": "TC_001", "Name": "Login works"}]
    )

    assert messages.kwargs["output_format"] is ColumnMappingResult
    assert result["mapping"]["test_id"] == "ID"
