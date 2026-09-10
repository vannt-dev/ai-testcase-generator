"""Parses uploaded test case files (.xlsx/.csv) into raw rows, independent of any target schema."""
import csv
import io

import openpyxl

MAX_IMPORTED_ROWS = 500


class FileImportError(ValueError):
    """File import error with a user-friendly message for the UI."""


def parse_uploaded_file(uploaded_file) -> list[dict]:
    """
    uploaded_file: an object exposing `.name` (str) and `.getvalue()`
    (bytes) — matches Streamlit's UploadedFile.
    Returns a list of dicts keyed by the file's own column headers.
    Raises FileImportError on an unsupported extension, an empty or
    unreadable file, or more than MAX_IMPORTED_ROWS data rows.
    """
    name = getattr(uploaded_file, "name", "")
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    raw_bytes = uploaded_file.getvalue()

    if suffix == "csv":
        rows = _parse_csv(raw_bytes)
    elif suffix == "xlsx":
        rows = _parse_xlsx(raw_bytes)
    else:
        raise FileImportError(
            f"Unsupported file type '.{suffix}'. Please upload a .xlsx or .csv file."
        )

    if not rows:
        raise FileImportError("The uploaded file has no data rows.")
    if len(rows) > MAX_IMPORTED_ROWS:
        raise FileImportError(
            f"The uploaded file has {len(rows):,} rows, which exceeds the "
            f"{MAX_IMPORTED_ROWS:,} row limit. Please split it into smaller files."
        )
    return rows


def _parse_csv(raw_bytes: bytes) -> list[dict]:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FileImportError(f"Could not read the CSV file as UTF-8: {error}") from error
    reader = csv.DictReader(io.StringIO(text))
    return [dict(row) for row in reader]


def _parse_xlsx(raw_bytes: bytes) -> list[dict]:
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
    except Exception as error:
        raise FileImportError(f"Could not read the Excel file: {error}") from error

    sheet = workbook.active
    rows_iter = sheet.iter_rows(values_only=True)
    try:
        headers = [str(h).strip() if h is not None else "" for h in next(rows_iter)]
    except StopIteration:
        return []

    rows = []
    for values in rows_iter:
        if all(v is None for v in values):
            continue
        rows.append({headers[i]: values[i] for i in range(len(headers))})
    return rows
