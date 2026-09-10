"""
AI Test Case Generator — MVP UI (Streamlit)

Chạy: streamlit run app.py
"""
import time
from datetime import datetime

import streamlit as st
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from core.prompt_builder import (
    ProjectConfigError,
    build_system_prompt,
    estimate_prompt_size_warning,
    list_available_configs,
    load_project_config,
)
from core.ai_client import AIClient
from core.excel_exporter import export_to_excel
from core.result_utils import (
    build_edited_result,
    find_incomplete_rows,
    normalize_edited_records,
)

load_dotenv()

st.set_page_config(page_title="AI Test Case Generator", page_icon="🧪", layout="wide")

CONFIGS_DIR = Path("configs")
# Giới hạn độ dài requirement để tránh vượt context/token limit của model
# với thông báo lỗi khó hiểu — ~40,000 ký tự tương đương ~10,000 token.
MAX_REQUIREMENT_CHARS = 40000
MAX_HISTORY_ENTRIES = 10

st.title("🧪 AI Test Case Generator")
st.caption("Sinh test case tự động từ requirement — hỗ trợ manual tester")

# ---------- Sidebar ----------
with st.sidebar:
    st.header("⚙️ Cấu hình")

    available_configs = list_available_configs(CONFIGS_DIR)
    if not available_configs:
        st.error("Không tìm thấy file config nào trong thư mục configs/")
        st.stop()

    selected_config = st.selectbox("Chọn project", available_configs)

    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        value=st.session_state.get("api_key", ""),
        help="Có thể để trống nếu đã set biến môi trường ANTHROPIC_API_KEY",
    )
    if api_key:
        st.session_state["api_key"] = api_key
    if api_key:
        st.caption(
            "⚠️ API key nhập ở đây chỉ lưu trong bộ nhớ phiên trình duyệt hiện tại "
            "(không ghi ra đĩa). Nếu app này được deploy public, hãy ưu tiên set "
            "biến môi trường `ANTHROPIC_API_KEY` phía server thay vì nhập tay ở đây."
        )

    st.divider()
    try:
        config = load_project_config(CONFIGS_DIR / f"{selected_config}.yaml")
    except ProjectConfigError as error:
        st.error(str(error))
        st.stop()
    st.markdown(f"**Project:** {config.get('project_name')}")
    st.markdown(f"**Platform:** {', '.join(config.get('platform', []))}")
    with st.expander("Xem chi tiết config"):
        st.json(config)

    history = st.session_state.setdefault("history", [])
    if history:
        st.divider()
        st.subheader("🕘 Lịch sử phiên này")
        for index, entry in reversed(list(enumerate(history))):
            label = (
                f"{entry['timestamp']} · {entry['project_name']} · "
                f"{entry['test_case_count']} test case"
            )
            with st.expander(label):
                st.caption(entry["requirement_excerpt"])
                if st.button("↩️ Xem lại kết quả này", key=f"restore_history_{index}"):
                    st.session_state.pop("test_case_editor", None)
                    st.session_state["last_result"] = entry["result"]
                    st.session_state["last_project_name"] = entry["project_name"]
                    st.rerun()

# ---------- Main ----------
requirement_text = st.text_area(
    "📋 Paste Requirement / User Story / Jira ticket vào đây",
    height=250,
    placeholder="VD: Là một người dùng, tôi muốn đăng nhập bằng số điện thoại và OTP để...",
)

generate_btn = st.button("🚀 Sinh Test Case", type="primary", use_container_width=False)

if generate_btn:
    if not requirement_text.strip():
        st.warning("Vui lòng nhập requirement trước.")
        st.stop()

    if len(requirement_text) > MAX_REQUIREMENT_CHARS:
        st.error(
            f"Requirement quá dài ({len(requirement_text):,} ký tự, giới hạn "
            f"{MAX_REQUIREMENT_CHARS:,}). Hãy tách nhỏ requirement thành nhiều "
            "phần và sinh test case riêng cho từng phần."
        )
        st.stop()

    try:
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    system_prompt = build_system_prompt(config)
    prompt_warning = estimate_prompt_size_warning(system_prompt)
    if prompt_warning:
        st.warning(prompt_warning)

    start_time = time.time()
    with st.status("AI đang phân tích requirement và sinh test case...", expanded=False) as status:
        try:
            result = client.generate_test_cases(system_prompt, requirement_text)
        except ValueError as e:
            status.update(label=f"Lỗi: {e}", state="error")
            st.error(f"Có lỗi khi gọi AI: {e}")
            st.stop()
        elapsed = time.time() - start_time
        status.update(label=f"Hoàn tất trong {elapsed:.1f}s", state="complete")

    st.session_state.pop("test_case_editor", None)
    st.session_state["last_result"] = result
    st.session_state["last_project_name"] = config["project_name"]

    history = st.session_state.setdefault("history", [])
    history.append(
        {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "project_name": config["project_name"],
            "requirement_excerpt": requirement_text.strip()[:200],
            "test_case_count": len(result.get("test_cases", [])),
            "result": result,
        }
    )
    del history[:-MAX_HISTORY_ENTRIES]

