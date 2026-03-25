"""
app.py  –  Brovarski Papers: AI Transcription & Review Platform
===============================================================
Main entry point for the multi-page Streamlit application.

Run with:
    streamlit run app.py

Pages:
  1. Dashboard   – overview metrics and progress
  2. Upload      – drag-and-drop card images + automatic AI transcription
  3. Review      – human-in-the-loop correction interface
  4. Export      – download CSV / JSON, rebuild export
  5. Settings    – API key, model selection, app configuration
"""

import os
import streamlit as st

# ── Page configuration ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Brovarski Papers",
    page_icon="𓂀",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Sidebar branding */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
}
[data-testid="stSidebar"] * { color: #e0e0e0 !important; }
[data-testid="stSidebar"] .stRadio label { font-size: 0.95rem; }

/* Metric cards */
[data-testid="metric-container"] {
    background: #f8f5f0;
    border: 1px solid #d4c5a9;
    border-radius: 8px;
    padding: 12px;
}

/* Status badges */
.badge-pending  { background:#ffc107; color:#000; padding:2px 8px; border-radius:12px; font-size:0.8rem; }
.badge-reviewed { background:#28a745; color:#fff; padding:2px 8px; border-radius:12px; font-size:0.8rem; }
.badge-flagged  { background:#dc3545; color:#fff; padding:2px 8px; border-radius:12px; font-size:0.8rem; }
.badge-error    { background:#6c757d; color:#fff; padding:2px 8px; border-radius:12px; font-size:0.8rem; }

/* Card image border */
.card-image img { border: 2px solid #d4c5a9; border-radius: 4px; }

/* Hieroglyph warning */
.hieroglyph-warning {
    background: #fff3cd;
    border-left: 4px solid #ffc107;
    padding: 10px 14px;
    border-radius: 4px;
    margin-bottom: 12px;
}
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "base_url": os.environ.get(
            "OPENAI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/"
        ),
        "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "review_index": 0,
        "review_filter": "Pending only",
        "active_page": "Dashboard",
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ── Sidebar navigation ────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 𓂀 Brovarski Papers")
    st.markdown("*AI Transcription & Review Platform*")
    st.divider()

    page = st.radio(
        "Navigation",
        ["Dashboard", "Upload & Transcribe", "Review Cards", "Export Data", "Settings"],
        index=["Dashboard", "Upload & Transcribe", "Review Cards", "Export Data", "Settings"]
              .index(st.session_state.get("active_page", "Dashboard")),
        label_visibility="collapsed",
    )
    st.session_state["active_page"] = page

    st.divider()

    # Quick stats in sidebar
    from data_store import count_by_status
    counts = count_by_status()
    total = counts["total"]
    done  = counts["reviewed"] + counts["flagged"]
    st.caption(f"**{done}** / **{total}** cards reviewed")
    if total > 0:
        st.progress(done / total)

    # API key status indicator
    st.divider()
    if st.session_state["api_key"]:
        st.success("API key configured", icon="✅")
    else:
        st.warning("No API key set", icon="⚠️")
        if st.button("Go to Settings", use_container_width=True):
            st.session_state["active_page"] = "Settings"
            st.rerun()


# ── Page routing ──────────────────────────────────────────────────────────────
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
