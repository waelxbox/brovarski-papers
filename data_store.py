# data_store.py
# =============
# Centralised helpers for reading/writing data. Abstracts local vs Google Drive storage.

import csv
import json
import io
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

# --- Paths & Constants ---
DATA_DIR = Path(__file__).parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
TRANSCRIPTIONS_DIR = DATA_DIR / "transcriptions"
EXPORT_CSV = DATA_DIR / "corrections_export.csv"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}
STATUS_PENDING = "pending"
STATUS_REVIEWED = "reviewed"
STATUS_FLAGGED = "flagged"
STATUS_ERROR = "error"
EDITABLE_FIELDS = [
    "Subject_Heading", "Museum_References", "Object_Types",
    "Egyptian_Titles", "Full_Transcription", "Confidence_Notes"
]
CSV_FIELDNAMES = ["image", "reviewed_at", "status"] + EDITABLE_FIELDS + ["Hieroglyphs_Present"]

# Ensure local dirs exist (used as fallback and for CSV export)
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- Backend helper ---

def _get_backend():
    """
    Return a GDriveStore if credentials are available, else None (local mode).
    Priority:
      1. Streamlit Secrets [gdrive] section (permanent, survives restarts)
      2. Session-state gdrive_creds (set during first-time OAuth flow)
    """
    from gdrive_store import load_credentials_from_secrets, GDriveStore

    # Try Secrets first (permanent connection)
    try:
        creds = load_credentials_from_secrets()
        if creds is not None:
            return GDriveStore()
    except Exception:
        pass

    # Fall back to session-state credentials (first-time auth, not yet in Secrets)
    session_creds = st.session_state.get("gdrive_creds")
    if session_creds:
        try:
            return GDriveStore(creds_json=session_creds)
        except Exception:
            return None

    return None


# --- Unified I/O ---

def list_cards() -> list[dict]:
    try:
        backend = _get_backend()
    except Exception:
        backend = None
    cards = []
    if backend:
        image_files = backend.list_files(backend.uploads_id)
        json_files = {f["name"]: f for f in backend.list_files(backend.transcriptions_id)}
        for img in image_files:
            if Path(img["name"]).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = Path(img["name"]).stem
            json_file = json_files.get(f"{stem}.json")
            data = {}
            if json_file:
                try:
                    data = json.loads(backend.get_file_content(json_file["id"]))
                except Exception:
                    data = {}
            cards.append({
                "image_id": img["id"],
                "json_id": json_file["id"] if json_file else None,
                "name": img["name"],
                "stem": stem,
                "status": data.get("_review_status", STATUS_PENDING) if data else "not_transcribed",
                "has_json": bool(json_file),
                "has_error": "error" in data,
                "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            })
    else:
        seen_stems = set()

        # First pass: cards that have an image file (with or without JSON)
        for img_path in sorted(UPLOADS_DIR.iterdir()):
            if not img_path.is_file() or img_path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            stem = img_path.stem
            seen_stems.add(stem)
            json_path = TRANSCRIPTIONS_DIR / (stem + ".json")
            data = {}
            if json_path.exists():
                try:
                    data = json.loads(json_path.read_text(encoding="utf-8"))
                except Exception:
                    data = {}
            cards.append({
                "image_path": img_path,
                "json_path": json_path,
                "name": img_path.name,
                "stem": stem,
                "status": data.get("_review_status", STATUS_PENDING) if data else "not_transcribed",
                "has_json": json_path.exists(),
                "has_error": "error" in data,
                "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            })

        # Second pass: JSON-only cards (batch-imported transcriptions without a matching image yet)
        for json_path in sorted(TRANSCRIPTIONS_DIR.iterdir()):
            if not json_path.is_file() or json_path.suffix.lower() != ".json":
                continue
            stem = json_path.stem
            if stem in seen_stems:
                continue  # already covered above
            data = {}
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            # Try to find a matching image with any supported extension
            img_path = None
            for ext in IMAGE_EXTENSIONS:
                candidate = UPLOADS_DIR / (stem + ext)
                if candidate.exists():
                    img_path = candidate
                    break
            cards.append({
                "image_path": img_path,  # may be None if image not yet uploaded
                "json_path": json_path,
                "name": stem + (img_path.suffix if img_path else ".json"),
                "stem": stem,
                "status": data.get("_review_status", STATUS_PENDING) if data else STATUS_PENDING,
                "has_json": True,
                "has_error": "error" in data,
                "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            })

    return sorted(cards, key=lambda c: c["name"])


def load_json(card: dict) -> dict:
    backend = _get_backend()
    try:
        if backend and card.get("json_id"):
            return json.loads(backend.get_file_content(card["json_id"]))
        elif not backend and card.get("json_path") and card["json_path"].exists():
            return json.loads(card["json_path"].read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_json(card_stem: str, data: dict):
    backend = _get_backend()
    filename = f"{card_stem}.json"
    content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    if backend:
        backend.upsert_json(filename, data, backend.transcriptions_id)
    else:
        (TRANSCRIPTIONS_DIR / filename).write_bytes(content)


def get_image_bytes(card: dict) -> bytes:
    backend = _get_backend()
    try:
        if backend and card.get("image_id"):
            return backend.get_file_content(card["image_id"])
        elif not backend and card.get("image_path"):
            return card["image_path"].read_bytes()
    except Exception:
        pass
    return b""


def save_uploaded_file(uploaded_file):
    backend = _get_backend()
    if backend:
        backend.upload_bytes(
            uploaded_file.name,
            bytes(uploaded_file.getbuffer()),
            backend.uploads_id,
        )
    else:
        (UPLOADS_DIR / uploaded_file.name).write_bytes(uploaded_file.getbuffer())


# --- Other helpers ---

def count_by_status() -> dict:
    counts = {"total": 0, STATUS_PENDING: 0, STATUS_REVIEWED: 0, STATUS_FLAGGED: 0, STATUS_ERROR: 0, "not_transcribed": 0}
    for card in list_cards():
        counts["total"] += 1
        s = card["status"]
        counts[s] = counts.get(s, 0) + 1
    return counts


def list_to_str(value) -> str:
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value) if value is not None else ""


def str_to_list(text: str) -> list:
    return [line.strip() for line in text.splitlines() if line.strip()]


def append_to_csv(image_name: str, data: dict):
    file_exists = EXPORT_CSV.exists()
    with open(EXPORT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        row = {
            "image": image_name,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "status": data.get("_review_status", STATUS_REVIEWED),
            "Hieroglyphs_Present": data.get("Hieroglyphs_Present", False),
        }
        for field in EDITABLE_FIELDS:
            val = data.get(field)
            row[field] = " | ".join(val) if isinstance(val, list) else (val or "")
        writer.writerow(row)


def rebuild_csv() -> Path:
    reviewed = []
    for card in list_cards():
        if card["status"] in (STATUS_REVIEWED, STATUS_FLAGGED) and card["has_json"]:
            data = load_json(card)
            reviewed.append((card["name"], data))
    with open(EXPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES, extrasaction="ignore")
        writer.writeheader()
        for image_name, data in reviewed:
            row = {
                "image": image_name,
                "reviewed_at": data.get("_reviewed_at", ""),
                "status": data.get("_review_status", ""),
                "Hieroglyphs_Present": data.get("Hieroglyphs_Present", False),
            }
            for field in EDITABLE_FIELDS:
                val = data.get(field)
                row[field] = " | ".join(val) if isinstance(val, list) else (val or "")
            writer.writerow(row)
    return EXPORT_CSV
