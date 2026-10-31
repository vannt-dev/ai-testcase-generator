"""Shared test setup."""
import pytest


@pytest.fixture(autouse=True)
def isolated_history_dir(tmp_path, monkeypatch):
    """Point the app's history folder at a temporary one, so tests never touch `history/`."""
    folder = tmp_path / "history"
    monkeypatch.setenv("TESTCASE_HISTORY_DIR", str(folder))
    return folder
