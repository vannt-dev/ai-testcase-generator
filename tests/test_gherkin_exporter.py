from core.gherkin_exporter import export_to_gherkin

SAMPLE_RESULT = {
    "test_cases": [
        {
            "test_id": "TC_LOGIN_001",
            "module": "Login",
            "title": "Successful login with valid phone number + OTP",
            "precondition": "Account is registered, not logged in",
            "steps": "1. Enter phone number\n2. Enter correct OTP\n3. Tap Login",
            "test_data": "Phone: 0912345678, OTP: 123456",
            "expected_result": "Login succeeds, redirected to the Home screen",
            "priority": "High",
            "type": "Positive",
            "platform": "All",
        },
        {
            "test_id": "TC_LOGIN_002",
            "module": "Login",
            "title": "Wrong OTP is rejected",
            "precondition": "",
            "steps": "Enter phone number\nEnter a wrong OTP",
            "test_data": "",
            "expected_result": "An error is shown\nThe user stays on the Login screen",
            "priority": "Medium",
            "type": "Negative",
            "platform": "Mobile App",
        },
    ],
    "summary": {"total": 2, "open_questions": ["How many OTP attempts are allowed?"]},
}


def test_each_test_case_becomes_a_tagged_scenario_with_given_when_then():
    feature = export_to_gherkin(SAMPLE_RESULT, feature_name="Shop app")

    assert feature == (
        "# language: en\n"
        "Feature: Shop app\n"
        "\n"
        "  # Open questions to confirm with BA/Dev:\n"
        "  # - How many OTP attempts are allowed?\n"
        "\n"
        "  @TC_LOGIN_001 @Login @High @Positive @All\n"
        "  Scenario: Successful login with valid phone number + OTP\n"
        "    # Test data: Phone: 0912345678, OTP: 123456\n"
        "    Given Account is registered, not logged in\n"
        "    When Enter phone number\n"
        "    And Enter correct OTP\n"
        "    And Tap Login\n"
        "    Then Login succeeds, redirected to the Home screen\n"
        "\n"
        "  @TC_LOGIN_002 @Login @Medium @Negative @Mobile_App\n"
        "  Scenario: Wrong OTP is rejected\n"
        "    When Enter phone number\n"
        "    And Enter a wrong OTP\n"
        "    Then An error is shown\n"
        "    And The user stays on the Login screen\n"
    )


def test_list_markers_and_existing_keywords_are_not_repeated():
    result = {
        "test_cases": [
            {
                "title": "Markers",
                "precondition": "Given the user is logged in\nAnd has one item in the cart",
                "steps": "1) Open the cart\n- Tap Checkout\n* Confirm\n  2.  Pay  now  ",
                "expected_result": "Then the order is placed",
            }
        ]
    }

    feature = export_to_gherkin(result)

    assert "    Given the user is logged in\n    And has one item in the cart\n" in feature
    assert (
        "    When Open the cart\n    And Tap Checkout\n    And Confirm\n    And Pay now\n"
        in feature
    )
    assert "    Then the order is placed\n" in feature
    assert "Given Given" not in feature and "Then Then" not in feature


def test_text_that_would_break_the_file_is_kept_on_one_line():
    result = {
        "test_cases": [
            {
                "test_id": "@TC 1 / a",
                "module": "Đăng nhập",
                "priority": "High",
                "type": "High",
                "title": "Line one\nScenario: injected",
                "steps": "Tap\t\tLogin",
                "expected_result": "",
                "test_data": "a: 1\nb: 2",
            },
            {"title": "", "steps": "", "expected_result": "", "precondition": ""},
        ],
        "summary": {"open_questions": ["first line\nFeature: injected", ""]},
    }

    feature = export_to_gherkin(result, feature_name="  My\nproject ")
    lines = feature.splitlines()

    assert lines[1] == "Feature: My project"
    assert "  # - first line Feature: injected" in lines
    # One tag per value, no "@" or spaces inside, duplicates dropped, Unicode kept.
    assert "  @TC_1_a @Đăng_nhập @High" in lines
    assert "  Scenario: Line one Scenario: injected" in lines
    assert "    # Test data: a: 1" in lines and "    # Test data: b: 2" in lines
    assert "    When Tap Login" in lines
    # Only two scenarios and one feature exist, whatever the cells contained.
    assert sum(line.startswith("  Scenario:") for line in lines) == 2
    assert sum(line.startswith("Feature:") for line in lines) == 1
    assert "  Scenario: Test case 2" in lines
    assert "    # This test case has no precondition, steps or expected result." in lines


def test_an_empty_set_is_still_a_valid_feature_file():
    assert export_to_gherkin({"test_cases": []}) == "# language: en\nFeature: Test cases\n"
    assert export_to_gherkin({}, feature_name="") == "# language: en\nFeature: Test cases\n"
