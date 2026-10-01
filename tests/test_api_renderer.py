"""Unit tests for core/api_renderer.py."""
from core.api_renderer import api_env_names, render_api_files, summarize_api, text_expr


def _step(**overrides):
    step = {
        "action": "request", "method": "GET", "path": "/orders", "headers": [], "query": [], "body": "",
        "expect_status": 200, "checks": [], "saves": [], "confident": True, "source": "1. GET /orders",
    }
    step.update(overrides)
    return step


def _todo(source="Check the email"):
    return _step(action="todo", method="", path="", expect_status=0, confident=False, source=source)


def _result(steps, module="Orders", test_id="TC_1", title="List orders"):
    return {"tests": [{"test_id": test_id, "title": title, "module": module, "steps": steps}], "open_questions": []}


def _spec(steps, **kwargs):
    files = render_api_files(_result(steps, **kwargs), "https://api.example.com")
    return files["tests/api/orders.api.spec.ts"]


def test_a_plain_get_renders_a_request_and_a_status_assertion():
    assert _spec([_step()]) == (
        "import { test, expect } from '@playwright/test';\n"
        "import { apiUrl, at, jsonBody } from './support';\n"
        "\n"
        'test("TC_1 List orders", async ({ request }) => {\n'
        "  // 1. GET /orders\n"
        '  const response1 = await request.get(apiUrl("/orders"));\n'
        "  expect(response1.status()).toBe(200);\n"
        "});\n"
    )


def test_a_post_with_headers_query_body_checks_and_saves():
    spec = _spec([_step(
        method="POST", expect_status=201, source="1. POST /orders",
        headers=[{"name": "Authorization", "value": "Bearer ${ENV:API_TOKEN}"}],
        query=[{"name": "dryRun", "value": "false"}],
        body='{"sku": "A-1", "quantity": 2, "tags": ["a", "b"], "gift": false, "note": null, "meta": {}}',
        checks=[
            {"kind": "json_exists", "path": "id", "value": ""},
            {"kind": "json_absent", "path": "error", "value": ""},
            {"kind": "json_equals", "path": "status", "value": '"pending"'},
            {"kind": "json_equals", "path": "lines", "value": '[{"sku": "A-1"}]'},
            {"kind": "json_contains", "path": "message", "value": "created"},
            {"kind": "text_contains", "path": "", "value": "A-1"},
        ],
        saves=[{"var": "orderId", "path": "id"}],
    )])

    assert (
        '  const response1 = await request.post(apiUrl("/orders"), {\n'
        "    headers: { \"Authorization\": \"Bearer \" + (process.env.API_TOKEN ?? '') },\n"
        '    params: { "dryRun": "false" },\n'
        '    data: { "sku": "A-1", "quantity": 2, "tags": ["a", "b"], "gift": false, "note": null, "meta": {} },\n'
        "  });\n"
        "  expect(response1.status()).toBe(201);\n"
        "  const body1 = await jsonBody(response1);\n"
        '  expect(at(body1, "id")).toBeDefined();\n'
        '  expect(at(body1, "error")).toBeUndefined();\n'
        '  expect(at(body1, "status")).toEqual("pending");\n'
        '  expect(at(body1, "lines")).toEqual([{ "sku": "A-1" }]);\n'
        '  expect(String(at(body1, "message"))).toContain("created");\n'
        '  expect(await response1.text()).toContain("A-1");\n'
        '  const orderId = at(body1, "id");\n'
        '  expect(orderId, "id is missing from the response").toBeDefined();\n'
    ) in spec


def test_repeated_query_parameters_are_all_sent():
    spec = _spec([_step(query=[{"name": "tag", "value": "a"}, {"name": "tag", "value": "b"}, {"name": "q", "value": "x"}])])

    assert '    params: new URLSearchParams([["tag", "a"], ["tag", "b"], ["q", "x"]]),\n' in spec


def test_a_string_body_is_sent_as_json():
    spec = _spec([
        _step(method="POST", body='"plain text"'),
        _step(method="POST", body='"again"', headers=[{"name": "content-type", "value": "application/json"}]),
    ])

    assert '    headers: { "Content-Type": "application/json" },\n    data: JSON.stringify("plain text"),\n' in spec
    assert '    headers: { "content-type": "application/json" },\n    data: JSON.stringify("again"),\n' in spec
    assert spec.count("Content-Type") == 1


def test_saved_variables_keep_their_type_alone_and_are_text_inside_strings():
    spec = _spec([
        _step(saves=[{"var": "orderId", "path": "id"}]),
        _step(
            method="PUT", path="/orders/${VAR:orderId}/lines", source="",
            body='{"orderId": "${VAR:orderId}", "ref": "order-${VAR:orderId}", "key": "${ENV:API_KEY}"}',
            checks=[{"kind": "json_equals", "path": "id", "value": '"${VAR:orderId}"'}],
        ),
    ])

    assert 'request.put(apiUrl("/orders/" + String(orderId) + "/lines"), {' in spec
    assert (
        '    data: { "orderId": orderId, "ref": "order-" + String(orderId), "key": process.env.API_KEY ?? \'\' },\n'
    ) in spec
    assert '  expect(at(body2, "id")).toEqual(orderId);\n' in spec
    assert "  const body1 = await jsonBody(response1);\n" in spec


