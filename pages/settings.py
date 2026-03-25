"""
pages/settings.py  –  API key, model, and app configuration
"""

import streamlit as st
from transcribe_engine import DEFAULT_MODEL


AVAILABLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gpt-4o",
    "gpt-4o-mini",
]

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_BASE_URL = "https://api.openai.com/v1"


def render():
    st.title("Settings")
    st.caption("Configure your API credentials and transcription preferences.")
    st.divider()

    # ── API Configuration ─────────────────────────────────────────────────────
    st.subheader("API Configuration")

    api_provider = st.radio(
        "API Provider",
        ["Google Gemini (recommended)", "OpenAI"],
        index=0,
        horizontal=True,
        help="Gemini models are recommended for handwriting recognition accuracy.",
    )

    if api_provider == "Google Gemini (recommended)":
        st.info(
            "Get a free Gemini API key at "
            "[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey). "
            "Processing 10,000 cards costs approximately $5–15 with Gemini Flash."
        )
        default_url = GEMINI_BASE_URL
    else:
        st.info("Enter your OpenAI API key from [platform.openai.com](https://platform.openai.com).")
        default_url = OPENAI_BASE_URL

    api_key = st.text_input(
        "API Key",
        value=st.session_state.get("api_key", ""),
        type="password",
        placeholder="Paste your API key here…",
        help="Your key is stored only in this browser session and never saved to disk.",
    )

    base_url = st.text_input(
        "API Base URL",
        value=st.session_state.get("base_url", default_url),
        help="Leave as default unless you are using a custom proxy or endpoint.",
    )

    st.divider()

    # ── Model Selection ───────────────────────────────────────────────────────
    st.subheader("Model Selection")

    current_model = st.session_state.get("model", DEFAULT_MODEL)
    model_idx = AVAILABLE_MODELS.index(current_model) if current_model in AVAILABLE_MODELS else 0

    model = st.selectbox(
        "Transcription Model",
        AVAILABLE_MODELS,
        index=model_idx,
        help=(
            "**gemini-2.5-flash** — Fast and cheap, excellent for most cards. "
            "**gemini-2.5-pro** — Slower and more expensive, best for difficult handwriting. "
            "**gpt-4o** — OpenAI alternative, requires an OpenAI API key."
        ),
    )

    model_info = {
        "gemini-2.5-flash": ("Fast", "~$0.001/card", "Best for most cards"),
        "gemini-2.5-pro":   ("Slow", "~$0.01/card",  "Best for difficult handwriting"),
        "gemini-2.0-flash": ("Fast", "~$0.001/card",  "Previous generation Gemini"),
        "gpt-4o":           ("Medium", "~$0.005/card", "OpenAI alternative"),
        "gpt-4o-mini":      ("Fast", "~$0.0005/card",  "OpenAI budget option"),
    }
    if model in model_info:
        speed, cost, note = model_info[model]
        col1, col2, col3 = st.columns(3)
        col1.metric("Speed", speed)
        col2.metric("Est. Cost", cost)
        col3.metric("Best For", note)

    st.divider()

    # ── Save button ───────────────────────────────────────────────────────────
    if st.button("Save Settings", type="primary", use_container_width=True):
        st.session_state["api_key"] = api_key
        st.session_state["base_url"] = base_url
        st.session_state["model"]    = model
        st.success("Settings saved for this session.")

    st.divider()

    # ── Connection test ───────────────────────────────────────────────────────
    st.subheader("Test API Connection")
    st.markdown("Send a simple test request to verify your API key and model are working.")

    if st.button("Test Connection"):
        if not api_key:
            st.error("Please enter an API key first.")
        else:
            from transcribe_engine import build_client
            from openai import OpenAI
            try:
                client = build_client(api_key=api_key, base_url=base_url or None)
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": "Reply with the single word: connected"}],
                    max_tokens=10,
                )
                reply = response.choices[0].message.content.strip().lower()
                if "connect" in reply or len(reply) < 30:
                    st.success(f"Connection successful! Model replied: *\"{reply}\"*")
                else:
                    st.warning(f"Connected, but unexpected reply: *\"{reply}\"*")
            except Exception as e:
                st.error(f"Connection failed: {e}")

    st.divider()

    # ── Danger zone ───────────────────────────────────────────────────────────
    with st.expander("⚠️ Danger Zone"):
        st.warning(
            "These actions are irreversible. Use with caution."
        )
        col1, col2 = st.columns(2)
        if col1.button("Clear All Transcriptions", use_container_width=True):
            from data_store import TRANSCRIPTIONS_DIR
            count = 0
            for f in TRANSCRIPTIONS_DIR.glob("*.json"):
                f.unlink()
                count += 1
            st.success(f"Deleted {count} transcription file(s).")
            st.rerun()

        if col2.button("Clear All Uploads", use_container_width=True):
            from data_store import UPLOADS_DIR, IMAGE_EXTENSIONS
            count = 0
            for f in UPLOADS_DIR.iterdir():
                if f.suffix.lower() in IMAGE_EXTENSIONS:
                    f.unlink()
                    count += 1
            st.success(f"Deleted {count} uploaded image(s).")
            st.rerun()
