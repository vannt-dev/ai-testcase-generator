"""
Module xuất bộ test case (dict trả về từ AI) ra file Excel (.xlsx)
theo format chuẩn, có style cơ bản để dễ đọc.
"""
import io
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

COLUMNS = [
    ("test_id", "Test ID", 16),
    ("module", "Module", 14),
    ("title", "Test Title", 30),
    ("precondition", "Precondition", 25),
    ("steps", "Test Steps", 40),
    ("test_data", "Test Data", 20),
    ("expected_result", "Expected Result", 35),
    ("priority", "Priority", 10),
    ("type", "Type", 14),
    ("platform", "Platform", 12),
]

PRIORITY_COLORS = {
    "High": "FFC7CE",
    "Medium": "FFEB9C",
    "Low": "C6EFCE",
}


def export_to_excel(result: dict, sheet_name: str = "Test Cases") -> bytes:
    """
    Nhận dict {"test_cases": [...], "summary": {...}} và trả về
    nội dung file .xlsx dạng bytes, sẵn sàng để tải xuống hoặc lưu file.
    """
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    wrap_alignment = Alignment(wrap_text=True, vertical="top")

    # Header
    for col_idx, (_, header, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        ws.column_dimensions[get_column_letter(col_idx)].width = width

    # Data rows
    test_cases = result.get("test_cases", [])
    for row_idx, tc in enumerate(test_cases, start=2):
        for col_idx, (key, _, _) in enumerate(COLUMNS, start=1):
            cell = ws.cell(row=row_idx, column=col_idx, value=tc.get(key, ""))
            cell.alignment = wrap_alignment
            if key == "priority" and tc.get(key) in PRIORITY_COLORS:
                cell.fill = PatternFill(
                    start_color=PRIORITY_COLORS[tc[key]],
                    end_color=PRIORITY_COLORS[tc[key]],
                    fill_type="solid",
                )

    ws.freeze_panes = "A2"

    # Sheet phụ: Summary
    summary = result.get("summary", {})
    if summary:
        ws2 = wb.create_sheet("Summary")
        ws2.append(["Tổng số test case", summary.get("total", len(test_cases))])
        ws2.append([])
        ws2.append(["Loại", "Số lượng"])
        for k, v in summary.get("by_type", {}).items():
            ws2.append([k, v])
        ws2.append([])
        ws2.append(["Câu hỏi cần confirm thêm với BA/Dev"])
        for q in summary.get("open_questions", []):
            ws2.append([q])
        ws2.column_dimensions["A"].width = 45
        ws2.column_dimensions["B"].width = 15

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