def test_placeholders_are_joined_to_escaped_literals():
    hostile = 'a"b`c${d}*/e\nf${ENV:TOKEN}"; process.exit(1); //'

    assert text_expr(hostile) == (
        '"a\\"b`c${d}*/e\\nf" + (process.env.TOKEN ?? \'\') + "\\"; process.exit(1); //"'
    )
    assert text_expr("") == '""'
    assert text_expr("${ENV:bad name}") == '"${ENV:bad name}"'
    spec = _spec([_step(headers=[{"name": 'X-"A', "value": hostile}], source="line one\nline */ two")])
    assert "  // line one line * / two\n" in spec
    assert '"X-\\"A": "a\\"b`c${d}*/e\\nf" + (process.env.TOKEN ?? \'\')' in spec


def test_head_and_options_use_fetch_and_delete_uses_its_method():
    spec = _spec([_step(method="HEAD"), _step(method="OPTIONS", headers=[{"name": "Origin", "value": "x"}]),
                  _step(method="DELETE", path="/orders/1", expect_status=204)])

    assert (
        '  const response1 = await request.fetch(apiUrl("/orders"), {\n'
        '    method: "HEAD",\n'
        "  });\n"
    ) in spec
    assert '    method: "OPTIONS",\n    headers: { "Origin": "x" },\n' in spec
    assert '  const response3 = await request.delete(apiUrl("/orders/1"));\n' in spec


def test_todo_steps_make_the_test_fixme_and_unconfident_requests_are_marked():
    spec = _spec([_step(confident=False, expect_status=0), _todo("Check the */ email\nnow")])

    assert spec.count("test.fixme(") == 1
    assert "  // TODO verify this request: the endpoint was not in the API description\n" in spec
    assert "  // TODO: Check the * / email now\n" in spec
    assert "expect(response1.status())" not in spec
    assert "body1" not in spec


def test_tests_are_grouped_by_module_slug_and_windows_names_are_avoided():
    result = {"tests": [
        {"test_id": "TC_1", "title": "a", "module": "Đơn hàng", "steps": [_step()]},
        {"test_id": "TC_2", "title": "b", "module": "CON", "steps": [_step()]},
        {"test_id": "TC_3", "title": "c", "module": "", "steps": [_step()]},
        {"test_id": "TC_4", "title": "d", "module": "don hang", "steps": [_step()]},
    ], "open_questions": []}

    files = render_api_files(result, "https://api.example.com")

    assert sorted(files) == [
        "tests/api/con-tests.api.spec.ts", "tests/api/don-hang.api.spec.ts",
        "tests/api/general.api.spec.ts", "tests/api/support.ts",
    ]
    assert files["tests/api/don-hang.api.spec.ts"].count("test(") == 2


def test_support_file_holds_the_base_url_as_an_escaped_literal():
    support = render_api_files(_result([_step()]), 'https://api.example.com/v1"; hack()//')["tests/api/support.ts"]

    assert 'process.env.API_BASE_URL ?? "https://api.example.com/v1\\"; hack()//"' in support
    assert "export function apiUrl(path: string): string {" in support
    assert "export function at(body: unknown, path: string): any {" in support
    assert ".replace(/\\/+$/, '')" in support
    assert "path.match(/[^.[\\]]+/g)" in support
    # A 204 or HEAD response has no body; response.json() would throw on it.
    assert "export async function jsonBody(response: APIResponse): Promise<any> {" in support
    assert "return text ? JSON.parse(text) : undefined;" in support


def test_a_proto_key_is_sent_as_a_property_not_as_the_prototype():
    spec = _spec([_step(
        method="POST", body='{"__proto__": {"admin": true}, "constructor": 1}',
        checks=[{"kind": "json_equals", "path": "", "value": '{"__proto__": 1}'}],
    )])

    assert '    data: { ["__proto__"]: { "admin": true }, "constructor": 1 },\n' in spec
    assert '.toEqual({ ["__proto__"]: 1 });\n' in spec


def test_a_variable_no_step_declared_is_rendered_as_text_never_as_an_identifier():
    spec = _spec([
        _step(saves=[{"var": "orderId", "path": "id"}]),
        _step(method="POST", path="/x/${VAR:ghost}", body='{"a": "${VAR:ghost}", "b": "${VAR:orderId}"}',
              checks=[{"kind": "json_equals", "path": "a", "value": '"${VAR:later}"'}],
              saves=[{"var": "later", "path": "id"}]),
    ])

    assert 'apiUrl("/x/${VAR:ghost}")' in spec
    assert '    data: { "a": "${VAR:ghost}", "b": orderId },\n' in spec
    assert '.toEqual("${VAR:later}");\n' in spec


def test_env_names_and_summary():
    result = {"tests": [
        {"test_id": "TC_1", "title": "a", "module": "m", "steps": [
            _step(
                headers=[{"name": "A", "value": "Bearer ${ENV:API_TOKEN}"}],
                query=[{"name": "k", "value": "${ENV:API_KEY}"}],
                body='{"p": "${ENV:PASSWORD}"}', path="/t/${ENV:TENANT}",
                checks=[{"kind": "json_contains", "path": "x", "value": "${ENV:EXPECTED}"}],
            ),
            _step(confident=False),
        ]},
        {"test_id": "TC_2", "title": "b", "module": "m", "steps": [_todo(), _step(confident=False)]},
    ], "open_questions": []}

    assert api_env_names(result) == ["API_KEY", "API_TOKEN", "EXPECTED", "PASSWORD", "TENANT"]
    assert summarize_api(result) == {"tests": 2, "fixme": 1, "unverified_requests": 2}
    assert render_api_files(result, "https://x.test") == render_api_files(result, "https://x.test")
