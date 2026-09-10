"""
Module chịu trách nhiệm gọi Claude API để sinh test case.
"""
import os
import time
from typing import Any
from typing import Literal

import anthropic
from pydantic import BaseModel, ConfigDict, Field

from core.result_utils import build_edited_result

DEFAULT_MODEL = "claude-sonnet-5"

# Số lần thử lại tối đa khi gặp lỗi tạm thời (rate limit / mất kết nối),
# với backoff tăng dần: retry_backoff_seconds * 2^(lần thử - 1).
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 1.0

# USD trên một triệu token. Cache write dùng TTL mặc định 5 phút.
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
                "Chưa có ANTHROPIC_API_KEY. Hãy set biến môi trường hoặc "
                "truyền api_key khi khởi tạo AIClient."
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

    def generate_test_cases(self, system_prompt: str, requirement_text: str) -> dict:
        """
        Gửi requirement + system prompt (đã ghép config project) tới Claude,
        trả về dict {"test_cases": [...], "summary": {...}} đã được validate
        theo schema (Structured Outputs), sẵn sàng cho excel_exporter/app.py.
        """
        attempt = 0
        while True:
            try:
                message = self.client.messages.parse(
                    model=self.model,
                    max_tokens=16000,
                    # Cache base prompt + config project: không đổi giữa các lần
                    # sinh test case trong cùng 1 session/project -> giảm chi phí.
                    system=[
                        {
                            "type": "text",
                            "text": system_prompt,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                    messages=[
                        {
                            "role": "user",
                            "content": f"Requirement/User Story cần viết test case:\n\n{requirement_text}",
                        }
                    ],
                    output_format=GenerationResult,
                )
                break
            except anthropic.AuthenticationError:
                raise ValueError("API key không hợp lệ. Vui lòng kiểm tra lại ANTHROPIC_API_KEY.")
            except (anthropic.RateLimitError, anthropic.APIConnectionError) as e:
                attempt += 1
                if attempt > self.max_retries:
                    if isinstance(e, anthropic.RateLimitError):
                        raise ValueError(
                            "Đã vượt rate limit của Anthropic API. Vui lòng thử lại sau ít phút."
                        ) from e
                    raise ValueError(
                        "Không kết nối được tới Anthropic API. Kiểm tra lại kết nối mạng."
                    ) from e
                self._sleep(self.retry_backoff_seconds * (2 ** (attempt - 1)))
            except anthropic.APIStatusError as e:
                raise ValueError(f"Anthropic API trả về lỗi ({e.status_code}): {e.message}")

        if message.stop_reason == "max_tokens":
            raise ValueError(
                "Phản hồi của AI bị cắt do vượt giới hạn max_tokens trước khi hoàn "
                "thành JSON. Hãy thử requirement ngắn/cụ thể hơn, hoặc tách nhỏ thành "
                "nhiều lần sinh test case."
            )

        if message.parsed_output is None:
            raise ValueError(
                "AI không trả về kết quả đúng schema mong đợi (test_cases/summary)."
            )

        parsed_result = message.parsed_output.model_dump()
        result = build_edited_result(parsed_result, parsed_result["test_cases"])
        result["usage"] = self._build_usage(message.usage)
        return result
