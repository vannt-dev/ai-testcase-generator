"""Unit tests for core/api_automation_validate.py."""
import json

from core.api_automation_validate import validate_api_automation


def _step(**overrides):
    step = {
        "action": "request", "method": "GET", "path": "/orders", "headers": [], "query": [], "body": "",
        "expect_status": 200, "checks": [], "saves": [], "confident": True, "source": "1. GET /orders",
    }
    step.update(overrides)
    return step


def _validate(steps, test_id="TC_1", modules=None):
    result, warnings = validate_api_automation(
        {"tests": [{"test_id": test_id, "title": "T", "steps": steps}], "open_questions": [" Which token? ", " "]},
        modules if modules is not None else {test_id: "Orders"},
    )
    return result, warnings


def _steps(steps):
    result, warnings = _validate(steps)
    return result["tests"][0]["steps"], warnings


def test_a_valid_request_passes_through_with_its_module():
    result, warnings = _validate([_step(method="post", body='{"sku": "A-1"}', expect_status=201)])

    test = result["tests"][0]
    assert warnings == []
    assert test["module"] == "Orders"
    assert test["steps"][0]["method"] == "POST"
    assert json.loads(test["steps"][0]["body"]) == {"sku": "A-1"}
    assert result["open_questions"] == [" Which token? "]


def test_unknown_action_method_and_bad_path_become_todo():
    steps, warnings = _steps([
        _step(action="click"), _step(method="TRACE"), _step(path="orders"), _step(path="/or ders"),
        _step(action="todo", source="Check the email"),
    ])

    assert [s["action"] for s in steps] == ["todo"] * 5
    assert steps[4]["source"] == "Check the email"
    assert any("unknown action 'click'" in w for w in warnings)
    assert any("unknown method 'TRACE'" in w for w in warnings)
    assert sum("must start with '/'" in w for w in warnings) == 2


def test_invalid_json_body_becomes_todo_and_get_body_is_dropped():
    steps, warnings = _steps([_step(method="POST", body="{sku: A-1}"), _step(method="GET", body='{"a": 1}')])

    assert steps[0]["action"] == "todo"
    assert steps[1]["action"] == "request" and steps[1]["body"] == ""
    assert any("body is not valid JSON" in w for w in warnings)
    assert any("GET request cannot send a body" in w for w in warnings)


def test_a_bare_placeholder_in_a_body_is_quoted():
    steps, warnings = _steps([
        _step(saves=[{"var": "orderId", "path": "id"}]),
        _step(method="POST", path="/payments", body='{"orderId": ${VAR:orderId}, "note": "x"}'),
    ])

    assert warnings == []
    assert json.loads(steps[1]["body"]) == {"orderId": "${VAR:orderId}", "note": "x"}


def test_status_outside_the_http_range_is_cleared():
    steps, warnings = _steps([_step(expect_status=999), _step(expect_status="abc")])

    assert [s["expect_status"] for s in steps] == [0, 0]
    assert any("status 999" in w for w in warnings)


def test_duplicate_header_and_query_names_keep_the_first():
    steps, warnings = _steps([_step(
        headers=[{"name": "Accept", "value": "a"}, {"name": "accept", "value": "b"}, {"name": " ", "value": "c"}],
        query=[{"name": "page", "value": "1"}, {"name": "page", "value": "2"}, {"name": "Page", "value": "3"}],
    )])

    assert steps[0]["headers"] == [{"name": "Accept", "value": "a"}]
    assert steps[0]["query"] == [{"name": "page", "value": "1"}, {"name": "Page", "value": "3"}]
    assert any("duplicate header 'accept'" in w for w in warnings)
    assert any("duplicate query parameter 'page'" in w for w in warnings)
    assert any("header without a name" in w for w in warnings)


