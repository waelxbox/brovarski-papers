"""
pages/review.py  –  Human-in-the-Loop correction interface
"""

from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from data_store import (
    list_cards, load_json, save_json, append_to_csv,
    list_to_str, str_to_list,
    STATUS_PENDING, STATUS_REVIEWED, STATUS_FLAGGED, STATUS_ERROR,
    EDITABLE_FIELDS,
)


# ── Filter helpers ────────────────────────────────────────────────────────────

FILTER_OPTIONS = [
    "Pending only",
    "All",
    "Reviewed only",
    "Flagged only",
    "With hieroglyphs",
    "Errors only",
]


def _apply_filter(cards: list, filter_opt: str) -> list:
    if filter_opt == "Pending only":
        return [c for c in cards if c["status"] == STATUS_PENDING]
    if filter_opt == "Reviewed only":
        return [c for c in cards if c["status"] == STATUS_REVIEWED]
    if filter_opt == "Flagged only":
        return [c for c in cards if c["status"] == STATUS_FLAGGED]
    if filter_opt == "With hieroglyphs":
        return [c for c in cards if c["has_hieroglyphs"]]
    if filter_opt == "Errors only":
        return [c for c in cards if c["status"] == STATUS_ERROR]
    return cards  # "All"


# ── Main render ───────────────────────────────────────────────────────────────

