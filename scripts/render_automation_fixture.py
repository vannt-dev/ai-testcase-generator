"""
Render tests/fixtures/automation/ai_output.json into a Playwright project.

    python scripts/render_automation_fixture.py <out_dir>

CI type-checks the output. To refresh the golden files after an intended
renderer change:

    python scripts/render_automation_fixture.py tests/fixtures/automation/golden
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.automation_validate import validate_automation  # noqa: E402
from core.playwright_renderer import render_project  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "automation" / "ai_output.json"


def render_fixture() -> dict[str, str]:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result, _ = validate_automation(fixture["ai_output"], fixture["modules"])
    return render_project(result, fixture["project_name"], fixture["base_url"])


def main(out_dir: str) -> None:
    out = Path(out_dir)
    for path, content in render_fixture().items():
        target = out / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/render_automation_fixture.py <out_dir>")
    main(sys.argv[1])
