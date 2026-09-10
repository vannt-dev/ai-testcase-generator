# AI Test Case Generator

[![Tests](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml/badge.svg)](https://github.com/vannt-dev/ai-testcase-generator/actions/workflows/tests.yml)

Công cụ hỗ trợ **manual tester** sinh test case tự động từ requirement/user
story bằng AI (Claude), xuất ra file Excel sẵn sàng sử dụng. Thiết kế để
**áp dụng được cho bất kỳ project nào** — chỉ cần thêm 1 file config,
không cần sửa code.

## Vì sao dùng tool này

- Giảm thời gian viết test case thủ công
- Tăng coverage: AI thường nghĩ ra các edge case/negative case mà con
  người dễ bỏ sót
- Chuẩn hóa format test case giữa các thành viên trong team
- Mở rộng dễ dàng cho nhiều project khác nhau nhờ hệ thống config tách biệt
- Tự động thử lại khi gặp lỗi tạm thời (rate limit, mất kết nối) từ Anthropic API
- Lưu lại lịch sử các lần sinh test case trong phiên làm việc để xem lại/khôi phục

## Kiến trúc

```
Core Engine (không đổi giữa các project)
        +
Project Config (YAML — đổi theo từng project)
        =
Test case phù hợp với domain/business rule riêng của project đó
```

## Cấu trúc thư mục

```
ai-testcase-generator/
├── app.py                       # Streamlit UI chính
├── core/
│   ├── ai_client.py              # Gọi Claude API (retry, pricing, structured output)
│   ├── prompt_builder.py         # Ghép base prompt + config project
│   ├── result_utils.py           # Chuẩn hóa/tính lại summary khi user chỉnh sửa
│   └── excel_exporter.py         # Xuất kết quả ra .xlsx
├── configs/
│   ├── _template.yaml            # Copy file này khi thêm project mới
│   └── example_ecommerce.yaml    # Config mẫu
├── prompts/
│   └── base_system_prompt.md     # Prompt gốc, áp dụng chung mọi project
├── tests/                        # pytest (core logic + integration test cho app.py)
├── .github/workflows/tests.yml   # CI: chạy pytest trên mỗi push/PR
└── docs/
    └── how-to-add-new-project.md
```

## Cài đặt

Yêu cầu Python >= 3.10 (code dùng cú pháp type hint `str | None`).

```bash
git clone <repo-url>
cd ai-testcase-generator
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Lấy Anthropic API key tại https://console.anthropic.com/, sau đó:

```bash
cp .env.example .env
# Điền ANTHROPIC_API_KEY vào file .env
```

(Hoặc bỏ qua bước này và nhập trực tiếp API key trong sidebar khi chạy app.)

## Chạy thử

```bash
streamlit run app.py
```

Mở trình duyệt tại `http://localhost:8501`:
1. Chọn project ở sidebar (mặc định có sẵn `example_ecommerce`)
2. Paste requirement/user story vào ô nhập
3. Nhấn **Sinh Test Case**
4. Xem kết quả dạng bảng, tải file Excel

## Chạy test

```bash
pip install -r requirements-dev.txt
pytest -q
```

CI (GitHub Actions) tự động chạy toàn bộ test suite trên mỗi push/PR vào `main`.

## Bảo mật

- API key nhập trong sidebar chỉ tồn tại trong `st.session_state` của phiên
  trình duyệt hiện tại, không được ghi ra đĩa hay log lại.
- Nếu deploy app này ở nơi công khai (Streamlit Cloud, server chung...),
  **không** dựa vào ô nhập API key trên UI — hãy set biến môi trường
  `ANTHROPIC_API_KEY` phía server/secrets manager và ẩn/bỏ ô nhập key đó đi,
  để tránh lộ key qua session của người dùng khác hoặc qua log trình duyệt.

## Thêm project của bạn

Xem hướng dẫn chi tiết tại [`docs/how-to-add-new-project.md`](docs/how-to-add-new-project.md).
Tóm tắt nhanh:

```bash
cp configs/_template.yaml configs/ten_project_cua_ban.yaml
# Điền domain rules, glossary, platform... cho project của bạn
```

## Roadmap

- [x] Giai đoạn 1: Sinh test case từ requirement (MVP hiện tại)
- [ ] Giai đoạn 2: Test Case Reviewer / Coverage Checker
- [ ] Giai đoạn 3: AI-assisted Bug Report Writer + tích hợp Jira
- [ ] Giai đoạn 4: Mở rộng sang automation (self-healing scripts, sinh code test)

## Lưu ý

- AI sẽ hỏi lại nếu requirement thiếu thông tin quan trọng thay vì tự
  suy đoán — nếu thấy phần "Cần confirm thêm với BA/Dev" xuất hiện,
  hãy bổ sung thông tin và chạy lại.
- Chất lượng test case phụ thuộc nhiều vào chất lượng `domain_rules`
  trong file config — nên đầu tư thời gian hoàn thiện config cho từng
  project.
