from core.bug_batch import (
    MAX_BATCH_ROWS,
    apply_summary_edits,
    combined_markdown,
    default_failed_values,
    distinct_values,
    failed_rows,
    notes_for_row,
    write_reports,
)

MAPPING = {"status": "Status", "actual_result": "Actual", "comment": "Note", "test_id": "ID", "title": "Title"}

ROWS = [
    {"ID": "TC_1", "Title": "Pay", "Status": "Failed", "Actual": "Freezes", "Note": "on Android"},
    {"ID": "TC_2", "Title": "Login", "Status": "Passed", "Actual": "OK", "Note": None},
    {"ID": "TC_3", "Title": "Cart", "Status": " FAILED ", "Actual": "Empty cart", "Note": ""},
    {"ID": None, "Title": "Search", "Status": "Không đạt", "Actual": "No results", "Note": None},
]


def _report(title="Bug", **extra):
    report = {
        "title": title, "module": "M", "severity": "Major", "priority": "High",
        "reproducibility": "Always", "build_version": "", "environment": "", "preconditions": "",
        "steps_to_reproduce": ["Do it"], "expected_result": "E", "actual_result": "A",
        "test_data": "", "related_test_id": "", "open_questions": [],
    }
    report.update(extra)
    return report


class FakeClient:
    def __init__(self, fail_on=(), costs=None):
        self.fail_on = set(fail_on)
        self.costs = costs or {}
        self.calls = []

    def write_bug_report(self, system_prompt, notes, related_test_case=None):
        self.calls.append((system_prompt, notes, related_test_case))
        number = len(self.calls)
        if number in self.fail_on:
            raise ValueError(f"boom {number}")
        return {
            "report": _report(title=f"Bug {number}"),
            "usage": {"model": "claude-sonnet-5", "input_tokens": 10, "output_tokens": 5,
                      "cache_creation_input_tokens": 1, "cache_read_input_tokens": 2,
                      "estimated_cost_usd": self.costs.get(number, 0.001)},
        }


def test_distinct_values_are_non_blank_and_first_seen():
    assert distinct_values(ROWS, "Status") == ["Failed", "Passed", "FAILED", "Không đạt"]
    assert distinct_values(ROWS, "") == []


def test_default_failed_values_normalizes_case_spaces_and_diacritics():
    values = ["Passed", "Failed", "KO ĐẠT", "Không đạt", "ko dat", "Blocked", "x", "NG", "", "FAILED"]

    assert default_failed_values(values) == ["Failed", "KO ĐẠT", "Không đạt", "ko dat", "NG", "FAILED"]


def test_failed_rows_matches_stripped_status():
    rows = failed_rows(ROWS, MAPPING, ["Failed", "FAILED", "Không đạt"])

    assert [row["row_number"] for row in rows] == [1, 3, 4]
    assert rows[0] == {
        "row_number": 1,
        "test_case": {"test_id": "TC_1", "title": "Pay"},
        "actual_result": "Freezes",
        "comment": "on Android",
    }
    assert rows[2]["test_case"] == {"title": "Search"}
    assert rows[2]["comment"] == ""


def test_notes_for_row_adds_the_comment_only_when_present():
    assert notes_for_row({"actual_result": "Freezes", "comment": ""}) == (
        "Test case failed during a test run.\n\nActual result: Freezes"
    )
    assert notes_for_row({"actual_result": "Freezes", "comment": "on Android"}).endswith(
        "\n\nTester comment: on Android"
    )


def test_write_reports_continues_after_a_failing_row():
    rows = failed_rows(ROWS, MAPPING, ["Failed", "FAILED", "Không đạt"])
    client = FakeClient(fail_on={2})
    progress = []

    result = write_reports(client, "system", rows, source_name="run.xlsx",
                           on_progress=lambda done, total: progress.append((done, total)))

    assert [r["title"] for r in result["reports"]] == ["Bug 1", "Bug 3"]
    assert [r["source"] for r in result["reports"]] == ["run.xlsx, row 1", "run.xlsx, row 4"]
    assert result["errors"] == [{"row": 3, "test_id": "TC_3", "error": "boom 2"}]
    assert progress == [(1, 3), (2, 3), (3, 3)]
    assert client.calls[0][2] == {"test_id": "TC_1", "title": "Pay"}
    assert client.calls[0][1].startswith("Test case failed during a test run.")


def test_write_reports_sums_usage_and_drops_cost_when_one_is_unknown():
    rows = failed_rows(ROWS, MAPPING, ["Failed", "Không đạt"])

    known = write_reports(FakeClient(), "system", rows)["usage"]
    assert known["input_tokens"] == 20
    assert known["cache_read_input_tokens"] == 4
    assert round(known["estimated_cost_usd"], 6) == 0.002
    assert known["model"] == "claude-sonnet-5"
    assert write_reports(FakeClient(), "system", rows)["reports"][0]["source"] == "row 1"

    unknown = write_reports(FakeClient(costs={2: None}), "system", rows)["usage"]
    assert unknown["estimated_cost_usd"] is None


def test_write_reports_sends_none_when_the_row_has_no_test_case_fields():
    rows = failed_rows(
        [{"Status": "Failed", "Actual": "x"}], {"status": "Status", "actual_result": "Actual"}, ["Failed"]
    )
    client = FakeClient()

    write_reports(client, "system", rows)

    assert client.calls[0][2] is None


def test_apply_summary_edits_keeps_originals_for_blank_or_invalid_values():
    reports = [_report(title="A"), _report(title="B")]
    edits = [
        {"title": "A edited", "severity": "Minor", "priority": "Low"},
        {"title": "  ", "severity": "Blocker", "priority": None},
    ]

    updated = apply_summary_edits(reports, edits)

    assert (updated[0]["title"], updated[0]["severity"], updated[0]["priority"]) == ("A edited", "Minor", "Low")
    assert (updated[1]["title"], updated[1]["severity"], updated[1]["priority"]) == ("B", "Major", "High")
    assert reports[0]["title"] == "A"


def test_combined_markdown_separates_reports():
    md = combined_markdown([_report(title="One"), _report(title="Two")])

    assert md.startswith("# One\n")
    assert "\n---\n\n# Two\n" in md


def test_max_batch_rows_is_fifty():
    assert MAX_BATCH_ROWS == 50