def render():
    st.title("Review Cards")
    st.caption(
        "Compare the original scan with the AI transcription. "
        "Correct any errors and click **Save & Next** to advance."
    )

    all_cards = list_cards()
    transcribed = [c for c in all_cards if c["has_json"]]

    if not transcribed:
        st.info(
            "No transcribed cards found. "
            "Go to **Upload & Transcribe** to process your scanned images first."
        )
        if st.button("Go to Upload & Transcribe →", type="primary"):
            st.session_state["active_page"] = "Upload & Transcribe"
            st.rerun()
        return

    # ── Filter controls ───────────────────────────────────────────────────────
    filter_col, jump_col = st.columns([2, 3])

    with filter_col:
        filter_opt = st.selectbox(
            "Show cards",
            FILTER_OPTIONS,
            index=FILTER_OPTIONS.index(
                st.session_state.get("review_filter", "Pending only")
            ),
        )
        st.session_state["review_filter"] = filter_opt

    filtered = _apply_filter(transcribed, filter_opt)

    if not filtered:
        st.info(f"No cards match the filter: **{filter_opt}**.")
        return

    # ── Card index management ─────────────────────────────────────────────────
    if "review_index" not in st.session_state:
        st.session_state["review_index"] = 0

    idx = st.session_state["review_index"]
    idx = max(0, min(idx, len(filtered) - 1))

    card_names = [c["name"] for c in filtered]

    with jump_col:
        selected_name = st.selectbox(
            f"Jump to card ({len(filtered)} in view)",
            card_names,
            index=idx,
        )
        idx = card_names.index(selected_name)
        st.session_state["review_index"] = idx

    st.divider()

    # ── Load current card ─────────────────────────────────────────────────────
    card = filtered[idx]
    data = load_json(card["json_path"])
    status = data.get("_review_status", STATUS_PENDING)

    # Status badge
    badge_map = {
        STATUS_PENDING:  "🟡 Pending",
        STATUS_REVIEWED: "✅ Reviewed",
        STATUS_FLAGGED:  "🚩 Flagged for expert",
        STATUS_ERROR:    "❌ Transcription error",
    }
    badge = badge_map.get(status, "🟡 Pending")

    st.markdown(
        f"**Card {idx + 1} of {len(filtered)}** &nbsp;|&nbsp; "
        f"{badge} &nbsp;|&nbsp; "
        f"Model: `{data.get('_model', 'unknown')}`"
    )

    # Hieroglyph warning banner
    if data.get("Hieroglyphs_Present"):
        st.warning(
            "**⚠️ Hieroglyphs Detected** — This card contains hand-drawn hieroglyphs "
            "marked with `[HIEROGLYPHS_PRESENT]`. Manual encoding by a specialist is required.",
            icon="𓀀",
        )

    # Error banner
    if "error" in data:
        st.error(
            f"**Transcription Error:** {data['error']}\n\n"
            "You can still manually enter the transcription in the fields below, "
            "or go to **Upload & Transcribe** to retry."
        )

    st.divider()

    # ── Two-column layout ─────────────────────────────────────────────────────
    left_col, right_col = st.columns([1, 1], gap="large")

    with left_col:
        st.subheader("Original Scan")
        try:
            st.image(str(card["image_path"]), use_container_width=True)
        except Exception as e:
            st.error(f"Cannot display image: {e}")

        with st.expander("Raw JSON (read-only)"):
            st.json(data)

    with right_col:
        st.subheader("AI Transcription — Edit to Correct")

        edited: dict = {}

        # Subject Heading
        edited["Subject_Heading"] = st.text_input(
            "Subject Heading",
            value=data.get("Subject_Heading") or "",
            help="The main topic or person's name on the card header.",
        )

        # List fields
        for field in ("Museum_References", "Object_Types", "Egyptian_Titles"):
            edited[field] = str_to_list(
                st.text_area(
                    field.replace("_", " "),
                    value=list_to_str(data.get(field)),
                    height=90,
                    help="One entry per line.",
                )
            )

        # Full transcription
        edited["Full_Transcription"] = st.text_area(
            "Full Transcription",
            value=data.get("Full_Transcription") or "",
            height=240,
            help=(
                "Complete verbatim text of the card. "
                "Keep [HIEROGLYPHS_PRESENT] tags where hieroglyphs appear."
            ),
        )

        # Confidence notes
        edited["Confidence_Notes"] = st.text_area(
            "Confidence Notes",
            value=data.get("Confidence_Notes") or "",
            height=70,
            help="Note any uncertain readings here.",
        )

        # Hieroglyphs checkbox
        edited["Hieroglyphs_Present"] = st.checkbox(
            "Hieroglyphs present on this card",
            value=bool(data.get("Hieroglyphs_Present", False)),
        )

        st.divider()

        # ── Action buttons ────────────────────────────────────────────────────
        b1, b2, b3, b4 = st.columns(4)

        save_clicked = b1.button("💾 Save & Next", type="primary", use_container_width=True)
        flag_clicked = b2.button("🚩 Flag for Expert", use_container_width=True)
        prev_clicked = b3.button("← Previous", use_container_width=True, disabled=(idx == 0))
        skip_clicked = b4.button("Skip →", use_container_width=True, disabled=(idx >= len(filtered) - 1))

        # Save / Flag
        if save_clicked or flag_clicked:
            new_status = STATUS_FLAGGED if flag_clicked else STATUS_REVIEWED
            updated = {
                **data,
                **edited,
                "_review_status": new_status,
                "_reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
            save_json(card["json_path"], updated)
            append_to_csv(card["name"], updated)

            action_word = "Flagged" if flag_clicked else "Saved"
            st.success(f"**{action_word}!** Card {idx + 1} of {len(filtered)}.")

            if idx < len(filtered) - 1:
                st.session_state["review_index"] = idx + 1
                st.rerun()
            else:
                st.balloons()
                st.info("🎉 You have reached the last card in this filter!")

        if prev_clicked and idx > 0:
            st.session_state["review_index"] = idx - 1
            st.rerun()

        if skip_clicked and idx < len(filtered) - 1:
            st.session_state["review_index"] = idx + 1
            st.rerun()

    # ── Navigation strip ──────────────────────────────────────────────────────
    st.divider()
    nav_cols = st.columns(min(len(filtered), 20))
    for i, col in enumerate(nav_cols):
        c = filtered[i]
        icon = {
            STATUS_PENDING:  "🟡",
            STATUS_REVIEWED: "✅",
            STATUS_FLAGGED:  "🚩",
            STATUS_ERROR:    "❌",
        }.get(c["status"], "⬜")
        if col.button(icon, key=f"nav_{i}", help=c["name"]):
            st.session_state["review_index"] = i
            st.rerun()
