# Cách thêm một project mới

Tool này được thiết kế để dùng chung 1 core engine cho nhiều project khác
nhau — mỗi project chỉ cần 1 file config riêng, không cần sửa code.

## Các bước

1. Copy file template:
   ```bash
   cp configs/_template.yaml configs/<ten_project_cua_ban>.yaml
   ```
   Tên file (không tính `.yaml`) sẽ là tên hiển thị trong dropdown chọn
   project trên UI.

2. Mở file vừa tạo và điền các thông tin:
   - `project_name`: tên hiển thị đầy đủ
   - `platform`: web / ios / android (có thể chọn nhiều)
   - `test_id_format`: format ID test case theo convention của team bạn
   - `test_types_required`: loại test case cần ưu tiên
   - `domain_rules`: **quan trọng nhất** — càng chi tiết, AI sinh case
     càng sát thực tế, ví dụ:
     - Rule validate input (số điện thoại, email, mật khẩu...)
     - Giới hạn nghiệp vụ (số lượng tối đa, thời gian timeout...)
     - Hành vi đặc thù của hệ thống khi lỗi xảy ra
   - `glossary`: giải nghĩa thuật ngữ riêng của hệ thống/domain, để AI
     không hiểu sai ngữ cảnh
   - `notes`: bất kỳ điều gì khác muốn AI lưu ý (VD: ưu tiên test kỹ
     module nào)

3. Chạy lại app (`streamlit run app.py`), project mới sẽ tự động xuất
   hiện trong dropdown — không cần sửa code.

## Mẹo để config hiệu quả

- Bắt đầu với 1 config đơn giản, chạy thử với vài requirement thật, xem
  AI sinh case có sát không, rồi bổ sung dần `domain_rules` dựa trên
  những chỗ AI hiểu sai hoặc bỏ sót.
- Nếu team có nhiều module với rule khác biệt lớn (VD: module Payment
  và module User Profile), có thể cân nhắc chia nhỏ thành từng "sub-config"
  hoặc note rõ trong `domain_rules` rule nào áp dụng cho module nào.
- Định kỳ review lại config theo feedback từ tester dùng thực tế.

## Nếu muốn thay đổi logic sinh test case chung (áp dụng mọi project)

Sửa file `prompts/base_system_prompt.md`. File này chứa các quy tắc
chung (bắt buộc phân loại test case, format JSON output...) áp dụng cho
tất cả project. Không nên đặt thông tin đặc thù của 1 project cụ thể
vào đây — hãy đặt vào file config YAML tương ứng.
