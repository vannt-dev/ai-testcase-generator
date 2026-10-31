"""Generation history on disk: one JSON file per entry in a history folder.

File names start with the save time (``YYYYMMDD-HHMMSS-ffffff``), so sorting them by name
gives the order the entries were saved in; a random suffix keeps two saves apart. The name
without ``.json`` is the entry's ``id``.
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_KEEP = 50

# The fields every entry has, and the type each must be for the entry to be restorable.
REQUIRED_KEYS: dict[str, type] = {
    "timestamp": str,
    "project_name": str,
    "requirement_excerpt": str,
    "test_case_count": int,
    "result": dict,
    "config": dict,
    "requirement_text": str,
}

_STAMP_FORMAT = "%Y%m%d-%H%M%S-%f"
_STAMP_LENGTH = len("YYYYMMDD-HHMMSS-ffffff")


def _entry_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.json"), key=lambda path: path.name)


def _next_stamp(existing: list[Path]) -> str:
    """The current time, moved past the newest file's when the clock hasn't moved on.

    Windows clocks can tick in steps of several milliseconds, so two quick saves could
    otherwise get the same time and sort in random order.
    """
    now = datetime.now()
    if existing:
        try:
            newest = datetime.strptime(existing[-1].name[:_STAMP_LENGTH], _STAMP_FORMAT)
        except ValueError:
            newest = None
        if newest is not None and newest >= now:
            now = newest + timedelta(microseconds=1)
    return now.strftime(_STAMP_FORMAT)


def save_entry(folder: Path, entry: dict, keep: int = DEFAULT_KEEP) -> str:
    """Write `entry` as a new file in `folder`, drop the oldest files beyond `keep`.

    Returns the new entry's id. Raises OSError when the folder or file can't be written.
    """
    folder.mkdir(parents=True, exist_ok=True)
    existing = _entry_files(folder)
    entry_id = f"{_next_stamp(existing)}-{secrets.token_hex(3)}"
    path = folder / f"{entry_id}.json"
    temp_path = folder / f"{entry_id}.json.tmp"
    try:
        with temp_path.open("w", encoding="utf-8") as file:
            json.dump(entry, file, ensure_ascii=False, indent=2, default=str)
        os.replace(temp_path, path)
    except (OSError, TypeError, ValueError) as error:
        temp_path.unlink(missing_ok=True)
        if isinstance(error, OSError):
            raise
        raise OSError(f"Couldn't encode the history entry: {error}") from error

    for old in _entry_files(folder)[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return entry_id


def _problem(data: object) -> str | None:
    if not isinstance(data, dict):
        return "it isn't a JSON object"
    for key, expected in REQUIRED_KEYS.items():
        if key not in data:
            return f"'{key}' is missing"
        value = data[key]
        if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
            return f"'{key}' isn't a {expected.__name__}"
    return None


def load_entries(folder: Path, limit: int) -> tuple[list[dict], list[str]]:
    """The newest `limit` valid entries, oldest first, each with its `id`.

    Files that can't be read or don't hold a valid entry are skipped; each gives a warning.
    """
    entries: list[dict] = []
    warnings: list[str] = []
    for path in reversed(_entry_files(folder)):
        if len(entries) >= limit:
            break
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            warnings.append(f"Skipped history file {path.name}: it can't be read ({error}).")
            continue
        problem = _problem(data)
        if problem:
            warnings.append(f"Skipped history file {path.name}: {problem}.")
            continue
        data["id"] = path.stem
        entries.append(data)
    entries.reverse()
    return entries, warnings


def clear_entries(folder: Path) -> int:
    """Delete every history file in `folder` (and unfinished writes); return how many entries."""
    if not folder.is_dir():
        return 0
    removed = 0
    for path in _entry_files(folder):
        path.unlink(missing_ok=True)
        removed += 1
    for temp_path in folder.glob("*.json.tmp"):
        temp_path.unlink(missing_ok=True)
    return removed
