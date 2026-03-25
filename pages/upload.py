"""
pages/upload.py  –  Upload card images and trigger automatic AI transcription
"""

import shutil
import time
from pathlib import Path

import streamlit as st

from data_store import (
    UPLOADS_DIR, TRANSCRIPTIONS_DIR,
    list_cards, load_json, save_json,
    IMAGE_EXTENSIONS, STATUS_PENDING,
)
from transcribe_engine import build_client, transcribe_image, DEFAULT_MODEL


def _get_client():
    """Build the API client from session state credentials."""
    key = st.session_state.get("api_key", "")
    url = st.session_state.get("base_url", "")
    if not key:
        return None
    return build_client(api_key=key, base_url=url or None)


def render():
    st.title("Upload & Transcribe")
    st.caption(
        "Upload scanned index-card images. Each image is automatically sent to the "
        "Gemini AI for transcription and placed in the review queue."
    )
    st.divider()

    # ── API key check ─────────────────────────────────────────────────────────
    if not st.session_state.get("api_key"):
        st.error(
            "No API key configured. Please go to **Settings** and enter your "
            "Gemini API key before uploading cards."
        )
        if st.button("Go to Settings"):
            st.session_state["active_page"] = "Settings"
            st.rerun()
        return

    # ── Upload widget ─────────────────────────────────────────────────────────
    st.subheader("1. Upload Images")
    uploaded_files = st.file_uploader(
        "Drag and drop scanned card images here, or click to browse",
        type=["jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"],
        accept_multiple_files=True,
        help="Supports JPG, PNG, TIFF, BMP, and WebP formats.",
    )

    model = st.session_state.get("model", DEFAULT_MODEL)
    skip_existing = st.checkbox(
        "Skip cards that have already been transcribed",
        value=True,
        help="Uncheck to re-transcribe cards even if a JSON file already exists.",
    )

    if uploaded_files:
        st.info(f"**{len(uploaded_files)}** file(s) selected. Click the button below to save and transcribe.")

        if st.button("Save & Transcribe All", type="primary", use_container_width=True):
            client = _get_client()
            if client is None:
                st.error("API client could not be created. Check your API key in Settings.")
                return

            # Save all uploaded files first
            saved_paths = []
            for uf in uploaded_files:
                dest = UPLOADS_DIR / uf.name
                with open(dest, "wb") as f:
                    f.write(uf.getbuffer())
                saved_paths.append(dest)

            st.success(f"Saved {len(saved_paths)} image(s) to the uploads folder.")
            st.divider()

            # ── Transcription pipeline ────────────────────────────────────────
            st.subheader("2. AI Transcription in Progress")
            progress_bar = st.progress(0)
            status_area  = st.empty()
            log_area     = st.empty()
            log_lines    = []

            total = len(saved_paths)
            for i, img_path in enumerate(saved_paths):
                json_path = TRANSCRIPTIONS_DIR / (img_path.stem + ".json")

                if skip_existing and json_path.exists():
                    log_lines.append(f"⏭️  Skipped (already done): **{img_path.name}**")
                    log_area.markdown("\n\n".join(log_lines))
                    progress_bar.progress((i + 1) / total)
                    continue

                status_area.info(f"Transcribing **{img_path.name}** ({i+1}/{total})…")

                result = transcribe_image(img_path, client, model=model)
                save_json(json_path, result)

                if "error" in result:
                    log_lines.append(f"❌ Error on **{img_path.name}**: {result['error']}")
                elif result.get("Hieroglyphs_Present"):
                    log_lines.append(f"✅ Done: **{img_path.name}** — ⚠️ Hieroglyphs detected")
                else:
                    subject = result.get("Subject_Heading") or "(no heading)"
                    log_lines.append(f"✅ Done: **{img_path.name}** — *{subject}*")

                log_area.markdown("\n\n".join(log_lines))
                progress_bar.progress((i + 1) / total)

            status_area.success("All cards transcribed! They are now in the review queue.")
            st.balloons()

            if st.button("Go to Review Cards →", type="primary"):
                st.session_state["active_page"] = "Review Cards"
                st.rerun()

    # ── Existing uploads table ────────────────────────────────────────────────
    st.divider()
    st.subheader("Uploaded Cards")

    cards = list_cards()
    if not cards:
        st.info("No cards uploaded yet.")
        return

    # Retranscribe controls
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Re-transcribe All Errors", use_container_width=True):
            client = _get_client()
            if client:
                error_cards = [c for c in cards if c["status"] == "error"]
                if error_cards:
                    with st.spinner(f"Re-transcribing {len(error_cards)} error card(s)…"):
                        for c in error_cards:
                            result = transcribe_image(c["image_path"], client, model=model)
                            save_json(c["json_path"], result)
                    st.success("Done. Refresh to see updated statuses.")
                    st.rerun()
                else:
                    st.info("No error cards to retry.")

    # Table
    rows = []
    for c in cards:
        status_icon = {
            "not_transcribed": "⬜ Not transcribed",
            STATUS_PENDING:    "🟡 Pending review",
            "reviewed":        "✅ Reviewed",
            "flagged":         "🚩 Flagged",
            "error":           "❌ Error",
        }.get(c["status"], c["status"])

        rows.append({
            "Image": c["name"],
            "Status": status_icon,
            "Hieroglyphs": "⚠️ Yes" if c["has_hieroglyphs"] else "—",
            "JSON": "✓" if c["has_json"] else "✗",
        })

    st.dataframe(rows, use_container_width=True, hide_index=True)

    # Per-card retranscribe
    st.divider()
    st.subheader("Retranscribe a Single Card")
    card_names = [c["name"] for c in cards]
    selected = st.selectbox("Select card to retranscribe", card_names)
    if st.button("Retranscribe Selected Card"):
        client = _get_client()
        if client:
            card = next(c for c in cards if c["name"] == selected)
            with st.spinner(f"Transcribing {selected}…"):
                result = transcribe_image(card["image_path"], client, model=model)
                save_json(card["json_path"], result)
            if "error" in result:
                st.error(f"Transcription failed: {result['error']}")
            else:
                st.success(f"Done! **{selected}** has been transcribed and is ready for review.")
                st.rerun()
