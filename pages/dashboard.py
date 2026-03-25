"""
pages/dashboard.py  –  Overview metrics and project status
"""

import streamlit as st
from data_store import (
    list_cards, count_by_status,
    STATUS_PENDING, STATUS_REVIEWED, STATUS_FLAGGED, STATUS_ERROR,
)


def render():
    st.title("𓂀 Brovarski Papers — Dashboard")
    st.caption("AI Transcription & Human Review Platform for the Brovarski Egyptology Archive")
    st.divider()

    counts = count_by_status()
    total        = counts["total"]
    not_trans    = counts["not_transcribed"]
    pending      = counts[STATUS_PENDING]
    reviewed     = counts[STATUS_REVIEWED]
    flagged      = counts[STATUS_FLAGGED]
    errors       = counts[STATUS_ERROR]
    done         = reviewed + flagged

    # ── Top metrics ───────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total Cards", total)
    c2.metric("Transcribed", total - not_trans, delta=None)
    c3.metric("Reviewed ✅", reviewed)
    c4.metric("Flagged 🚩", flagged, help="Cards flagged for expert attention (e.g. hieroglyphs)")
    c5.metric("Errors ⚠️", errors, help="Cards where AI transcription failed")

    # ── Progress bar ──────────────────────────────────────────────────────────
    st.divider()
    if total > 0:
        pct = done / total
        st.markdown(f"### Overall Progress — {done} of {total} cards reviewed ({pct:.0%})")
        st.progress(pct)
    else:
        st.info("No cards uploaded yet. Go to **Upload & Transcribe** to get started.")
        return

    st.divider()

    # ── Status breakdown ──────────────────────────────────────────────────────
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Status Breakdown")
        status_data = {
            "Not transcribed": not_trans,
            "Pending review":  pending,
            "Reviewed":        reviewed,
            "Flagged":         flagged,
            "Errors":          errors,
        }
        for label, count in status_data.items():
            bar_pct = count / total if total else 0
            col_a, col_b = st.columns([3, 1])
            col_a.progress(bar_pct, text=label)
            col_b.markdown(f"**{count}**")

    with col_right:
        st.subheader("Quick Actions")
        if not_trans > 0:
            st.warning(f"**{not_trans}** card(s) have been uploaded but not yet transcribed.")
            if st.button("Go to Upload & Transcribe →", use_container_width=True, type="primary"):
                st.session_state["active_page"] = "Upload & Transcribe"
                st.rerun()

        if pending > 0:
            st.info(f"**{pending}** card(s) are transcribed and waiting for review.")
            if st.button("Go to Review Cards →", use_container_width=True):
                st.session_state["active_page"] = "Review Cards"
                st.rerun()

        if flagged > 0:
            st.warning(f"**{flagged}** card(s) are flagged for expert attention.")
            if st.button("Review Flagged Cards →", use_container_width=True):
                st.session_state["active_page"] = "Review Cards"
                st.session_state["review_filter"] = "Flagged only"
                st.rerun()

        if done > 0:
            if st.button("Export Reviewed Data →", use_container_width=True):
                st.session_state["active_page"] = "Export Data"
                st.rerun()

    # ── Recent cards table ────────────────────────────────────────────────────
    st.divider()
    st.subheader("Recent Cards")

    cards = list_cards()
    if not cards:
        st.info("No cards found.")
        return

    # Show last 10
    recent = cards[-10:][::-1]
    rows = []
    for c in recent:
        status_icon = {
            "not_transcribed": "⬜ Not transcribed",
            STATUS_PENDING:    "🟡 Pending",
            STATUS_REVIEWED:   "✅ Reviewed",
            STATUS_FLAGGED:    "🚩 Flagged",
            STATUS_ERROR:      "❌ Error",
        }.get(c["status"], c["status"])
        rows.append({
            "Card": c["name"],
            "Status": status_icon,
            "Hieroglyphs": "Yes" if c["has_hieroglyphs"] else "—",
        })

    st.table(rows)
