"""
data_store.py
=============
Centralised helpers for reading and writing card data (JSON files + CSV export).
All pages import from here so the data layer is in one place.
"""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────

DATA_DIR = Path(__file__).parent / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
TRANSCRIPTIONS_DIR = DATA_DIR / "transcriptions"
EXPORT_CSV = DATA_DIR / "corrections_export.csv"

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

# Statuses
STATUS_PENDING  = "pending"
STATUS_REVIEWED = "reviewed"
STATUS_FLAGGED  = "flagged"
STATUS_ERROR    = "error"

# JSON fields shown in the review editor
EDITABLE_FIELDS = [
    "Subject_Heading",
    "Museum_References",
    "Object_Types",
    "Egyptian_Titles",
    "Full_Transcription",
    "Confidence_Notes",
]

# ── Ensure directories exist ──────────────────────────────────────────────────

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPTIONS_DIR.mkdir(parents=True, exist_ok=True)


# ── Card discovery ────────────────────────────────────────────────────────────

def list_cards() -> list[dict]:
    """
    Return a list of card metadata dicts, one per uploaded image.
    Each dict contains: image_path, json_path, name, status, has_json.
    """
    cards = []
    for img in sorted(UPLOADS_DIR.iterdir()):
        if img.is_file() and img.suffix.lower() in IMAGE_EXTENSIONS:
            json_path = TRANSCRIPTIONS_DIR / (img.stem + ".json")
            data = load_json(json_path) if json_path.exists() else {}
            cards.append({
                "image_path": img,
                "json_path": json_path,
                "name": img.name,
                "stem": img.stem,
                "status": data.get("_review_status", STATUS_PENDING) if data else "not_transcribed",
                "has_json": json_path.exists(),
                "has_error": "error" in data,
                "has_hieroglyphs": bool(data.get("Hieroglyphs_Present", False)),
            })
    return cards


def count_by_status() -> dict:
    """Return counts keyed by status string."""
    counts = {
        "total": 0,
        STATUS_PENDING: 0,
        STATUS_REVIEWED: 0,
        STATUS_FLAGGED: 0,
        STATUS_ERROR: 0,
        "not_transcribed": 0,
    }
    for card in list_cards():
        counts["total"] += 1
        s = card["status"]
        if s in counts:
            counts[s] += 1
        else:
            counts[STATUS_PENDING] += 1
    return counts


# ── JSON I/O ──────────────────────────────────────────────────────────────────

def load_json(json_path: Path) -> dict:
    try:
        return json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(json_path: Path, data: dict) -> None:
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── List helpers ──────────────────────────────────────────────────────────────

def list_to_str(value) -> str:
    """Convert a JSON list to a newline-separated string for text areas."""
    if isinstance(value, list):
        return "\n".join(str(v) for v in value)
    return str(value) if value is not None else ""


def str_to_list(text: str) -> list:
    """Convert a newline-separated string back to a cleaned list."""
    return [line.strip() for line in text.splitlines() if line.strip()]


# ── CSV export ────────────────────────────────────────────────────────────────

CSV_FIELDNAMES = ["image", "reviewed_at", "status"] + EDITABLE_FIELDS + ["Hieroglyphs_Present"]


def append_to_csv(image_name: str, data: dict) -> None:
    """Append one reviewed record to the master CSV export."""
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


def rebuild_csv() -> None:
    """Regenerate the full CSV from all reviewed JSON files."""
    reviewed = []
    for card in list_cards():
        if card["status"] in (STATUS_REVIEWED, STATUS_FLAGGED) and card["has_json"]:
            data = load_json(card["json_path"])
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
