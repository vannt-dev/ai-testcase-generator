"""Unit tests for core/automation_validate.py."""
from core.automation_validate import to_camel, to_pascal, validate_automation


def _locator(key, strategy="label", role="", value="Email", confident=True):
    return {"key": key, "strategy": strategy, "role": role, "value": value, "confident": confident}


def _step(action, page="", locator="", value="", source="a step"):
    return {"action": action, "page": page, "locator": locator, "value": value, "source": source}


def _result(pages, tests, questions=None):
    return {"pages": pages, "tests": tests, "open_questions": questions or []}


LOGIN = {"name": "LoginPage", "path": "/login", "locators": [_locator("emailInput")]}


def test_valid_result_passes_through_without_warnings():
    raw = _result([LOGIN], [{"test_id": "TC_1", "title": "Login", "steps": [
        _step("goto", page="LoginPage"),
        _step("fill", page="LoginPage", locator="emailInput", value="a@b.c"),
    ]}], ["Which account?"])

    cleaned, warnings = validate_automation(raw, {"TC_1": "Login"})

    assert warnings == []
    assert cleaned["pages"][0]["name"] == "LoginPage"
    assert cleaned["pages"][0]["var"] == "loginPage"
    assert cleaned["tests"][0]["module"] == "Login"
    assert cleaned["tests"][0]["steps"][1] == {
        "action": "fill", "page": "LoginPage", "locator": "emailInput", "value": "a@b.c", "source": "a step",
    }
    assert cleaned["open_questions"] == ["Which account?"]


def test_vietnamese_names_are_transliterated():
    assert to_pascal("Trang chủ") == "TrangChu"
    assert to_pascal("Đăng nhập") == "DangNhap"
    assert to_camel("Nút đăng nhập") == "nutDangNhap"


def test_names_with_nothing_usable_get_defaults():
    assert to_pascal("!!!") == "UnnamedPage"
    assert to_camel("") == "element"
    assert to_pascal("2fa screen") == "Page2faScreen"
    assert to_camel("1st button") == "el1stButton"


def test_reserved_names_get_a_suffix():
    assert to_pascal("page") == "PageObject"
    assert to_pascal("Locator") == "LocatorObject"
    assert to_camel("delete") == "deleteLocator"
    assert to_camel("path") == "pathLocator"
    assert to_camel("goto") == "gotoLocator"


def test_steps_may_reference_the_raw_or_the_cleaned_page_name():
    page = {"name": "Trang chủ", "path": "/", "locators": [_locator("menu")]}
    raw = _result([page], [{"test_id": "TC_1", "title": "t", "steps": [
        _step("click", page="Trang chủ", locator="menu"),
        _step("click", page="TrangChu", locator="menu"),
    ]}])

    cleaned, warnings = validate_automation(raw, {})

    assert warnings == []
    assert [s["page"] for s in cleaned["tests"][0]["steps"]] == ["TrangChu", "TrangChu"]


def test_duplicate_page_keeps_the_first_definition():
    second = {"name": "LoginPage", "path": "/other", "locators": []}
    cleaned, warnings = validate_automation(_result([LOGIN, second], []), {})

    assert len(cleaned["pages"]) == 1
    assert cleaned["pages"][0]["path"] == "/login"
    assert any("Duplicate page 'LoginPage'" in w for w in warnings)


def test_page_names_that_clash_after_cleaning_get_numbers():
    pages = [
        {"name": "Login page", "path": "/a", "locators": []},
        {"name": "login-page", "path": "/b", "locators": []},
    ]
    cleaned, _ = validate_automation(_result(pages, []), {})

    assert [p["name"] for p in cleaned["pages"]] == ["LoginPage", "LoginPage2"]
    assert [p["var"] for p in cleaned["pages"]] == ["loginPage", "loginPage2"]


def test_page_names_differing_only_in_case_get_numbers():
    pages = [
        {"name": "LoginPage", "path": "/a", "locators": []},
        {"name": "Loginpage", "path": "/b", "locators": []},
    ]
    cleaned, _ = validate_automation(_result(pages, []), {})

    assert [p["name"] for p in cleaned["pages"]] == ["LoginPage", "Loginpage2"]


def test_duplicate_locator_keeps_the_first_definition():
    page = {"name": "LoginPage", "path": "/", "locators": [
        _locator("emailInput", value="Email"), _locator("emailInput", value="Other"),
    ]}
    cleaned, warnings = validate_automation(_result([page], []), {})

    assert [loc["value"] for loc in cleaned["pages"][0]["locators"]] == ["Email"]
    assert any("duplicate locator 'emailInput'" in w for w in warnings)


