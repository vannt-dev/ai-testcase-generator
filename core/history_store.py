"""Generation history on disk: one JSON file per entry in a history folder.

File names start with the save time (``YYYYMMDD-HHMMSS-ffffff``), so sorting them by name
gives the order the entries were saved in; a random suffix keeps two saves apart. The name
without ``.json`` is the entry's ``id``.

Entries never hold an API key: they keep the project config, the requirement, the result and
the result's usage (provider, model, token counts).

Saving to disk is opt-in: only when `TESTCASE_HISTORY_DIR` names a folder. Without it the app
keeps each browser session's runs in that session only, so on a shared or hosted server one
visitor never sees, restores or deletes another visitor's runs.
"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta
from pathlib import Path

DEFAULT_KEEP = 50
# The folder the history is saved in; unset or empty keeps it in the browser session only.
FOLDER_ENV = "TESTCASE_HISTORY_DIR"

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
_ID_PATTERN = re.compile(r"\d{8}-\d{6}-\d{6}-[0-9a-z]+")


def history_dir() -> Path | None:
    """The history folder `TESTCASE_HISTORY_DIR` names, or None to keep runs in the session only.

    There is no default folder: a server shared by several people would show every visitor's
    runs to everyone. Whoever runs the app for themselves turns saving on.
    """
    value = os.environ.get(FOLDER_ENV, "").strip()
    return Path(value) if value else None


def _entry_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.json"), key=lambda path: path.name)


def new_entry_id(newest_id: str | None = None) -> str:
    """A new entry id that sorts after `newest_id`, the newest id so far (None: there is none).

    The id starts with the current time, moved past the newest id's when the clock hasn't
    moved on: Windows clocks can tick in steps of several milliseconds, so two quick saves
    could otherwise get the same time and sort in random order.
    """
    now = datetime.now()
    if newest_id:
        try:
            newest = datetime.strptime(newest_id[:_STAMP_LENGTH], _STAMP_FORMAT)
        except ValueError:
            newest = None
        if newest is not None and newest >= now:
            now = newest + timedelta(microseconds=1)
    return f"{now.strftime(_STAMP_FORMAT)}-{secrets.token_hex(3)}"


def save_entry(folder: Path, entry: dict, keep: int = DEFAULT_KEEP) -> str:
    """Write `entry` as a new file in `folder`, drop the oldest files beyond `keep`.

    Returns the new entry's id. Raises OSError when the folder or file can't be written.
    """
    folder.mkdir(parents=True, exist_ok=True)
    existing = _entry_files(folder)
    entry_id = new_entry_id(existing[-1].stem if existing else None)
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


def delete_entry(folder: Path, entry_id: str) -> bool:
    """Delete one entry's file; return whether it was there.

    Only an id shaped like the ones `save_entry` gives is accepted, so a crafted id can't
    reach a file outside `folder`. Raises OSError when the file can't be deleted.
    """
    if not _ID_PATTERN.fullmatch(entry_id):
        raise ValueError(f"Not a history entry id: {entry_id!r}")
    path = folder / f"{entry_id}.json"
    (folder / f"{entry_id}.json.tmp").unlink(missing_ok=True)
    if not path.is_file():
        return False
    path.unlink()
    return True


def provider_and_model(entry: dict) -> tuple[str, str]:
    """The AI provider and model that made the entry's result, or "" when it doesn't say."""
    usage = entry.get("result", {}).get("usage") or {}
    if not isinstance(usage, dict):
        return "", ""
    model = str(usage.get("model") or "")
    # Results from before other providers were added only came from Claude.
    provider = str(usage.get("provider") or ("anthropic" if model else ""))
    return provider, model


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
