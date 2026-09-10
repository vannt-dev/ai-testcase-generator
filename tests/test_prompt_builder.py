from pathlib import Path

from core.prompt_builder import (
    ProjectConfigError,
    build_system_prompt,
    estimate_prompt_size_warning,
    list_available_configs,
    load_project_config,
)
import pytest

CONFIGS_DIR = Path(__file__).parent.parent / "configs"


def test_load_project_config_parses_yaml():
    config = load_project_config(CONFIGS_DIR / "example_ecommerce.yaml")
    assert config["project_name"] == "E-commerce App Demo"
    assert config["platform"] == ["web", "ios", "android"]
    assert "Voucher" in config["glossary"]


def test_list_available_configs_excludes_template():
    configs = list_available_configs(CONFIGS_DIR)
    assert "example_ecommerce" in configs
    assert "_template" not in configs


def test_build_system_prompt_includes_base_prompt_and_project_context():
    config = load_project_config(CONFIGS_DIR / "example_ecommerce.yaml")
    prompt = build_system_prompt(config)

    # Base prompt content phải có mặt
    assert "Senior QA Engineer" in prompt
    assert '"test_cases"' in prompt

    # Config project phải được ghép vào
    assert "E-commerce App Demo" in prompt
    assert "web, ios, android" in prompt
    assert "Số điện thoại VN: 10 số, bắt đầu bằng 0" in prompt
    assert "SKU: Mã định danh sản phẩm" in prompt


def test_build_system_prompt_handles_missing_optional_fields():
    minimal_config = {
        "project_name": "Minimal Project",
        "platform": ["web"],
        "test_id_format": "TC_{MODULE}_{NUMBER}",
        "test_types_required": ["positive"],
    }
    prompt = build_system_prompt(minimal_config)

    assert "Minimal Project" in prompt
    assert "(Không có)" in prompt  # domain_rules và glossary rỗng


def test_load_project_config_reports_missing_required_fields(tmp_path):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("project_name: Demo\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError) as error:
        load_project_config(config_path)

    message = str(error.value)
    assert "invalid.yaml" in message
    assert "platform" in message
    assert "test_id_format" in message


def test_load_project_config_reports_invalid_yaml(tmp_path):
    config_path = tmp_path / "broken.yaml"
    config_path.write_text("project_name: [broken\n", encoding="utf-8")

    with pytest.raises(ProjectConfigError, match="sai cú pháp YAML"):
        load_project_config(config_path)


def test_load_project_config_normalizes_case_and_removes_duplicates(tmp_path):
    config_path = tmp_path / "valid.yaml"
    config_path.write_text(
        """project_name: Demo
platform: [Web, web, IOS]
test_id_format: TC_{MODULE}_{NUMBER}
test_types_required: [Positive, positive, Security]
""",
        encoding="utf-8",
    )

    config = load_project_config(config_path)

    assert config["platform"] == ["web", "ios"]
    assert config["test_types_required"] == ["positive", "security"]


def test_estimate_prompt_size_warning_none_for_short_prompt():
    assert estimate_prompt_size_warning("prompt ngắn") is None


def test_estimate_prompt_size_warning_flags_large_prompt():
    huge_prompt = "a" * 40000  # ~10,000 token ước tính, vượt ngưỡng 8,000

    warning = estimate_prompt_size_warning(huge_prompt)

    assert warning is not None
    assert "10,000" in warning
