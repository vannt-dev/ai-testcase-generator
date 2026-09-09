"""
Module ghép base system prompt với config đặc thù của từng project (YAML)
để tạo ra system prompt cuối cùng gửi cho AI.
"""
from pathlib import Path
import yaml

BASE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "base_system_prompt.md"


def load_base_prompt() -> str:
    return BASE_PROMPT_PATH.read_text(encoding="utf-8")


def load_project_config(config_path: str | Path) -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def list_available_configs(configs_dir: str | Path = "configs") -> list[str]:
    """Liệt kê các file config project khả dụng (bỏ qua template)."""
    configs_dir = Path(configs_dir)
    return sorted(
        f.stem for f in configs_dir.glob("*.yaml") if not f.stem.startswith("_")
    )
