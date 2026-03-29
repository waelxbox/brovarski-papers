# pages/upload.py

import json
import streamlit as st
from data_store import (
    list_cards, save_uploaded_file, get_image_bytes, save_json,
    STATUS_PENDING, STATUS_REVIEWED, STATUS_FLAGGED, STATUS_ERROR,
    UPLOADS_DIR, TRANSCRIPTIONS_DIR,
)
from transcribe_engine import build_client, transcribe_image, DEFAULT_MODEL


def _get_client():
    key = st.session_state.get("api_key", "")
    url = st.session_state.get("base_url", "")
    if not key:
        return None
    return build_client(api_key=key, base_url=url or None)


def render():
    st.title("Upload & Transcribe")
    st.caption(
        "Upload scanned index-card images. Each image is automatically sent to "
        "the Gemini AI for transcription and placed in the review queue."
    )
    st.divider()

    # ── TAB LAYOUT ───────────────────────────────────────────────────────────
    tab1, tab2 = st.tabs(["🖼️ Upload & Transcribe (live)", "📦 Import Batch Results"])

    # ════════════════════════════════════════════════════════════════════════
    # TAB 1 — original live upload + transcribe flow
    # ════════════════════════════════════════════════════════════════════════
    with tab1:
        if not st.session_state.get("api_key"):
            st.error(
                "No API key configured. Please go to **Settings** and enter your "
                "Gemini API key before uploading cards."
            )
            if st.button("Go to Settings"):
                st.session_state["active_page"] = "Settings"
                st.rerun()
        else:
            st.subheader("1. Upload Images")
            uploaded_files = st.file_uploader(
                "Drag and drop scanned card images here, or click to browse",
                type=["jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"],
                accept_multiple_files=True,
                key="live_uploader",
            )
            model = st.session_state.get("model", DEFAULT_MODEL)
            skip_existing = st.checkbox("Skip cards that have already been transcribed", value=True)

            if uploaded_files:
                st.info(f"**{len(uploaded_files)}** file(s) selected. Click the button below to save and transcribe.")
                if st.button("Save & Transcribe All", type="primary", use_container_width=True):
                    client = _get_client()
                    if client is None:
                        st.error("API client could not be created. Check your API key in Settings.")
                    else:
                        for uf in uploaded_files:
                            save_uploaded_file(uf)
                        st.success(f"Saved {len(uploaded_files)} image(s) to storage.")
                        st.divider()

                        st.subheader("2. AI Transcription in Progress")
                        progress_bar = st.progress(0)
                        status_area = st.empty()
                        log_area = st.empty()
                        log_lines = []

                        cards_to_process = list_cards()
                        total = len(cards_to_process)
                        if total == 0:
                            st.warning("No cards found in storage after upload. Please try again.")
                        else:
                            for i, card in enumerate(cards_to_process):
                                if skip_existing and card["has_json"]:
                                    log_lines.append(f"⏭️ Skipped (already done): **{card['name']}**")
                                    log_area.markdown("\n\n".join(log_lines))
                                    progress_bar.progress((i + 1) / total)
                                    continue

                                status_area.info(f"Transcribing **{card['name']}** ({i + 1}/{total})…")
                                try:
                                    image_bytes = get_image_bytes(card)
                                    if not image_bytes:
                                        log_lines.append(f"⚠️ Could not read image: **{card['name']}**")
                                        log_area.markdown("\n\n".join(log_lines))
                                        progress_bar.progress((i + 1) / total)
                                        continue

                                    result = transcribe_image(
                                        image_bytes, client, model=model, filename=card["name"]
                                    )
                                    save_json(card["stem"], result)

                                    if "error" in result:
                                        log_lines.append(f"❌ Error on **{card['name']}**: {result['error']}")
                                    elif result.get("Hieroglyphs_Present"):
                                        log_lines.append(f"✅ Done: **{card['name']}** — ⚠️ Hieroglyphs detected")
                                    else:
                                        heading = result.get("Subject_Heading") or "(no heading)"
                                        log_lines.append(f"✅ Done: **{card['name']}** — *{heading}*")

                                except Exception as exc:
                                    log_lines.append(f"❌ Unexpected error on **{card['name']}**: {exc}")

                                log_area.markdown("\n\n".join(log_lines))
                                progress_bar.progress((i + 1) / total)

                            status_area.success("All cards processed! They are now in the review queue.")
                            st.balloons()
                            if st.button("Go to Review Cards →", type="primary"):
                                st.session_state["active_page"] = "Review Cards"
                                st.rerun()

        # Card table
        st.divider()
        st.subheader("Uploaded Cards")
        cards = list_cards()
        if not cards:
            st.info("No cards uploaded yet.")
        else:
            model = st.session_state.get("model", DEFAULT_MODEL)
            col1, col2 = st.columns([3, 1])
            with col2:
                if st.button("Re-transcribe All Errors", use_container_width=True):
                    client = _get_client()
                    if client:
                        error_cards = [c for c in cards if c["status"] == STATUS_ERROR]
                        if error_cards:
                            with st.spinner(f"Re-transcribing {len(error_cards)} error card(s)…"):
                                for c in error_cards:
                                    try:
                                        image_bytes = get_image_bytes(c)
                                        result = transcribe_image(
                                            image_bytes, client, model=model, filename=c["name"]
                                        )
                                        save_json(c["stem"], result)
                                    except Exception as exc:
                                        st.warning(f"Error retranscribing {c['name']}: {exc}")
                            st.success("Done. Refresh to see updated statuses.")
                            st.rerun()
                        else:
                            st.info("No error cards to retry.")

            status_label = {
                "not_transcribed": "⬜ Not transcribed",
                STATUS_PENDING:    "🟡 Pending review",
                STATUS_REVIEWED:   "✅ Reviewed",
                STATUS_FLAGGED:    "🚩 Flagged",
                STATUS_ERROR:      "❌ Error",
            }
            rows = []
            for c in cards:
                rows.append({
                    "Image":       c["name"],
                    "Status":      status_label.get(c["status"], c["status"]),
                    "Hieroglyphs": "⚠️ Yes" if c["has_hieroglyphs"] else "—",
                    "JSON":        "✓" if c["has_json"] else "✗",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

            st.divider()
            st.subheader("Retranscribe a Single Card")
            selected = st.selectbox("Select card to retranscribe", [c["name"] for c in cards])
            if st.button("Retranscribe Selected Card"):
                client = _get_client()
                if client:
                    card = next(c for c in cards if c["name"] == selected)
                    with st.spinner(f"Transcribing {selected}…"):
                        try:
                            image_bytes = get_image_bytes(card)
                            result = transcribe_image(
                                image_bytes, client, model=model, filename=card["name"]
                            )
                            save_json(card["stem"], result)
                            if "error" in result:
                                st.error(f"Transcription failed: {result['error']}")
                            else:
                                st.success(f"Done! **{selected}** has been transcribed and is ready for review.")
                                st.rerun()
                        except Exception as exc:
                            st.error(f"Unexpected error: {exc}")

    # ════════════════════════════════════════════════════════════════════════
    # TAB 2 — Import batch results (JSON + images) produced by local script
    # ════════════════════════════════════════════════════════════════════════
    with tab2:
        st.subheader("Import Batch Results from Local Script")
        st.markdown(
            """
Use this tab when you have already run the **local batch transcription script** on your Mac
and want to bring the results into the app for review.

**What to upload:**
- **Step A** — Upload all the `.json` files from your local `data/transcriptions/` folder.
- **Step B** — Upload the corresponding scanned image files (`.jpg`, `.png`, etc.).

Both steps are needed so the Review page can show the image alongside the transcription.
You can do them in either order or at the same time.
            """
        )
        st.divider()

        # ── Step A: Upload JSON files ────────────────────────────────────────
        st.markdown("### Step A — Upload Transcription JSON Files")
        json_files = st.file_uploader(
            "Select all `.json` files from your local `data/transcriptions/` folder",
            type=["json"],
            accept_multiple_files=True,
            key="batch_json_uploader",
        )

        if json_files:
            if st.button(f"Import {len(json_files)} JSON file(s)", type="primary", use_container_width=True, key="import_json_btn"):
                ok = 0
                errors = []
                for jf in json_files:
                    try:
                        raw = jf.read().decode("utf-8")
                        data = json.loads(raw)
                        stem = jf.name.replace(".json", "")
                        # Ensure the card gets a pending status if not already reviewed
                        if "_review_status" not in data:
                            data["_review_status"] = STATUS_PENDING
                        save_json(stem, data)
                        ok += 1
                    except Exception as exc:
                        errors.append(f"❌ `{jf.name}`: {exc}")

                if ok:
                    st.success(f"✅ Imported **{ok}** JSON file(s) successfully.")
                for e in errors:
                    st.warning(e)
                st.rerun()

        # ── Step B: Upload image files ───────────────────────────────────────
        st.divider()
        st.markdown("### Step B — Upload Scanned Image Files")
        st.caption(
            "Upload the original scan images. The filenames must match the JSON files "
            "(e.g. `card_001.jpg` matches `card_001.json`)."
        )
        image_files = st.file_uploader(
            "Select scanned card images",
            type=["jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp"],
            accept_multiple_files=True,
            key="batch_image_uploader",
        )

        if image_files:
            if st.button(f"Import {len(image_files)} image(s)", type="primary", use_container_width=True, key="import_img_btn"):
                ok = 0
                errors = []
                for img in image_files:
                    try:
                        save_uploaded_file(img)
                        ok += 1
                    except Exception as exc:
                        errors.append(f"❌ `{img.name}`: {exc}")

                if ok:
                    st.success(f"✅ Imported **{ok}** image(s) successfully.")
                for e in errors:
                    st.warning(e)
                st.rerun()

        # ── Current import status ────────────────────────────────────────────
        st.divider()
        st.markdown("### Current Import Status")
        cards = list_cards()

        # Count JSON-only cards (no matching image) and image-only cards
        json_only = [c for c in cards if c["has_json"] and not c.get("image_path", c.get("image_id"))]
        img_only  = [c for c in cards if not c["has_json"]]
        paired    = [c for c in cards if c["has_json"]]

        col1, col2, col3 = st.columns(3)
        col1.metric("Cards with transcription", len(paired))
        col2.metric("Cards without transcription", len(img_only))
        col3.metric("Total cards in system", len(cards))

        if paired:
            st.success(
                f"**{len(paired)}** card(s) are ready for review. "
                "Go to **Review Cards** to start."
            )
            if st.button("Go to Review Cards →", type="primary", key="goto_review_btn"):
                st.session_state["active_page"] = "Review Cards"
                st.rerun()

        if cards:
            status_label = {
                "not_transcribed": "⬜ Not transcribed",
                STATUS_PENDING:    "🟡 Pending review",
                STATUS_REVIEWED:   "✅ Reviewed",
                STATUS_FLAGGED:    "🚩 Flagged",
                STATUS_ERROR:      "❌ Error",
            }
            rows = []
            for c in cards:
                rows.append({
                    "Image":       c["name"],
                    "Status":      status_label.get(c["status"], c["status"]),
                    "Has JSON":    "✓" if c["has_json"] else "✗",
                    "Hieroglyphs": "⚠️ Yes" if c["has_hieroglyphs"] else "—",
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)
