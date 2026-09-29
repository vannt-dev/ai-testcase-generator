"""The rendered fixture project must match the reviewed golden files exactly."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
GOLDEN = ROOT / "tests" / "fixtures" / "automation" / "golden"


def _render_fixture():
    spec = importlib.util.spec_from_file_location("render_fixture", ROOT / "scripts" / "render_automation_fixture.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render_fixture()


def test_fixture_project_matches_golden_files():
    rendered = _render_fixture()
    golden = {
        path.relative_to(GOLDEN).as_posix(): path.read_text(encoding="utf-8").replace("\r\n", "\n")
        for path in GOLDEN.rglob("*") if path.is_file()
    }

    assert sorted(rendered) == sorted(golden)
    for path, content in rendered.items():
        assert content == golden[path], f"{path} differs; if intended, regenerate the golden files"
