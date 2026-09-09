"""
Module chịu trách nhiệm gọi Claude API để sinh test case.
"""
import json
import os
import anthropic

DEFAULT_MODEL = "claude-sonnet-5"


class AIClient:
    def __init__(self, api_key: str | None = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Chưa có ANTHROPIC_API_KEY. Hãy set biến môi trường hoặc "
                "truyền api_key khi khởi tạo AIClient."
            )
        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.model = model

    def generate_test_cases(self, system_prompt: str, requirement_text: str) -> dict:
        """
        Gửi requirement + system prompt (đã ghép config project) tới Claude,
        trả về dict đã parse từ JSON response.
        """
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": f"Requirement/User Story cần viết test case:\n\n{requirement_text}",
                    }
                ],
            )
        except anthropic.AuthenticationError:
            raise ValueError("API key không hợp lệ. Vui lòng kiểm tra lại ANTHROPIC_API_KEY.")
        except anthropic.RateLimitError:
            raise ValueError("Đã vượt rate limit của Anthropic API. Vui lòng thử lại sau ít phút.")
        except anthropic.APIConnectionError:
            raise ValueError("Không kết nối được tới Anthropic API. Kiểm tra lại kết nối mạng.")
        except anthropic.APIStatusError as e:
            raise ValueError(f"Anthropic API trả về lỗi ({e.status_code}): {e.message}")

        if message.stop_reason == "max_tokens":
            raise ValueError(
                "Phản hồi của AI bị cắt do vượt giới hạn max_tokens trước khi hoàn "
                "thành JSON. Hãy thử requirement ngắn/cụ thể hơn, hoặc tách nhỏ thành "
                "nhiều lần sinh test case."
            )

        raw_text = "".join(
            block.text for block in message.content if block.type == "text"
        ).strip()

        cleaned = raw_text.replace("```json", "").replace("```", "").strip()

        # Phòng trường hợp model kèm theo text giải thích trước/sau khối JSON
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            cleaned = cleaned[start : end + 1]

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"AI trả về không đúng định dạng JSON. Lỗi: {e}\n\nRaw response:\n{raw_text}"
            )
