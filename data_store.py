# data_store.py
# =============
# Centralised helpers for reading/writing data. Abstracts local vs Google Drive storage.
#
# PERFORMANCE NOTE (Google Drive mode):
# Instead of downloading every JSON file on each page load to read status/metadata,
# we maintain a single lightweight "index.json" file in the transcriptions folder.
# This means the dashboard and sidebar only need ONE API call to get all card statuses.

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
INDEX_FILENAME = "_index.json"  # Lightweight metadata index stored in transcriptions folder

# Ensure local dirs exist
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Backend helper
# ---------------------------------------------------------------------------

def _get_backend():
    """
    Return a GDriveStore if credentials are available, else None (local mode).
    Priority:
      1. Streamlit Secrets [gdrive] section (permanent, survives restarts)
      2. Session-state gdrive_creds (set during first-time OAuth flow)
    """
    from gdrive_store import _get_cache_keys, GDriveStore

    # Try Secrets first (permanent connection)
    if _get_cache_keys() is not None:
        try:
            return GDriveStore()
        except Exception:
            pass

    # Fall back to session-state credentials
    session_creds = st.session_state.get("gdrive_creds")
    if session_creds:
        try:
            return GDriveStore(creds_json=session_creds)
        except Exception:
            return None

    return None


# ---------------------------------------------------------------------------
# Drive index helpers — one small JSON file tracks all card metadata
# ---------------------------------------------------------------------------

def _load_drive_index(backend) -> dict:
    """
    Load the lightweight index from Drive. Returns dict keyed by stem.
    Each entry: {status, has_json, has_error, has_hieroglyphs, json_id, image_id}
    Falls back to empty dict if not found.
    """
    try:
        files = backend.list_files(backend.transcriptions_id)
        idx_file = next((f for f in files if f["name"] == INDEX_FILENAME), None)
        if idx_file:
            raw = backend.get_file_content(idx_file["id"])
            return json.loads(raw)
    except Exception:
        pass
    return {}


def _save_drive_index(backend, index: dict):
    """Save the lightweight index to Drive."""
    try:
        backend.upsert_json(INDEX_FILENAME, index, backend.transcriptions_id)
    except Exception:
        pass


def _rebuild_drive_index(backend) -> dict:
    """
    Rebuild the index by listing files only (no content downloads).
    Called once when index is missing or after bulk imports.
    """
    image_files = backend.list_files(backend.uploads_id)
    json_files_list = backend.list_files(backend.transcriptions_id)

    image_map = {Path(f["name"]).stem: f for f in image_files
                 if Path(f["name"]).suffix.lower() in IMAGE_EXTENSIONS}
    json_map  = {Path(f["name"]).stem: f for f in json_files_list
                 if f["name"] != INDEX_FILENAME and Path(f["name"]).suffix.lower() == ".json"}

    all_stems = set(image_map.keys()) | set(json_map.keys())
    index = {}
    for stem in all_stems:
        img  = image_map.get(stem)
        jf   = json_map.get(stem)
        # We don't download the JSON here — status defaults to pending
        # It will be updated to the real status next time save_json() is called
        index[stem] = {
            "image_id":       img["id"] if img else None,
            "image_name":     img["name"] if img else (stem + ".jpg"),
            "json_id":        jf["id"] if jf else None,
            "has_json":       jf is not None,
            "has_error":      False,
            "has_hieroglyphs": False,
            "status":         STATUS_PENDING if jf else "not_transcribed",
        }
    _save_drive_index(backend, index)
    return index


# ---------------------------------------------------------------------------
# Unified I/O
# ---------------------------------------------------------------------------

