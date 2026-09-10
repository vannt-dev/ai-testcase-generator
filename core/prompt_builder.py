"""
Merges the base system prompt with each project's config (YAML) to
produce the final system prompt sent to the AI.
"""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
import yaml

BASE_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "base_system_prompt.md"
REVIEWER_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "reviewer_system_prompt.md"
COLUMN_MAPPING_PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "column_mapping_system_prompt.md"

# Rough token estimate ~ character count / 4 (common rule of thumb for
# English/Vietnamese text). Threshold used to warn when domain_rules/
# glossary get too long, which increases input cost per API call (the
# system prompt is cached but cache writes are still billed).
CHARS_PER_TOKEN_ESTIMATE = 4
SYSTEM_PROMPT_TOKEN_WARNING_THRESHOLD = 8000


class ProjectConfigError(ValueError):
    """Project config error with a user-friendly message for the UI."""


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
            raise ValueError(f"must contain placeholder(s): {', '.join(missing)}")
        return value

    @field_validator("domain_rules")
    @classmethod
    def validate_domain_rules(cls, value: list[str]) -> list[str]:
        if any(not rule.strip() for rule in value):
            raise ValueError("must not contain empty rules")
        return value


def _format_validation_error(config_path: Path, error: ValidationError) -> ProjectConfigError:
    details = []
    for item in error.errors(include_url=False):
        field = ".".join(str(part) for part in item["loc"])
        details.append(f"- {field}: {item['msg']}")
    return ProjectConfigError(
        f"Config '{config_path.name}' is invalid:\n" + "\n".join(details)
    )


def load_base_prompt(path: Path = BASE_PROMPT_PATH) -> str:
    return path.read_text(encoding="utf-8")


def load_column_mapping_prompt() -> str:
    return COLUMN_MAPPING_PROMPT_PATH.read_text(encoding="utf-8")


def load_project_config(config_path: str | Path) -> dict:
    config_path = Path(config_path)
    try:
        with config_path.open("r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f)
    except FileNotFoundError as error:
        raise ProjectConfigError(f"Config not found: {config_path}") from error
    except OSError as error:
        raise ProjectConfigError(f"Could not read config '{config_path.name}': {error}") from error
    except yaml.YAMLError as error:
        raise ProjectConfigError(
            f"Config '{config_path.name}' has invalid YAML syntax: {error}"
        ) from error

    if not isinstance(raw_config, dict):
        raise ProjectConfigError(
            f"Config '{config_path.name}' must be a non-empty YAML object."
        )

    try:
        return ProjectConfig.model_validate(raw_config).model_dump()
    except ValidationError as error:
        raise _format_validation_error(config_path, error) from error


def build_system_prompt(config: dict, base_prompt_path: Path = BASE_PROMPT_PATH) -> str:
    """
    Merge a base prompt with the project config info into one final
    system prompt. `base_prompt_path` defaults to the Generator's base
    prompt; pass REVIEWER_PROMPT_PATH to build the Reviewer's instead.
    """
    base_prompt = load_base_prompt(base_prompt_path)

    domain_rules = "\n".join(f"- {rule}" for rule in config.get("domain_rules", [])) or "- (None)"
    glossary = "\n".join(
        f"- {term}: {definition}" for term, definition in config.get("glossary", {}).items()
    ) or "- (None)"
    platforms = ", ".join(config.get("platform", ["Web"]))
    required_types = ", ".join(config.get("test_types_required", []))

    project_context = f"""

===================== PROJECT CONFIG: {config.get("project_name", "N/A")} =====================
Target platforms: {platforms}
Test ID format: {config.get("test_id_format", "TC_{MODULE}_{NUMBER}")}
Test types required to be considered: {required_types}

Domain rules (must be followed when generating test cases):
{domain_rules}

Glossary (system-specific terminology):
{glossary}

Additional notes: {config.get("notes", "(None)")}
=================================================================================================
"""
    return base_prompt + project_context


def estimate_prompt_size_warning(prompt: str) -> str | None:
    """
    Return a warning (or None) if the estimated system prompt size exceeds
    the token threshold, so the UI can warn about rising input cost.
    """
    estimated_tokens = len(prompt) // CHARS_PER_TOKEN_ESTIMATE
    if estimated_tokens <= SYSTEM_PROMPT_TOKEN_WARNING_THRESHOLD:
        return None
    return (
        f"This project's system prompt is quite large (~{estimated_tokens:,} "
        "estimated tokens). Long domain rules/glossary entries increase input "
        "cost on every API call — consider trimming them if not strictly needed."
    )


def list_available_configs(configs_dir: str | Path = "configs") -> list[str]:
    """List available project config files (excluding the template)."""
    configs_dir = Path(configs_dir)
    return sorted(
        f.stem for f in configs_dir.glob("*.yaml") if not f.stem.startswith("_")
    )