def test_empty_role_falls_back_to_text_without_warning():
    page = {"name": "P", "path": "/", "locators": [_locator("ok", strategy="role", role="", value="OK")]}
    cleaned, warnings = validate_automation(_result([page], []), {})

    loc = cleaned["pages"][0]["locators"][0]
    assert (loc["strategy"], loc["role"], loc["confident"]) == ("text", "", False)
    assert warnings == []


def test_unknown_role_falls_back_to_text():
    page = {"name": "P", "path": "/", "locators": [_locator("ok", strategy="role", role="btn", value="OK")]}
    cleaned, warnings = validate_automation(_result([page], []), {})

    loc = cleaned["pages"][0]["locators"][0]
    assert (loc["strategy"], loc["role"], loc["confident"]) == ("text", "", False)
    assert any("unknown ARIA role 'btn'" in w for w in warnings)


def test_role_is_lowercased_and_kept_when_valid():
    page = {"name": "P", "path": "/", "locators": [_locator("ok", strategy="role", role=" Button ", value="OK")]}
    cleaned, _ = validate_automation(_result([page], []), {})

    assert cleaned["pages"][0]["locators"][0]["role"] == "button"


def test_role_is_cleared_for_other_strategies():
    page = {"name": "P", "path": "/", "locators": [_locator("ok", strategy="label", role="button")]}
    cleaned, _ = validate_automation(_result([page], []), {})

    assert cleaned["pages"][0]["locators"][0]["role"] == ""


def test_unknown_page_becomes_todo():
    raw = _result([LOGIN], [{"test_id": "TC_1", "title": "t", "steps": [
        _step("goto", page="HomePage", source="Open home"),
    ]}])
    cleaned, warnings = validate_automation(raw, {})

    assert cleaned["tests"][0]["steps"][0] == {
        "action": "todo", "page": "", "locator": "", "value": "", "source": "Open home",
    }
    assert "TC_1 step 1: unknown page 'HomePage'." in warnings


def test_unknown_locator_becomes_todo():
    raw = _result([LOGIN], [{"test_id": "TC_3", "title": "t", "steps": [
        _step("goto", page="LoginPage"),
        _step("goto", page="LoginPage"),
        _step("goto", page="LoginPage"),
        _step("click", page="LoginPage", locator="foo"),
    ]}])
    cleaned, warnings = validate_automation(raw, {})

    assert cleaned["tests"][0]["steps"][3]["action"] == "todo"
    assert "TC_3 step 4: unknown locator 'foo' on LoginPage." in warnings


def test_missing_required_field_becomes_todo():
    raw = _result([LOGIN], [{"test_id": "TC_1", "title": "t", "steps": [
        _step("fill", page="LoginPage", locator="emailInput", value="  "),
        _step("expect_url", value=""),
    ]}])
    cleaned, warnings = validate_automation(raw, {})

    assert [s["action"] for s in cleaned["tests"][0]["steps"]] == ["todo", "todo"]
    assert "TC_1 step 1: fill is missing value." in warnings
    assert "TC_1 step 2: expect_url is missing value." in warnings


def test_unknown_action_becomes_todo():
    raw = _result([LOGIN], [{"test_id": "TC_1", "title": "t", "steps": [
        _step("hover", page="LoginPage", locator="emailInput", source=""),
    ]}])
    cleaned, warnings = validate_automation(raw, {})

    assert cleaned["tests"][0]["steps"][0]["action"] == "todo"
    assert cleaned["tests"][0]["steps"][0]["source"] == "hover"
    assert "TC_1 step 1: unknown action 'hover'." in warnings


def test_duplicate_test_id_gets_a_suffix():
    tests = [
        {"test_id": "TC_1", "title": "a", "steps": [_step("todo")]},
        {"test_id": "TC_1", "title": "b", "steps": [_step("todo")]},
    ]
    cleaned, warnings = validate_automation(_result([], tests), {"TC_1": "Login"})

    assert [t["test_id"] for t in cleaned["tests"]] == ["TC_1", "TC_1_2"]
    assert [t["module"] for t in cleaned["tests"]] == ["Login", "Login"]
    assert "Duplicate test id 'TC_1' renamed to 'TC_1_2'." in warnings


def test_test_without_steps_gets_one_todo():
    cleaned, warnings = validate_automation(_result([], [{"test_id": "TC_1", "title": "a", "steps": []}]), {})

    assert [s["action"] for s in cleaned["tests"][0]["steps"]] == ["todo"]
    assert "TC_1: no steps were returned; marked as fixme." in warnings


def test_unknown_module_is_empty():
    cleaned, _ = validate_automation(_result([], [{"test_id": "TC_9", "title": "a", "steps": [_step("todo")]}]), {})

    assert cleaned["tests"][0]["module"] == ""
