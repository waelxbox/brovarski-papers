"""
pages/settings.py  –  API key, model, and app configuration
"""

import os
import streamlit as st
from transcribe_engine import DEFAULT_MODEL, build_client


AVAILABLE_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-pro",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "claude-3-7-sonnet-20250219",
    "claude-3-5-sonnet-20241022",
    "gpt-4o",
    "gpt-4o-mini",
]

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
OPENAI_BASE_URL = "https://api.openai.com/v1"
CLAUDE_BASE_URL = "https://api.anthropic.com/v1/"


def _detect_provider(base_url: str) -> str:
    if "anthropic" in base_url:
        return "Anthropic Claude"
    if "openai.com" in base_url:
        return "OpenAI"
    return "Google Gemini (recommended)"


def render():
    st.title("Settings")
    st.caption("Configure your API credentials and transcription preferences.")
    st.divider()

    # ── API Configuration ─────────────────────────────────────────────────────
    st.subheader("API Configuration")

    current_url = st.session_state.get("base_url", GEMINI_BASE_URL)
    provider_default = _detect_provider(current_url)
    provider_options = ["Google Gemini (recommended)", "Anthropic Claude", "OpenAI"]

    api_provider = st.radio(
        "API Provider",
        provider_options,
        index=provider_options.index(provider_default),
        horizontal=True,
    )

    if api_provider == "Google Gemini (recommended)":
        st.info(
            "Get a free Gemini API key at "
            "[aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey). "
            "Processing 10,000 cards costs approximately $5–15 with Gemini Flash."
        )
        default_url = GEMINI_BASE_URL
    elif api_provider == "Anthropic Claude":
        st.info(
            "Get a Claude API key at "
            "[console.anthropic.com](https://console.anthropic.com). "
            "Claude 3.5 Sonnet is the most accurate model for handwritten academic text."
        )
        default_url = CLAUDE_BASE_URL
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
            "**gemini-2.5-pro** — Slower, best for difficult handwriting. "
            "**claude-3-5-sonnet** — Best overall accuracy on messy handwriting. "
            "**gpt-4o** — OpenAI alternative."
        ),
    )

    model_info = {
        "gemini-3.1-pro-preview":     ("Slow",   "~$0.012/card",  "Most advanced reasoning (Preview)"),
        "gemini-3-flash-preview":     ("Medium", "~$0.003/card",  "Pro-level intelligence at Flash speed"),
        "gemini-2.5-pro":             ("Slow",   "~$0.01/card",   "Best for difficult handwriting"),
        "gemini-2.5-flash":           ("Fast",   "~$0.001/card",  "Best for most cards"),
        "gemini-2.0-flash":           ("Fast",   "~$0.001/card",  "Previous generation Gemini"),
        "claude-3-7-sonnet-20250219": ("Medium", "~$0.004/card",  "Latest Claude, highest accuracy"),
        "claude-3-5-sonnet-20241022": ("Medium", "~$0.003/card",  "Best handwriting accuracy"),
        "gpt-4o":                     ("Medium", "~$0.005/card",  "OpenAI alternative"),
        "gpt-4o-mini":                ("Fast",   "~$0.0005/card", "OpenAI budget option"),
    }
    if model in model_info:
        speed, cost, note = model_info[model]
        col1, col2, col3 = st.columns(3)
        col1.metric("Speed", speed)
        col2.metric("Est. Cost", cost)
        col3.metric("Best For", note)

    st.divider()

    # ── Save + Test (combined — one click, always reliable) ───────────────────
    st.subheader("Save & Test Connection")
    st.markdown(
        "Click **Save & Test Connection** to save your settings and verify the API key "
        "in a single step. Or click **Save Settings** alone if you do not want to test."
    )

    col_save, col_test = st.columns(2)

    if col_save.button("Save Settings", use_container_width=True):
        st.session_state["api_key"]  = api_key
        st.session_state["base_url"] = base_url or default_url
        st.session_state["model"]    = model
        st.success("Settings saved.")

    if col_test.button("Save & Test Connection", use_container_width=True, type="primary"):
        # Commit current form values to session state BEFORE testing
        st.session_state["api_key"]  = api_key
        st.session_state["base_url"] = base_url or default_url
        st.session_state["model"]    = model

        key_to_test   = st.session_state["api_key"]
        url_to_test   = st.session_state["base_url"]
        model_to_test = st.session_state["model"]

        if not key_to_test:
            st.error("Please enter an API key first.")
        else:
            with st.spinner(f"Testing connection to {model_to_test}…"):
                try:
                    client = build_client(api_key=key_to_test, base_url=url_to_test)
                    response = client.chat.completions.create(
                        model=model_to_test,
                        messages=[{"role": "user", "content": "Reply with the single word: connected"}],
                        max_tokens=10,
                        temperature=0,
                    )
                    content = response.choices[0].message.content
                    if content is None:
                        # Gemini sometimes returns None on the test ping — the
                        # connection itself succeeded if we got a 200 response.
                        st.success("Connection successful! (Model returned an empty ping response — this is normal for Gemini.)")
                    else:
                        reply = content.strip().lower()
                        if "connect" in reply or len(reply) < 50:
                            st.success(f"Connection successful! Model replied: *\"{reply}\"*")
                        else:
                            st.warning(f"Connected, but unexpected reply: *\"{reply}\"*")
                except Exception as e:
                    st.error(
                        f"Connection failed: {e}\n\n"
                        "Check that your API key is correct and the Base URL matches your provider."
                    )

    st.divider()

    # ── Danger zone ───────────────────────────────────────────────────────────
    with st.expander("Danger Zone"):
        st.warning("These actions are irreversible. Use with caution.")
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
