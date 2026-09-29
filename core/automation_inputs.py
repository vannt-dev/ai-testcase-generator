"""Input checks for the Automation page, kept out of Streamlit so they can be unit tested."""
import hashlib
import json
import re

MAX_CASES = 10
MAX_PAGES = 10
MAX_SNAPSHOT_CHARS = 50_000
WEB_PLATFORMS = {"web", "all", ""}
BASE_URL = re.compile(r"^https?://[^\s/]+\S*$")


def web_cases(cases: list[dict]) -> list[dict]:
    """Test cases a browser can run; uploads without a platform column count as web."""
    return [case for case in cases if str(case.get("platform") or "").strip().lower() in WEB_PLATFORMS]


def input_problems(selected: list[dict], base_url: str, pages: list[dict]) -> list[str]:
    problems = []
    if not selected:
        problems.append("Select at least one test case.")
    elif len(selected) > MAX_CASES:
        problems.append(f"Select at most {MAX_CASES} test cases per generation ({len(selected)} selected).")
    if not BASE_URL.match(base_url.strip()):
        problems.append("Enter a Base URL that starts with http:// or https://.")
    if len(pages) > MAX_PAGES:
        problems.append(f"Describe at most {MAX_PAGES} pages ({len(pages)} given).")
    if any(not page["name"].strip() or not page["path"].strip() for page in pages):
        problems.append("Every page needs a name and a path.")
    names = [page["name"].strip().casefold() for page in pages if page["name"].strip()]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        problems.append(f"Page names must be unique: {', '.join(duplicates)}.")
    too_long = [page["name"].strip() or "(unnamed)" for page in pages if len(page["snapshot"]) > MAX_SNAPSHOT_CHARS]
    if too_long:
        problems.append(f"Snapshots must be at most {MAX_SNAPSHOT_CHARS:,} characters: {', '.join(too_long)}.")
    return problems


def signature(*parts) -> str:
    """Fingerprint of the inputs a stored result belongs to."""
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
