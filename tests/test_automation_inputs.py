"""Unit tests for core/automation_inputs.py."""
from core.automation_inputs import MAX_CASES, MAX_DESCRIPTION_CHARS, api_cases, input_problems, signature, web_cases

CASE = {"test_id": "TC_1", "platform": "Web"}
PAGE = {"name": "Login", "path": "/login", "snapshot": ""}


def test_web_cases_keeps_web_all_and_blank_platforms():
    cases = [
        {"test_id": "1", "platform": "Web"}, {"test_id": "2", "platform": "all"},
        {"test_id": "3", "platform": ""}, {"test_id": "4", "platform": "iOS"},
        {"test_id": "5", "platform": "Android"}, {"test_id": "6"},
    ]

    assert [c["test_id"] for c in web_cases(cases)] == ["1", "2", "3", "6"]


def test_valid_input_has_no_problems():
    assert input_problems([CASE], "https://staging.example.com", [PAGE]) == []
    assert input_problems([CASE], " http://localhost:3000 ", []) == []


def test_nothing_selected():
    assert input_problems([], "https://x.test", []) == ["Select at least one test case."]


def test_too_many_cases():
    problems = input_problems([CASE] * (MAX_CASES + 1), "https://x.test", [])

    assert problems == ["Select at most 10 test cases per generation (11 selected)."]


def test_bad_base_url():
    for url in ["", "staging.example.com", "ftp://x.test", "https://", "https://x .test"]:
        assert input_problems([CASE], url, []) == ["Enter a Base URL that starts with http:// or https://."]


def test_too_many_pages():
    pages = [{"name": f"P{i}", "path": "/", "snapshot": ""} for i in range(11)]

    assert input_problems([CASE], "https://x.test", pages) == ["Describe at most 10 pages (11 given)."]


def test_page_needs_name_and_path():
    problems = input_problems([CASE], "https://x.test", [{"name": "", "path": "/", "snapshot": ""}])

    assert problems == ["Every page needs a name and a path."]


def test_duplicate_page_names_ignore_case():
    pages = [PAGE, {**PAGE, "name": "login"}]

    assert input_problems([CASE], "https://x.test", pages) == ["Page names must be unique: login."]


def test_snapshot_too_long():
    pages = [{**PAGE, "snapshot": "x" * 50_001}]

    assert input_problems([CASE], "https://x.test", pages) == [
        "Snapshots must be at most 50,000 characters: Login."
    ]


def test_signature_changes_with_any_part():
    assert signature("session", "", ["TC_1"]) == signature("session", "", ["TC_1"])
    assert signature("session", "", ["TC_1"]) != signature("session", "", ["TC_2"])
    assert signature("upload", "a", ["TC_1"]) != signature("upload", "b", ["TC_1"])


API_CASE = {"test_id": "TC_A1", "platform": "API"}


def test_api_cases_ignores_case_and_spaces():
    cases = [
        {"test_id": "1", "platform": "API"}, {"test_id": "2", "platform": " api "}, {"test_id": "3", "platform": "Web"},
        {"test_id": "4", "platform": "All"}, {"test_id": "5"}, {"test_id": "6", "platform": None},
    ]

    assert [c["test_id"] for c in api_cases(cases)] == ["1", "2"]
    assert [c["test_id"] for c in web_cases(cases)] == ["3", "4", "5", "6"]


def test_api_only_selection_needs_an_api_base_url_and_no_web_base_url():
    assert input_problems([], "", [], [API_CASE], "https://api.example.com", "") == []
    assert input_problems([], "", [], [API_CASE], "api.example.com", "") == [
        "Enter an API base URL that starts with http:// or https://."
    ]


def test_mixed_selection_checks_both_kinds():
    problems = input_problems([CASE], "", [], [API_CASE] * (MAX_CASES + 1), "", "x" * (MAX_DESCRIPTION_CHARS + 1))

    assert problems == [
        "Select at most 10 API test cases per generation (11 selected).",
        "Enter a Base URL that starts with http:// or https://.",
        "Enter an API base URL that starts with http:// or https://.",
        "The API description must be at most 50,000 characters.",
    ]


def test_nothing_selected_of_either_kind():
    assert input_problems([], "", [], [], "", "") == [
        "Select at least one test case.",
        "Enter a Base URL that starts with http:// or https://.",
    ]
