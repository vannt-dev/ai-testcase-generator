"""
Data sets for data-driven testing: a table of concrete values for the input
fields of one test case, one row per combination, each with a category
(Valid, Boundary, Invalid) and an expected result.

A data set is {"fields": [...], "rows": [{"category", "values", "expected_result"}],
"source": "..."}, kept in a result under "data_sets", keyed by test id. Field
values are kept exactly as given: a leading space, "", "-1" or "=1+1" can be
the very value a row tests.
"""
import csv
import io

from core.file_import import parse_uploaded_file

CATEGORY_COLUMN = "category"
EXPECTED_COLUMN = "expected_result"
CATEGORIES = ("Valid", "Boundary", "Invalid")
# Rows asked of the AI in one reply, and the most a data set keeps.
MAX_AI_ROWS = 30
MAX_DATA_SET_ROWS = 200


class DataSetError(ValueError):
    """The data set cannot be used; the message says why, for the UI."""


def _column_key(header: str) -> str:
    """"Expected Result", "expected-result" and "expected_result" all give "expected_result"."""
    return "_".join(str(header).strip().lower().replace("-", " ").split())


def _category(value) -> str:
    text = "" if value is None else str(value).strip()
    for category in CATEGORIES:
        if text.lower() == category.lower():
            return category
    return text


def _check_fields(fields: list[str]) -> list[str]:
    names = [str(field).strip() for field in fields]
    if not names or any(not name for name in names):
        raise DataSetError("Every input field of the data set needs a name.")
    seen: set[str] = set()
    for name in names:
        key = _column_key(name)
        if key in (CATEGORY_COLUMN, EXPECTED_COLUMN):
            raise DataSetError(f'"{name}" cannot be an input field name: it is a reserved column.')
        if key in seen:
            raise DataSetError(f'The input field "{name}" appears more than once.')
        seen.add(key)
    return names


def data_set_from_reply(reply: dict, source: str = "AI") -> dict:
    """
    Check the AI's reply ({"fields", "rows", "open_questions"}) and turn it
    into a data set. Every row must give each field exactly one value; a
    missing, repeated or unknown field raises DataSetError, so nothing is
    attached.
    """
    fields = _check_fields(reply.get("fields") or [])
    rows = []
    for number, row in enumerate(reply.get("rows") or [], start=1):
        values: dict[str, str] = {}
        for cell in row.get("values") or []:
            field = str(cell.get("field", "")).strip()
            if field not in fields:
                raise DataSetError(
                    f'Row {number} has a value for "{field}", which is not one of the fields. '
                    "Nothing was attached; try again."
                )
            if field in values:
                raise DataSetError(
                    f'Row {number} gives "{field}" more than once. Nothing was attached; try again.'
                )
            values[field] = "" if cell.get("value") is None else str(cell.get("value"))
        missing = [field for field in fields if field not in values]
        if missing:
            raise DataSetError(
                f"Row {number} has no value for {', '.join(missing)}. Nothing was attached; "
                "try again."
            )
        rows.append(
            {
                "category": _category(row.get("category")),
                "values": {field: values[field] for field in fields},
                "expected_result": str(row.get("expected_result") or "").strip(),
            }
        )
    if not rows:
        raise DataSetError("The AI returned no data rows. Nothing was attached; try again.")
    if len(rows) > MAX_DATA_SET_ROWS:
        raise DataSetError(f"The data set has more than {MAX_DATA_SET_ROWS} rows.")
    return {
        "fields": fields,
        "rows": rows,
        "source": source,
        "open_questions": [str(q) for q in reply.get("open_questions") or [] if str(q).strip()],
    }


def data_set_from_file(uploaded_file) -> dict:
    """
    Read a .csv/.xlsx of data rows (the format data_set_to_csv writes, or any
    table with a header row). A "category" and an "expected_result" (or
    "Expected Result") column are optional; every other named column is an
    input field. Raises DataSetError (a FileImportError is passed on as one).
    """
    try:
        raw_rows = parse_uploaded_file(uploaded_file)
    except ValueError as error:
        raise DataSetError(str(error)) from error
    headers = [header for header in raw_rows[0] if str(header).strip()]
    category_header = next((h for h in headers if _column_key(h) == CATEGORY_COLUMN), None)
    expected_header = next((h for h in headers if _column_key(h) == EXPECTED_COLUMN), None)
    fields = [h for h in headers if h not in (category_header, expected_header)]
    if not fields:
        raise DataSetError(
            "The file has no input field columns: only category and expected result were found."
        )
    _check_fields(fields)

    def text(value) -> str:
        return "" if value is None else str(value)

    rows = []
    for raw in raw_rows:
        values = {field: text(raw.get(field)) for field in fields}
        expected = text(raw.get(expected_header)).strip() if expected_header else ""
        category = _category(raw.get(category_header)) if category_header else ""
        if not any(values.values()) and not expected and not category:
            continue  # a row of empty cells
        rows.append({"category": category, "values": values, "expected_result": expected})
    if not rows:
        raise DataSetError("The uploaded file has no data rows.")
    if len(rows) > MAX_DATA_SET_ROWS:
        raise DataSetError(
            f"The file has {len(rows)} data rows; a data set keeps at most {MAX_DATA_SET_ROWS}."
        )
    return {
        "fields": fields,
        "rows": rows,
        "source": getattr(uploaded_file, "name", "") or "file",
        "open_questions": [],
    }


def data_set_records(data_set: dict) -> list[dict]:
    """The rows as flat records, columns in CSV order, for a table or a CSV file."""
    return [
        {
            CATEGORY_COLUMN: row.get("category", ""),
            **{field: row.get("values", {}).get(field, "") for field in data_set["fields"]},
            EXPECTED_COLUMN: row.get("expected_result", ""),
        }
        for row in data_set.get("rows", [])
    ]


def data_set_to_csv(data_set: dict) -> bytes:
    """
    The data set as CSV: category, one column per field, expected_result.
    UTF-8 with a BOM so Excel shows accented text; values are written exactly,
    since a test runner reads them as test input.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([CATEGORY_COLUMN, *data_set["fields"], EXPECTED_COLUMN])
    for record in data_set_records(data_set):
        writer.writerow(list(record.values()))
    return buffer.getvalue().encode("utf-8-sig")

