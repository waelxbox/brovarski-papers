"""
app.py  –  Brovarski Papers: AI Transcription & Review Platform
Main entry point for the multi-page Streamlit application.

Run with:
    streamlit run app.py
"""

import os
import streamlit as st

st.set_page_config(
    page_title="Brovarski Papers",
    page_icon="𓂀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
}
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }
[data-testid="stSidebar"] .stRadio label { font-size: 0.95rem; }
[data-testid="metric-container"] {
    background: #f8f5f0;
    border: 1px solid #d4c5a9;
    border-radius: 8px;
    padding: 12px;
}
</style>
""", unsafe_allow_html=True)


def _init_state():
    defaults = {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "review_index": 0,
        "review_filter": "Pending only",
        "active_page": "Dashboard",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

PAGES = ["Dashboard", "Upload & Transcribe", "Review Cards", "Export Data", "Settings", "Google Drive"]

with st.sidebar:
    st.markdown("## 𓂀 Brovarski Papers")
    st.markdown("*AI Transcription & Review Platform*")
    st.divider()

    page = st.radio(
        "Navigation",
        PAGES,
        index=PAGES.index(st.session_state.get("active_page", "Dashboard")),
        label_visibility="collapsed",
    )
    st.session_state["active_page"] = page

    st.divider()

    from data_store import count_by_status
    counts = count_by_status()
    total = counts["total"]
    done = counts["reviewed"] + counts["flagged"]
    st.caption(f"**{done}** / **{total}** cards reviewed")
    if total > 0:
        st.progress(done / total)

    st.divider()

    # Google Drive status indicator
    if st.session_state.get("gdrive_creds"):
        st.success("Google Drive connected", icon="☁️")
    else:
        st.info("Storage: Local (temporary)", icon="💾")
        if st.button("Connect Google Drive", use_container_width=True):
            st.session_state["active_page"] = "Google Drive"
            st.rerun()

    st.divider()
    if st.session_state["api_key"]:
        st.success("API key configured", icon="✅")
    else:
        st.warning("No API key set", icon="⚠️")
        if st.button("Go to Settings", use_container_width=True):
            st.session_state["active_page"] = "Settings"
            st.rerun()


if page == "Dashboard":
    from pages.dashboard import render
    render()
elif page == "Upload & Transcribe":
    from pages.upload import render
    render()
elif page == "Review Cards":
    from pages.review import render
    render()
elif page == "Export Data":
    from pages.export import render
    render()
elif page == "Settings":
    from pages.settings import render
    render()
elif page == "Google Drive":
    from pages.gdrive_auth import render
    render()
