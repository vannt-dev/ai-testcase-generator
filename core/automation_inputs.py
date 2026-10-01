"""Input checks for the Automation page, kept out of Streamlit so they can be unit tested."""
import hashlib
import json
import re

MAX_CASES = 10
MAX_PAGES = 10
MAX_SNAPSHOT_CHARS = 50_000
MAX_DESCRIPTION_CHARS = 50_000
WEB_PLATFORMS = {"web", "all", ""}
BASE_URL = re.compile(r"^https?://[^\s/]+\S*$")


def web_cases(cases: list[dict]) -> list[dict]:
    """Test cases a browser can run; uploads without a platform column count as web."""
    return [case for case in cases if str(case.get("platform") or "").strip().lower() in WEB_PLATFORMS]


def api_cases(cases: list[dict]) -> list[dict]:
    """Test cases that call an API; an upload must say so in its platform column."""
    return [case for case in cases if str(case.get("platform") or "").strip().lower() == "api"]


def input_problems(
    selected: list[dict], base_url: str, pages: list[dict],
    api_selected: list[dict] | None = None, api_base_url: str = "", api_description: str = "",
) -> list[str]:
    """`selected` are the web cases, `api_selected` the API cases; each kind has its own limit and inputs."""
    api_selected = api_selected or []
    problems = []
    if not selected and not api_selected:
        problems.append("Select at least one test case.")
    if len(selected) > MAX_CASES:
        problems.append(f"Select at most {MAX_CASES} test cases per generation ({len(selected)} selected).")
    if len(api_selected) > MAX_CASES:
        problems.append(f"Select at most {MAX_CASES} API test cases per generation ({len(api_selected)} selected).")
    # The web Base URL only matters to web tests; with nothing selected it is still asked for, as before.
    if (selected or not api_selected) and not BASE_URL.match(base_url.strip()):
        problems.append("Enter a Base URL that starts with http:// or https://.")
    if api_selected and not BASE_URL.match(api_base_url.strip()):
        problems.append("Enter an API base URL that starts with http:// or https://.")
    if len(api_description) > MAX_DESCRIPTION_CHARS:
        problems.append(f"The API description must be at most {MAX_DESCRIPTION_CHARS:,} characters.")
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