# ---------- Hiển thị kết quả ----------
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    test_cases = result.get("test_cases", [])

    if not test_cases:
        st.warning("AI không sinh được test case nào — có thể do requirement thiếu thông tin.")
    else:
        st.subheader("✏️ Chỉnh sửa test case")
        st.caption("Bạn có thể sửa trực tiếp, thêm hoặc xóa dòng trước khi tải Excel.")

        df = pd.DataFrame(test_cases)
        edited_df = st.data_editor(
            df,
            key="test_case_editor",
            use_container_width=True,
            hide_index=True,
            num_rows="dynamic",
            column_config={
                "priority": st.column_config.SelectboxColumn(
                    "Priority", options=["High", "Medium", "Low"], required=True
                ),
                "type": st.column_config.SelectboxColumn(
                    "Type",
                    options=[
                        "Positive", "Negative", "Edge case", "UI/UX",
                        "Compatibility", "Performance", "Security",
                    ],
                    required=True,
                ),
                "platform": st.column_config.SelectboxColumn(
                    "Platform", options=["Web", "iOS", "Android", "All"], required=True
                ),
            },
        )
        edited_test_cases = normalize_edited_records(edited_df.to_dict("records"))
        edited_result = build_edited_result(result, edited_test_cases)
        summary = edited_result["summary"]

        st.success(f"Bộ dữ liệu hiện có {len(edited_test_cases)} test case.")

        with st.expander("Xem thống kê theo loại", expanded=True):
            st.metric("Tổng số test case", summary.get("total", len(test_cases)))
            for k, v in summary.get("by_type", {}).items():
                if v:
                    st.write(f"**{k}**: {v}")

        incomplete_rows = find_incomplete_rows(edited_test_cases)
        if incomplete_rows:
            st.error(
                "Chưa thể export: các dòng sau còn thiếu dữ liệu bắt buộc: "
                + ", ".join(map(str, incomplete_rows))
            )

        excel_bytes = export_to_excel(edited_result)
        export_project_name = st.session_state.get("last_project_name", "project")
        st.download_button(
            "⬇️ Tải xuống Excel",
            data=excel_bytes,
            file_name=f"testcases_{export_project_name.replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            disabled=bool(incomplete_rows) or not edited_test_cases,
        )

    summary = result.get("summary", {})
    open_questions = summary.get("open_questions", [])
    if open_questions:
        st.divider()
        st.subheader("❓ Cần confirm thêm với BA/Dev")
        for q in open_questions:
            st.markdown(f"- {q}")

    usage = result.get("usage", {})
    if usage:
        st.divider()
        st.subheader("📊 Token usage & chi phí ước tính")
        usage_cols = st.columns(5)
        usage_cols[0].metric("Input mới", f"{usage.get('input_tokens', 0):,}")
        usage_cols[1].metric("Output", f"{usage.get('output_tokens', 0):,}")
        usage_cols[2].metric(
            "Cache write", f"{usage.get('cache_creation_input_tokens', 0):,}"
        )
        usage_cols[3].metric(
            "Cache hit", f"{usage.get('cache_read_input_tokens', 0):,}"
        )
        estimated_cost = usage.get("estimated_cost_usd")
        usage_cols[4].metric(
            "Ước tính (USD)",
            f"${estimated_cost:.6f}" if estimated_cost is not None else "N/A",
        )
        st.caption(
            f"Model: {usage.get('model', 'N/A')}. Chi phí là ước tính theo bảng giá "
            "Claude API và có thể khác hóa đơn thực tế."
        )
        if estimated_cost is None:
            st.caption(
                f"⚠️ Chưa có bảng giá cho model `{usage.get('model', 'N/A')}` trong "
                "`MODEL_PRICING` (core/ai_client.py) nên không thể ước tính chi phí."
            )
