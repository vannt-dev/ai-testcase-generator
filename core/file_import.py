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

    # Reject an unsupported extension before reading a single byte.
    if suffix not in ("csv", "xlsx"):
        raise FileImportError(
            f"Unsupported file type '.{suffix}'. Please upload a .xlsx or .csv file."
        )

    raw_bytes = uploaded_file.getvalue()
    rows = _parse_csv(raw_bytes) if suffix == "csv" else _parse_xlsx(raw_bytes)

    if not rows:
        raise FileImportError("The uploaded file has no data rows.")
    return rows


def _too_many_rows_error() -> FileImportError:
    return FileImportError(
        f"The uploaded file has more than {MAX_IMPORTED_ROWS:,} rows, which exceeds the "
        f"{MAX_IMPORTED_ROWS:,} row limit. Please split it into smaller files."
    )


def _parse_csv(raw_bytes: bytes) -> list[dict]:
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise FileImportError(f"Could not read the CSV file as UTF-8: {error}") from error
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        if len(rows) >= MAX_IMPORTED_ROWS:
            # Stop as soon as the cap is exceeded so a hostile file cannot
            # be fully materialized in memory first.
            raise _too_many_rows_error()
        rows.append(dict(row))
    return rows


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
        if len(rows) >= MAX_IMPORTED_ROWS:
            # Stop as soon as the cap is exceeded so a hostile file cannot
            # be fully materialized in memory first.
            raise _too_many_rows_error()
        # A malformed file can yield a row shorter than the header row —
        # pad the missing trailing columns instead of raising IndexError.
        rows.append({h: (values[i] if i < len(values) else None) for i, h in enumerate(headers)})
    return rows