def list_cards() -> list[dict]:
    try:
        backend = _get_backend()
    except Exception:
        backend = None

    cards = []

    if backend:
        # Load the lightweight index (1 API call max, cached 60s)
        index = _load_drive_index(backend)

        # If index is empty, rebuild it from file listings (no content downloads)
        if not index:
            index = _rebuild_drive_index(backend)

        for stem, meta in index.items():
            cards.append({
                "image_id":  meta.get("image_id"),
                "json_id":   meta.get("json_id"),
                "name":      meta.get("image_name", stem + ".jpg"),
                "stem":      stem,
                "status":    meta.get("status", STATUS_PENDING),
                "has_json":  meta.get("has_json", False),
                "has_error": meta.get("has_error", False),
                "has_hieroglyphs": meta.get("has_hieroglyphs", False),
            })

    else:
        seen_stems = set()

        # First pass: cards that have an image file
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
                "json_path":  json_path,
                "name":       img_path.name,
                "stem":       stem,
                "status":     data.get("_review_status", STATUS_PENDING) if data else "not_transcribed",
                "has_json":   json_path.exists(),
                "has_error":  "error" in data,
                "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            })

        # Second pass: JSON-only cards
        for json_path in sorted(TRANSCRIPTIONS_DIR.iterdir()):
            if not json_path.is_file() or json_path.suffix.lower() != ".json":
                continue
            stem = json_path.stem
            if stem in seen_stems:
                continue
            data = {}
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            img_path = None
            for ext in IMAGE_EXTENSIONS:
                candidate = UPLOADS_DIR / (stem + ext)
                if candidate.exists():
                    img_path = candidate
                    break
            cards.append({
                "image_path": img_path,
                "json_path":  json_path,
                "name":       stem + (img_path.suffix if img_path else ".json"),
                "stem":       stem,
                "status":     data.get("_review_status", STATUS_PENDING) if data else STATUS_PENDING,
                "has_json":   True,
                "has_error":  "error" in data,
                "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            })

    return sorted(cards, key=lambda c: c["name"])


def load_json(card: dict) -> dict:
    try:
        backend = _get_backend()
    except Exception:
        backend = None
    try:
        if backend and card.get("json_id"):
            return json.loads(backend.get_file_content(card["json_id"]))
        elif not backend and card.get("json_path") and card["json_path"].exists():
            return json.loads(card["json_path"].read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def save_json(card_stem: str, data: dict):
    try:
        backend = _get_backend()
    except Exception:
        backend = None

    filename = f"{card_stem}.json"

    if backend:
        new_id = backend.upsert_json(filename, data, backend.transcriptions_id)
        # Update the index with the latest metadata so future list_cards() is accurate
        index = _load_drive_index(backend)
        entry = index.get(card_stem, {})
        entry.update({
            "json_id":        new_id,
            "has_json":       True,
            "has_error":      "error" in data,
            "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            "status":         data.get("_review_status", STATUS_PENDING),
        })
        if "image_name" not in entry:
            entry["image_name"] = card_stem + ".jpg"
        index[card_stem] = entry
        _save_drive_index(backend, index)
    else:
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        (TRANSCRIPTIONS_DIR / filename).write_bytes(content)


def get_image_bytes(card: dict) -> bytes:
    try:
        backend = _get_backend()
    except Exception:
        backend = None
    try:
        if backend and card.get("image_id"):
            return backend.get_file_content(card["image_id"])
        elif not backend and card.get("image_path") and card["image_path"]:
            return card["image_path"].read_bytes()
    except Exception:
        pass
    return b""


def save_uploaded_file(uploaded_file):
    try:
        backend = _get_backend()
    except Exception:
        backend = None

    if backend:
        new_id = backend.upload_bytes(
            uploaded_file.name,
            bytes(uploaded_file.getbuffer()),
            backend.uploads_id,
        )
        # Update index to record the image
        stem = Path(uploaded_file.name).stem
        index = _load_drive_index(backend)
        entry = index.get(stem, {})
        entry.update({
            "image_id":   new_id,
            "image_name": uploaded_file.name,
        })
        if "status" not in entry:
            entry["status"] = "not_transcribed"
        if "has_json" not in entry:
            entry["has_json"] = False
        index[stem] = entry
        _save_drive_index(backend, index)
    else:
        (UPLOADS_DIR / uploaded_file.name).write_bytes(uploaded_file.getbuffer())


# ---------------------------------------------------------------------------
# Other helpers
# ---------------------------------------------------------------------------

def count_by_status() -> dict:
    counts = {"total": 0, STATUS_PENDING: 0, STATUS_REVIEWED: 0,
              STATUS_FLAGGED: 0, STATUS_ERROR: 0, "not_transcribed": 0}
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
            "image":    image_name,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
            "status":   data.get("_review_status", STATUS_REVIEWED),
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
                "image":       image_name,
                "reviewed_at": data.get("_reviewed_at", ""),
                "status":      data.get("_review_status", ""),
                "Hieroglyphs_Present": data.get("Hieroglyphs_Present", False),
            }
            for field in EDITABLE_FIELDS:
                val = data.get(field)
                row[field] = " | ".join(val) if isinstance(val, list) else (val or "")
            writer.writerow(row)
    return EXPORT_CSV
