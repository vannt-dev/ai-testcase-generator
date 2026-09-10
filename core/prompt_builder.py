"""
Module ghép base system prompt với config đặc thù của từng project (YAML)
để tạo ra system prompt cuối cùng gửi cho AI.
"""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import yaml

BASE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "base_system_prompt.md"

# Ước lượng token ~ số ký tự / 4 (kinh nghiệm chung cho text tiếng Anh/Việt).
# Ngưỡng cảnh báo khi domain_rules/glossary quá dài, làm tăng chi phí input
# mỗi lần gọi API (system prompt được cache nhưng vẫn tính phí cache write).
CHARS_PER_TOKEN_ESTIMATE = 4
SYSTEM_PROMPT_TOKEN_WARNING_THRESHOLD = 8000


class ProjectConfigError(ValueError):
    """Lỗi cấu hình project có nội dung thân thiện để hiển thị trên UI."""


class ProjectConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_name: str = Field(min_length=1)
    platform: list[Literal["web", "ios", "android"]] = Field(min_length=1)
    test_id_format: str = Field(min_length=1)
    test_types_required: list[
        Literal[
            "positive",
            "negative",
            "edge_case",
            "ui_ux",
            "compatibility",
            "performance",
            "security",
        ]
    ] = Field(min_length=1)
    domain_rules: list[str] = Field(default_factory=list)
    glossary: dict[str, str] = Field(default_factory=dict)
    notes: str = ""

    @field_validator("platform", "test_types_required", mode="before")
    @classmethod
    def normalize_list_values(cls, value):
        if isinstance(value, list):
            return list(dict.fromkeys(str(item).strip().lower() for item in value))
        return value

    @field_validator("test_id_format")
    @classmethod
    def validate_test_id_format(cls, value: str) -> str:
        missing = [token for token in ("{MODULE}", "{NUMBER}") if token not in value]
        if missing:
            raise ValueError(f"phải chứa placeholder: {', '.join(missing)}")
        return value

    @field_validator("domain_rules")
    @classmethod
    def validate_domain_rules(cls, value: list[str]) -> list[str]:
        if any(not rule.strip() for rule in value):
            raise ValueError("không được chứa rule rỗng")
        return value


def _format_validation_error(config_path: Path, error: ValidationError) -> ProjectConfigError:
    details = []
    for item in error.errors(include_url=False):
        field = ".".join(str(part) for part in item["loc"])
        details.append(f"- {field}: {item['msg']}")
    return ProjectConfigError(
        f"Config '{config_path.name}' không hợp lệ:\n" + "\n".join(details)
    )


def load_base_prompt() -> str:
    return BASE_PROMPT_PATH.read_text(encoding="utf-8")


def load_project_config(config_path: str | Path) -> dict:
    config_path = Path(config_path)
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except FileNotFoundError as error:
        raise ProjectConfigError(f"Không tìm thấy config: {config_path}") from error
    except OSError as error:
        raise ProjectConfigError(f"Không đọc được config '{config_path.name}': {error}") from error
    except yaml.YAMLError as error:
        raise ProjectConfigError(
            f"Config '{config_path.name}' sai cú pháp YAML: {error}"
        ) from error

    if not isinstance(raw_config, dict):
        raise ProjectConfigError(
            f"Config '{config_path.name}' phải là một YAML object, không được rỗng."
        )

    try:
        return ProjectConfig.model_validate(raw_config).model_dump()
    except ValidationError as error:
        raise _format_validation_error(config_path, error) from error


def build_system_prompt(config: dict) -> str:
    """
    Ghép base prompt + thông tin config project thành 1 system prompt hoàn chỉnh.
    """
    base_prompt = load_base_prompt()

    domain_rules = "\n".join(f"- {rule}" for rule in config.get("domain_rules", [])) or "- (Không có)"
    glossary = "\n".join(
        f"- {term}: {definition}" for term, definition in config.get("glossary", {}).items()
    ) or "- (Không có)"
    platforms = ", ".join(config.get("platform", ["Web"]))
    required_types = ", ".join(config.get("test_types_required", []))

    project_context = f"""

===================== CẤU HÌNH PROJECT: {config.get("project_name", "N/A")} =====================
Nền tảng áp dụng: {platforms}
Test ID format: {config.get("test_id_format", "TC_{MODULE}_{NUMBER}")}
Các loại test case bắt buộc cân nhắc: {required_types}

Domain rules (bắt buộc tuân thủ khi sinh test case):
{domain_rules}

Glossary (thuật ngữ riêng của hệ thống):
{glossary}

Ghi chú thêm: {config.get("notes", "(Không có)")}
=================================================================================================
"""
    return base_prompt + project_context


def estimate_prompt_size_warning(prompt: str) -> str | None:
    """
    Trả về cảnh báo (hoặc None) nếu system prompt ước tính vượt ngưỡng token,
    để UI báo trước cho người dùng biết chi phí input có thể tăng.
    """
    estimated_tokens = len(prompt) // CHARS_PER_TOKEN_ESTIMATE
    if estimated_tokens <= SYSTEM_PROMPT_TOKEN_WARNING_THRESHOLD:
        return None
    return (
        f"System prompt của project này khá lớn (~{estimated_tokens:,} token ước tính). "
        "Domain rules/glossary dài sẽ làm tăng chi phí input mỗi lần gọi API — "
        "cân nhắc rút gọn nếu không thực sự cần thiết."
    )


def list_available_configs(configs_dir: str | Path = "configs") -> list[str]:
    """Liệt kê các file config project khả dụng (bỏ qua template)."""
    configs_dir = Path(configs_dir)
    return sorted(
        f.stem for f in configs_dir.glob("*.yaml") if not f.stem.startswith("_")
    )
