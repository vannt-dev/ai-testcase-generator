"""
AI Test Case Generator — MVP UI (Streamlit)

Chạy: streamlit run app.py
"""
import streamlit as st
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

from core.prompt_builder import build_system_prompt, load_project_config, list_available_configs
from core.ai_client import AIClient
from core.excel_exporter import export_to_excel

load_dotenv()

st.set_page_config(page_title="AI Test Case Generator", page_icon="🧪", layout="wide")

CONFIGS_DIR = Path("configs")

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

    st.divider()
    config = load_project_config(CONFIGS_DIR / f"{selected_config}.yaml")
    st.markdown(f"**Project:** {config.get('project_name')}")
    st.markdown(f"**Platform:** {', '.join(config.get('platform', []))}")
    with st.expander("Xem chi tiết config"):
        st.json(config)

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

    try:
        client = AIClient(api_key=st.session_state.get("api_key") or None)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    system_prompt = build_system_prompt(config)

    with st.spinner("AI đang phân tích requirement và sinh test case..."):
        try:
            result = client.generate_test_cases(system_prompt, requirement_text)
        except ValueError as e:
            st.error(f"Có lỗi khi gọi AI: {e}")
            st.stop()

    st.session_state["last_result"] = result

# ---------- Hiển thị kết quả ----------
if "last_result" in st.session_state:
    result = st.session_state["last_result"]
    test_cases = result.get("test_cases", [])
    summary = result.get("summary", {})

    if not test_cases:
        st.warning("AI không sinh được test case nào — có thể do requirement thiếu thông tin.")
    else:
        st.success(f"Đã sinh {len(test_cases)} test case.")

        col1, col2 = st.columns([3, 1])
        with col1:
            df = pd.DataFrame(test_cases)
            st.dataframe(df, use_container_width=True, hide_index=True)
        with col2:
            st.metric("Tổng số test case", summary.get("total", len(test_cases)))
            for k, v in summary.get("by_type", {}).items():
                st.write(f"**{k}**: {v}")

        excel_bytes = export_to_excel(result)
        st.download_button(
            "⬇️ Tải xuống Excel",
            data=excel_bytes,
            file_name=f"testcases_{config.get('project_name', 'project').replace(' ', '_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    open_questions = summary.get("open_questions", [])
    if open_questions:
        st.divider()
        st.subheader("❓ Cần confirm thêm với BA/Dev")
        for q in open_questions:
            st.markdown(f"- {q}")
