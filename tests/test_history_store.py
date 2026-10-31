"""Tests for core.history_store: generation history saved as one JSON file per entry."""
import json

import pytest

from core.history_store import REQUIRED_KEYS, clear_entries, load_entries, save_entry


def _entry(n: int = 1, **overrides) -> dict:
    entry = {
        "timestamp": f"2026-10-31 10:00:{n:02d}",
        "project_name": "Shop",
        "requirement_excerpt": f"Requirement {n}",
        "test_case_count": 1,
        "result": {"test_cases": [{"id": f"TC-{n}", "title": "Đăng nhập bằng OTP"}]},
        "config": {"project_name": "Shop", "platform": ["web"]},
        "requirement_text": f"Full requirement {n} — người dùng đăng nhập",
    }
    entry.update(overrides)
    return entry


def test_saved_entry_loads_back_unchanged_with_an_id(tmp_path):
    entry_id = save_entry(tmp_path, _entry())

    entries, warnings = load_entries(tmp_path, limit=10)

    assert warnings == []
    assert len(entries) == 1
    loaded = entries[0]
    assert loaded.pop("id") == entry_id
    assert loaded == _entry()


def test_save_creates_the_folder(tmp_path):
    folder = tmp_path / "history"

    save_entry(folder, _entry())

    assert len(list(folder.glob("*.json"))) == 1


def test_entries_load_oldest_first_and_limit_keeps_the_newest(tmp_path):
    for n in range(1, 6):
        save_entry(tmp_path, _entry(n))

    entries, _ = load_entries(tmp_path, limit=3)

    assert [e["requirement_excerpt"] for e in entries] == [
        "Requirement 3",
        "Requirement 4",
        "Requirement 5",
    ]


def test_saving_beyond_keep_deletes_the_oldest_files(tmp_path):
    for n in range(1, 5):
        save_entry(tmp_path, _entry(n), keep=3)

    assert len(list(tmp_path.glob("*.json"))) == 3
    entries, _ = load_entries(tmp_path, limit=10)
    assert [e["requirement_excerpt"] for e in entries] == [
        "Requirement 2",
        "Requirement 3",
        "Requirement 4",
    ]


def test_default_keep_is_fifty(tmp_path):
    for n in range(51):
        save_entry(tmp_path, _entry(n % 60))

    assert len(list(tmp_path.glob("*.json"))) == 50


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        json.dumps(["a", "list"]),
        json.dumps({key: "x" for key in REQUIRED_KEYS if key != "result"}),
        json.dumps({**_entry(), "result": "not a dict"}),
        json.dumps({**_entry(), "test_case_count": "three"}),
    ],
    ids=["bad-json", "not-a-dict", "missing-key", "result-wrong-type", "count-wrong-type"],
)
def test_a_bad_file_is_skipped_with_a_warning(tmp_path, content):
    save_entry(tmp_path, _entry(1))
    (tmp_path / "20260101-000000-000000-bad000.json").write_text(content, encoding="utf-8")
    save_entry(tmp_path, _entry(2))

    entries, warnings = load_entries(tmp_path, limit=10)

    assert [e["requirement_excerpt"] for e in entries] == ["Requirement 1", "Requirement 2"]
    assert len(warnings) == 1
    assert "20260101-000000-000000-bad000.json" in warnings[0]


def test_a_file_that_is_not_utf8_is_skipped_with_a_warning(tmp_path):
    (tmp_path / "20260101-000000-000000-bad000.json").write_bytes(b"\xff\xfe\x00bad")

    entries, warnings = load_entries(tmp_path, limit=10)

    assert entries == []
    assert len(warnings) == 1


def test_a_missing_folder_loads_nothing(tmp_path):
    assert load_entries(tmp_path / "nope", limit=10) == ([], [])


def test_clear_removes_only_history_files(tmp_path):
    save_entry(tmp_path, _entry(1))
    save_entry(tmp_path, _entry(2))
    (tmp_path / "leftover.json.tmp").write_text("{", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")

    removed = clear_entries(tmp_path)

    assert removed == 2
    assert list(tmp_path.glob("*.json")) == []
    assert not (tmp_path / "leftover.json.tmp").exists()
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "keep me"


def test_clear_on_a_missing_folder_removes_nothing(tmp_path):
    assert clear_entries(tmp_path / "nope") == 0


def test_save_into_a_path_that_is_a_file_raises_oserror(tmp_path):
    blocker = tmp_path / "history"
    blocker.write_text("I am a file", encoding="utf-8")

    with pytest.raises(OSError):
        save_entry(blocker, _entry())


def test_values_json_cannot_encode_are_saved_as_text(tmp_path):
    import datetime

    save_entry(tmp_path, _entry(config={"project_name": "Shop", "since": datetime.date(2026, 1, 2)}))

    entries, warnings = load_entries(tmp_path, limit=10)

    assert warnings == []
    assert entries[0]["config"]["since"] == "2026-01-02"
