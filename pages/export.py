# pages/export.py

import json
import zipfile
import io

import streamlit as st

from data_store import (
    list_cards, load_json, rebuild_csv, get_image_bytes,
    STATUS_REVIEWED, STATUS_FLAGGED,
)

def render():
    st.title("Export Data")
    st.caption("Download your reviewed transcriptions as CSV or JSON for use in databases, spreadsheets, or the next pipeline stage.")
    st.divider()

    cards = list_cards()
    reviewed_cards = [c for c in cards if c["status"] in (STATUS_REVIEWED, STATUS_FLAGGED)]

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Cards", len(cards))
    c2.metric("Ready to Export", len(reviewed_cards))
    c3.metric("Still Pending", len(cards) - len(reviewed_cards))

    if not reviewed_cards:
        st.info("No reviewed cards to export yet. Complete some reviews first.")
        return

    st.divider()

    st.subheader("CSV Export")
    st.markdown("A flat CSV file containing all reviewed cards. Ideal for importing into Excel, Google Sheets, or a relational database.")
    if st.button("Rebuild & Download CSV", type="primary"):
        csv_path = rebuild_csv()
        st.download_button(
            label="⬇️ Download corrections_export.csv",
            data=csv_path.read_bytes(),
            file_name="brovarski_corrections_export.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.divider()

    st.subheader("JSON Export")
    st.markdown("A single JSON file containing all reviewed cards as a list of objects. Ideal for loading into a vector database or custom application.")
    if st.button("Build & Download JSON"):
        all_data = []
        for c in reviewed_cards:
            data = load_json(c)
            data["_image_filename"] = c["name"]
            all_data.append(data)
        json_bytes = json.dumps(all_data, ensure_ascii=False, indent=2).encode("utf-8")
        st.download_button(
            label="⬇️ Download brovarski_archive.json",
            data=json_bytes,
            file_name="brovarski_archive.json",
            mime="application/json",
            use_container_width=True,
        )

    st.divider()

    st.subheader("Full Archive ZIP")
    st.markdown("A ZIP file containing every reviewed JSON file alongside its original scanned image. This is the complete, self-contained archive package.")
    if st.button("Build & Download Full Archive ZIP"):
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for c in reviewed_cards:
                zf.writestr(f"images/{c['name']}", get_image_bytes(c))
                json_data = load_json(c)
                if json_data:
                    zf.writestr(f"json/{c['stem']}.json", json.dumps(json_data, indent=2))
            csv_path = rebuild_csv()
            if csv_path.exists():
                zf.write(csv_path, arcname="corrections_export.csv")
        zip_buffer.seek(0)
        st.download_button(
            label="⬇️ Download brovarski_archive.zip",
            data=zip_buffer,
            file_name="brovarski_archive.zip",
            mime="application/zip",
            use_container_width=True,
        )

    st.divider()

    st.subheader("Preview of Reviewed Cards")
    rows = []
    for c in reviewed_cards:
        data = load_json(c)
        rows.append({
            "Image": c["name"],
            "Subject Heading": data.get("Subject_Heading") or "—",
            "Status": "🚩 Flagged" if c["status"] == STATUS_FLAGGED else "✅ Reviewed",
            "Hieroglyphs": "⚠️ Yes" if c.get("has_hieroglyphs") else "—",
            "Museum Refs": len(data.get("Museum_References") or []),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)