def test_checks_with_bad_kind_or_path_are_dropped():
    steps, warnings = _steps([_step(checks=[
        {"kind": "json_exists", "path": "data.items[0].id", "value": "ignored"},
        {"kind": "json_exists", "path": "data..id", "value": ""},
        {"kind": "regex", "path": "id", "value": ""},
        {"kind": "text_contains", "path": "ignored", "value": "ok"},
        {"kind": "json_equals", "path": "", "value": "[]"},
    ])])

    assert steps[0]["checks"] == [
        {"kind": "json_exists", "path": "data.items[0].id", "value": ""},
        {"kind": "text_contains", "path": "", "value": "ok"},
        {"kind": "json_equals", "path": "", "value": "[]"},
    ]
    assert any("invalid JSON path 'data..id'" in w for w in warnings)
    assert any("unknown check 'regex'" in w for w in warnings)


def test_json_equals_value_that_is_not_json_is_compared_as_text():
    steps, warnings = _steps([
        _step(saves=[{"var": "orderId", "path": "id"}]),
        _step(checks=[
            {"kind": "json_equals", "path": "status", "value": "paid"},
            {"kind": "json_equals", "path": "id", "value": "${VAR:orderId}"},
            {"kind": "json_equals", "path": "total", "value": "12.5"},
        ]),
    ])

    assert [c["value"] for c in steps[1]["checks"]] == ['"paid"', '"${VAR:orderId}"', "12.5"]
    assert sum("is not JSON" in w for w in warnings) == 1


def test_saved_variables_are_cleaned_made_unique_and_references_rewritten():
    steps, warnings = _steps([
        _step(saves=[
            {"var": "order id", "path": "id"}, {"var": "Order-Id", "path": "ref"},
            {"var": "request", "path": "x"}, {"var": "response1", "path": "y"}, {"var": "bad", "path": "a..b"},
        ]),
        _step(path="/orders/${VAR:order id}", headers=[{"name": "X-Ref", "value": "r-${VAR:Order-Id}"}]),
    ])

    assert [s["var"] for s in steps[0]["saves"]] == ["orderId", "orderId2", "requestValue", "response1Value"]
    assert steps[1]["path"] == "/orders/${VAR:orderId}"
    assert steps[1]["headers"][0]["value"] == "r-${VAR:orderId2}"
    assert any("invalid JSON path 'a..b'" in w for w in warnings)


def test_an_unknown_variable_becomes_todo():
    steps, warnings = _steps([_step(path="/orders/${VAR:orderId}")])

    assert steps[0]["action"] == "todo"
    assert any("TC_1 step 1: unknown variable 'orderId'" in w for w in warnings)


def test_a_variable_from_a_downgraded_step_downgrades_its_users():
    steps, warnings = _steps([
        _step(method="TRACE", saves=[{"var": "orderId", "path": "id"}]),
        _step(path="/orders/${VAR:orderId}"),
    ])

    assert [s["action"] for s in steps] == ["todo", "todo"]
    assert any("step 2: unknown variable 'orderId'" in w for w in warnings)


def test_a_variable_is_not_visible_in_another_test():
    result, warnings = validate_api_automation({"tests": [
        {"test_id": "TC_1", "title": "a", "steps": [_step(saves=[{"var": "orderId", "path": "id"}])]},
        {"test_id": "TC_2", "title": "b", "steps": [_step(path="/orders/${VAR:orderId}")]},
    ], "open_questions": []}, {"TC_1": "A", "TC_2": "A"})

    assert result["tests"][1]["steps"][0]["action"] == "todo"


def test_invalid_env_names_stay_literal_and_valid_ones_are_kept():
    steps, warnings = _steps([_step(headers=[
        {"name": "Authorization", "value": "Bearer ${ENV:API_TOKEN}"}, {"name": "X-Bad", "value": "${ENV:bad name}"},
    ])])

    assert [h["value"] for h in steps[0]["headers"]] == ["Bearer ${ENV:API_TOKEN}", "${ENV:bad name}"]
    assert warnings == []


