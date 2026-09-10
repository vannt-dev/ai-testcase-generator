import io

import openpyxl
import pytest

from core.file_import import FileImportError, MAX_IMPORTED_ROWS, parse_uploaded_file


class FakeUploadedFile:
    def __init__(self, name: str, content: bytes):
        self.name = name
        self._content = content

    def getvalue(self) -> bytes:
        return self._content


def _make_xlsx_bytes(headers, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_parse_uploaded_xlsx_returns_rows_keyed_by_header():
    content = _make_xlsx_bytes(
        ["ID", "Title"],
        [["TC_001", "Login works"], ["TC_002", "Login fails"]],
    )
    uploaded = FakeUploadedFile("cases.xlsx", content)

    rows = parse_uploaded_file(uploaded)

    assert rows == [
        {"ID": "TC_001", "Title": "Login works"},
        {"ID": "TC_002", "Title": "Login fails"},
    ]


def test_parse_uploaded_csv_returns_rows_keyed_by_header():
    content = "ID,Title\nTC_001,Login works\nTC_002,Login fails\n".encode("utf-8")
    uploaded = FakeUploadedFile("cases.csv", content)

    rows = parse_uploaded_file(uploaded)

    assert rows == [
        {"ID": "TC_001", "Title": "Login works"},
        {"ID": "TC_002", "Title": "Login fails"},
    ]


def test_parse_uploaded_file_rejects_unsupported_extension():
    uploaded = FakeUploadedFile("cases.txt", b"whatever")

    with pytest.raises(FileImportError, match="Unsupported file type"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_file_rejects_empty_file():
    content = _make_xlsx_bytes(["ID", "Title"], [])
    uploaded = FakeUploadedFile("empty.xlsx", content)

    with pytest.raises(FileImportError, match="no data rows"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_file_rejects_too_many_rows():
    content = _make_xlsx_bytes(["ID"], [[f"TC_{i}"] for i in range(MAX_IMPORTED_ROWS + 1)])
    uploaded = FakeUploadedFile("huge.xlsx", content)

    with pytest.raises(FileImportError, match="row limit"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_file_accepts_exactly_max_rows():
    content = _make_xlsx_bytes(["ID"], [[f"TC_{i}"] for i in range(MAX_IMPORTED_ROWS)])
    uploaded = FakeUploadedFile("boundary.xlsx", content)

    rows = parse_uploaded_file(uploaded)

    assert len(rows) == MAX_IMPORTED_ROWS


def test_parse_uploaded_csv_rejects_too_many_rows():
    lines = ["ID"] + [f"TC_{i}" for i in range(MAX_IMPORTED_ROWS + 1)]
    uploaded = FakeUploadedFile("huge.csv", "\n".join(lines).encode("utf-8"))

    with pytest.raises(FileImportError, match="row limit"):
        parse_uploaded_file(uploaded)


def test_parse_uploaded_csv_accepts_exactly_max_rows():
    lines = ["ID"] + [f"TC_{i}" for i in range(MAX_IMPORTED_ROWS)]
    uploaded = FakeUploadedFile("boundary.csv", "\n".join(lines).encode("utf-8"))

    rows = parse_uploaded_file(uploaded)

    assert len(rows) == MAX_IMPORTED_ROWS


def test_parse_uploaded_file_rejects_unsupported_extension_without_reading_bytes():
    class ExplodingUploadedFile:
        name = "cases.txt"

        def getvalue(self):
            raise AssertionError("getvalue() must not be called for an unsupported type")

    with pytest.raises(FileImportError, match="Unsupported file type"):
        parse_uploaded_file(ExplodingUploadedFile())


def test_parse_xlsx_pads_short_data_row_with_none(monkeypatch):
    """A malformed file can yield a row shorter than the header row."""
    import core.file_import as file_import

    class _FakeSheet:
        def iter_rows(self, values_only=True):
            yield ("ID", "Title", "Extra")
            yield ("TC_001", "Login works")  # short row

    class _FakeWorkbook:
        active = _FakeSheet()

    monkeypatch.setattr(
        file_import.openpyxl, "load_workbook", lambda *args, **kwargs: _FakeWorkbook()
    )

    rows = parse_uploaded_file(FakeUploadedFile("short.xlsx", b"ignored"))

    assert rows == [{"ID": "TC_001", "Title": "Login works", "Extra": None}]


def test_parse_uploaded_csv_rejects_invalid_utf8():
    uploaded = FakeUploadedFile("bad.csv", b"\x80\x81\x82")

    with pytest.raises(FileImportError, match="UTF-8"):
        parse_uploaded_file(uploaded)
