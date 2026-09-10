"""
Module responsible for calling the Claude API to generate test cases.
"""
import json
import os
import time
from typing import Any
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from core.result_utils import build_edited_result

DEFAULT_MODEL = "claude-sonnet-5"

# Max number of retries for transient errors (rate limit / connection loss),
# with increasing backoff: retry_backoff_seconds * 2^(attempt - 1).
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

# USD per one million tokens. Cache writes use the default 5-minute TTL.
MODEL_PRICING = {
    "claude-sonnet-5": {
        "input": 2.0,
        "cache_write": 2.5,
        "cache_read": 0.2,
        "output": 10.0,
    }
}


class TestCase(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    test_id: str = Field(min_length=1)
    module: str = Field(min_length=1)
    title: str = Field(min_length=1)
    precondition: str = Field(min_length=1)
    steps: str = Field(min_length=1)
    test_data: str = Field(min_length=1)
    expected_result: str = Field(min_length=1)
    priority: Literal["High", "Medium", "Low"]
    type: Literal[
        "Positive", "Negative", "Edge case", "UI/UX", "Compatibility", "Performance", "Security"
    ]
    platform: Literal["Web", "iOS", "Android", "All"]


class TestCaseSummary(BaseModel):
    total: int
    by_type: dict[str, int]
    open_questions: list[str]


class GenerationResult(BaseModel):
    test_cases: list[TestCase]
    summary: TestCaseSummary


class CoverageGap(BaseModel):
    description: str = Field(min_length=1)
    suggested_type: Literal[
        "Positive", "Negative", "Edge case", "UI/UX", "Compatibility", "Performance", "Security"
    ]
    severity: Literal["High", "Medium", "Low"]


class DuplicateGroup(BaseModel):
    test_ids: list[str] = Field(min_length=2)
    reason: str = Field(min_length=1)


class ReviewResult(BaseModel):
    coverage_score: int = Field(ge=0, le=100)
    missing_test_types: list[str]
    gaps: list[CoverageGap]
    duplicates: list[DuplicateGroup]
    summary_note: str


class AIClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        client: Any | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
        sleep_fn: Any = time.sleep,
    ):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if client is None and not self.api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is missing. Set the environment variable or "
                "pass api_key when constructing AIClient."
            )
        self.client = client or anthropic.Anthropic(api_key=self.api_key)
        self.model = model
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep_fn

    def _build_usage(self, usage: Any) -> dict:
        def value(name: str) -> int:
            return int(getattr(usage, name, 0) or 0)

        input_tokens = value("input_tokens")
        output_tokens = value("output_tokens")
        cache_write_tokens = value("cache_creation_input_tokens")
        cache_read_tokens = value("cache_read_input_tokens")
        pricing = MODEL_PRICING.get(self.model)
        estimated_cost = None
        if pricing:
            estimated_cost = (
                input_tokens * pricing["input"]
                + cache_write_tokens * pricing["cache_write"]
                + cache_read_tokens * pricing["cache_read"]
                + output_tokens * pricing["output"]
            ) / 1_000_000

        return {
            "model": self.model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_write_tokens,
            "cache_read_input_tokens": cache_read_tokens,
            "total_input_tokens": input_tokens + cache_write_tokens + cache_read_tokens,
            "estimated_cost_usd": estimated_cost,
        }

    def _call_ai(self, system_prompt: str, user_content: str, output_format: type[BaseModel]):
        """
        Shared retry/error-handling wrapper around client.messages.parse.
        Returns the raw `message` object (caller extracts parsed_output/
        usage). Raises ValueError with a user-facing message on failure.
        """
        attempt = 0
        while True:
            try:
                message = self.client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    # Cache the base prompt + project config: unchanged across
                    # generations within the same session/project -> lowers cost.
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[{"role": "user", "content": user_content}],
                    output_format=output_format,
                )
                break
            except anthropic.AuthenticationError:
                raise ValueError("Invalid API key. Please check your ANTHROPIC_API_KEY.")
            except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
                attempt += 1
                if attempt > self.max_retries:
                    if isinstance(e, anthropic.RateLimitError):
                        raise ValueError(
                            "Anthropic API rate limit exceeded. Please try again in a few minutes."
                        ) from e
                    raise ValueError(
                        "Could not connect to the Anthropic API. Check your network connection."
                    ) from e
                self._sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
            except anthropic.APIStatusError as e:
                raise ValueError(f"Anthropic API returned an error ({e.status_code}): {e.message}")

        if message.stop_reason == "max_tokens":
            raise ValueError(
                "The AI's response was cut off after exceeding max_tokens before "
                "finishing the JSON. Try a shorter/more specific requirement, or "
                "split it into multiple generation runs."
            )
        if message.parsed_output is None:
            raise ValueError(
                "The AI did not return a result matching the expected schema "
                "(test_cases/summary)."
            )
        return message

    def generate_test_cases(self, system_prompt: str, requirement_text: str) -> dict:
        """
        Send the requirement + system prompt (already merged with the project
        config) to Claude, and return a dict {"test_cases": [...], "summary":
        {...}} validated against the schema (Structured Outputs), ready for
        excel_exporter/app.py.
        """
        message = self._call_ai(
            system_prompt,
            f"Requirement/User Story to write test cases for:\n\n{requirement_text}",
            GenerationResult,
        )
        parsed_result = message.parsed_output.model_dump()
        result = build_edited_result(parsed_result, parsed_result["test_cases"])
        result["usage"] = self._build_usage(message.usage)
        return result

    def review_test_cases(self, system_prompt: str, requirement_text: str, test_cases: list[dict]) -> dict:
        """
        Send the requirement + an existing test case set to Claude for a
        coverage review. Returns {"review": {...ReviewResult...}, "usage": {...}}.
        """
        test_cases_json = json.dumps(test_cases, ensure_ascii=False, indent=2)
        message = self._call_ai(
            system_prompt,
            (
                f"Requirement/User Story:\n\n{requirement_text}\n\n"
                f"Existing test cases (JSON):\n\n{test_cases_json}"
            ),
            ReviewResult,
        )
        return {
            "review": message.parsed_output.model_dump(),
            "usage": self._build_usage(message.usage),
        }