def test_a_request_that_asserts_nothing_gets_a_warning():
    steps, warnings = _steps([_step(expect_status=0)])

    assert steps[0]["action"] == "request"
    assert any("asserts nothing" in w for w in warnings)


def test_duplicate_ids_empty_tests_and_unexpected_ids():
    result, warnings = validate_api_automation({"tests": [
        {"test_id": "TC_1", "title": "a", "steps": [_step()]},
        {"test_id": "TC_1", "title": "b", "steps": []},
        {"test_id": "TC_9", "title": "c", "steps": [_step()]},
    ], "open_questions": None}, {"TC_1": "Orders", "TC_2": "Orders"})

    assert [t["test_id"] for t in result["tests"]] == ["TC_1", "TC_1_2", "TC_9"]
    assert result["tests"][1]["steps"][0]["action"] == "todo"
    assert result["tests"][2]["module"] == ""
    assert any("Duplicate test id 'TC_1' renamed to 'TC_1_2'" in w for w in warnings)
    assert any("TC_9 was not among the selected test cases" in w for w in warnings)
    assert any("TC_2 was selected but the AI returned no test for it" in w for w in warnings)


def test_malformed_output_never_raises():
    result, warnings = validate_api_automation(
        {"tests": [{"steps": [{"headers": None, "checks": [{}], "saves": [{}]}]}]}, {},
    )

    assert result["tests"][0]["steps"][0]["action"] == "todo"
    assert validate_api_automation({}, {}) == ({"tests": [], "open_questions": []}, [])


def test_json_escaped_placeholders_are_validated_like_plain_ones():
    steps, warnings = _steps([_step(method="POST", body='{"a": "$\\u007bVAR:sneaky}"}')])
    assert steps[0]["action"] == "todo"
    assert any("unknown variable 'sneaky'" in w for w in warnings)

    steps, warnings = _steps([_step(checks=[{"kind": "json_equals", "path": "id", "value": '"$\\u007bVAR:sneaky}"'}])])
    assert steps[0]["action"] == "todo"

    steps, warnings = _steps([_step(method="POST", body='{"k": "$\\u007bENV:HIDDEN}"}')])
    assert "${ENV:HIDDEN}" in steps[0]["body"]


def test_variables_named_like_step_locals_or_special_identifiers_are_renamed():
    steps, _ = _steps([_step(saves=[
        {"var": "response", "path": "a"}, {"var": "response", "path": "b"}, {"var": "body", "path": "c"},
        {"var": "arguments", "path": "d"}, {"var": "eval", "path": "e"},
    ])])

    assert [s["var"] for s in steps[0]["saves"]] == [
        "responseValue", "responseValue2", "bodyValue", "argumentsValue", "evalValue",
    ]


def test_deep_nesting_and_invalid_unicode_never_raise():
    deep = "[" * 100_000 + "]" * 100_000
    nested = "[" * 60 + "]" * 60
    steps, warnings = _steps([
        _step(method="POST", body=deep),
        _step(method="POST", body=nested),
        _step(checks=[{"kind": "json_equals", "path": "a", "value": deep}]),
        _step(method="POST", body='{"a": "\\ud800"}', source="bad \ud800 text", path="/x\ud800"),
    ])

    assert [s["action"] for s in steps] == ["todo", "todo", "request", "request"]
    assert steps[2]["checks"] == []
    assert sum("nested too deeply" in w for w in warnings) == 3
    for text in (steps[3]["body"], steps[3]["source"], steps[3]["path"]):
        text.encode("utf-8")


def test_a_path_parameter_left_in_braces_becomes_todo():
    steps, warnings = _steps([
        _step(path="/orders/{id}"),
        _step(saves=[{"var": "orderId", "path": "id"}]),
        _step(path="/orders/${VAR:orderId}"),
    ])

    assert [s["action"] for s in steps] == ["todo", "request", "request"]
    assert any("still holds the parameter '{id}'" in w for w in warnings)
