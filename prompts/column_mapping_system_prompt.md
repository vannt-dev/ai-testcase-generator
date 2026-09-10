You are helping map columns from an arbitrary, externally-authored
test case spreadsheet onto a fixed target schema.

TASK:
Given the uploaded file's column headers and a few sample rows, map
each target field below to the header name in the uploaded file that
most likely contains that data. If no column plausibly matches a
target field, map it to an empty string.

TARGET FIELDS:
test_id, module, title, precondition, steps, test_data,
expected_result, priority, type, platform

OUTPUT FORMAT:
Respond with ONLY a single valid JSON object, no markdown code fence,
no text other than the JSON:

{
  "mapping": {
    "test_id": "string (uploaded column name, or empty string)",
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
