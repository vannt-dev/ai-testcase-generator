You are helping map columns from an executed test run spreadsheet (test
cases plus the result of running them) onto a fixed target schema.

TASK:
Given the uploaded file's column headers and a few sample rows, map each
target field below to the header name in the uploaded file that most
likely contains that data. If no column plausibly matches a target field,
map it to an empty string.

TARGET FIELDS:
- status: the execution result of each test (e.g. Pass/Fail, Passed/Failed,
  Đạt/Không đạt, OK/NG)
- actual_result: what actually happened when the test ran
- comment: the tester's remarks or notes about the run (optional)
- test_id, module, title, precondition, steps, test_data,
  expected_result, priority, type, platform: the test case itself
  (optional)

Do not map "status" to a priority or type column, and do not map
"actual_result" to the expected result column.

OUTPUT FORMAT:
Respond with ONLY a single valid JSON object, no markdown code fence,
no text other than the JSON:

{
  "mapping": {
    "status": "string (uploaded column name, or empty string)",
    "actual_result": "string",
    "comment": "string",
    "test_id": "string",
    "module": "string",
    "title": "string",
    "precondition": "string",
    "steps": "string",
    "test_data": "string",
    "expected_result": "string",
    "priority": "string",
    "type": "string",
    "platform": "string"
  }
}
