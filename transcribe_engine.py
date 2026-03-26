"""
transcribe_engine.py
====================
Core AI transcription logic shared by the upload pipeline and the app.
Sends a single image to the Gemini API and returns a structured JSON dict.

image_input can be:
  - a pathlib.Path or str  → read from disk
  - raw bytes              → encode directly (use filename= hint for MIME detection)
"""

import base64
import json
import os
import re
from pathlib import Path

from openai import OpenAI

# ── Constants ────────────────────────────────────────────────────────────────

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_MIME_MAP = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff", ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}

SYSTEM_PROMPT = """You are an expert Egyptologist with deep knowledge of Old Kingdom
administrative titles, museum cataloguing conventions, and standard Egyptological
transliteration.

Your task is to transcribe a handwritten index card written by Dr. Edward Brovarski.
The card may contain:
  * English prose and bibliographic references
  * Egyptian transliteration written in ALL CAPS with standard diacritical marks
    (e.g. H̱, Š, Ṭ, ꜣ, ꜥ, Ḥ, Ḏ, Ẓ, Ṯ, Ḳ)
  * Hand-drawn Egyptian hieroglyphs
  * Museum inventory numbers (e.g. "Berlin 1111", "Bklyn. 37.18E")
  * Bibliographic abbreviations (e.g. "BMB", "JARCE", "MDAIK")

Rules:
1. Reproduce ALL CAPS transliteration exactly, using correct Unicode diacriticals.
2. Do NOT translate any Egyptian text.
3. Preserve original punctuation and line breaks in Full_Transcription.
4. If you see hand-drawn Egyptian hieroglyphs anywhere on the card, insert the
   placeholder tag [HIEROGLYPHS_PRESENT] at the exact location in Full_Transcription.
5. If a field has no content, use null.
6. Output ONLY valid JSON – no markdown fences, no prose before or after.

Output schema (strict JSON):
{
  "Subject_Heading":    "<string | null>",
  "Museum_References":  ["<string>", ...],
  "Object_Types":       ["<string>", ...],
  "Egyptian_Titles":    ["<string>", ...],
  "Full_Transcription": "<string>",
  "Hieroglyphs_Present": <true | false>,
  "Confidence_Notes":   "<string | null>"
}

Confidence_Notes: briefly flag any words you are uncertain about, e.g.
  "Line 3 word 2 unclear – possibly 'ŠNWT' or 'ŠNBT'."
"""

# ── Helpers ──────────────────────────────────────────────────────────────────

def _mime_from_filename(filename: str) -> str:
    """Return MIME type based on file extension, defaulting to image/jpeg."""
    ext = Path(filename).suffix.lower()
    return _MIME_MAP.get(ext, "image/jpeg")


def _mime_from_bytes(data: bytes) -> str:
    """Sniff the first few bytes to determine image MIME type."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" or data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] in (b"MM", b"II"):
        return "image/tiff"
    if data[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"  # safe default


def _encode_image(image_input, filename: str = "card.jpg"):
    """
    Return (base64_string, mime_type, source_name).

    Accepts a Path/str (reads from disk) or raw bytes.
    """
    if isinstance(image_input, (str, Path)):
        p = Path(image_input)
        raw = p.read_bytes()
        mime = _mime_from_filename(p.name)
        source_name = p.name
    else:
        # Must be bytes-like
        raw = bytes(image_input)
        # Prefer extension hint from filename, fall back to magic-byte sniff
        ext = Path(filename).suffix.lower()
        mime = _MIME_MAP.get(ext) or _mime_from_bytes(raw)
        source_name = filename

    b64 = base64.standard_b64encode(raw).decode("utf-8")
    return b64, mime, source_name


def build_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    """Build an OpenAI client pointing at the Gemini endpoint."""
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    url = base_url or os.environ.get(
        "OPENAI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    return OpenAI(api_key=key, base_url=url)


# ── Main transcription function ───────────────────────────────────────────────

def transcribe_image(
    image_input,
    client: OpenAI,
    model: str = DEFAULT_MODEL,
    filename: str = "card.jpg",
) -> dict:
    """
    Send one image to the Gemini API and return the parsed JSON dict.

    image_input : Path/str to an image file, OR raw bytes.
    filename    : Filename hint used for MIME detection and metadata when
                  image_input is raw bytes.

    Always returns a dict. On failure the dict contains an 'error' key.
    """
    b64, mime, source_name = _encode_image(image_input, filename=filename)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{b64}",
                        "detail": "high",
                    },
                },
                {
                    "type": "text",
                    "text": (
                        "Please transcribe this index card and return the result "
                        "as the JSON object described in your instructions."
                    ),
                },
            ],
        },
    ]

    raw = ""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()

        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        result = json.loads(raw)

        # Normalise the hieroglyph flag
        if "Hieroglyphs_Present" not in result:
            result["Hieroglyphs_Present"] = (
                "[HIEROGLYPHS_PRESENT]" in result.get("Full_Transcription", "")
            )

        result["_source_image"] = source_name
        result["_model"] = model
        result["_review_status"] = "pending"
        return result

    except json.JSONDecodeError as exc:
        return {
            "error": f"JSON parse error: {exc}",
            "raw_response": raw,
            "_source_image": source_name,
            "_model": model,
            "_review_status": "error",
        }
    except Exception as exc:
        return {
            "error": str(exc),
            "_source_image": source_name,
            "_model": model,
            "_review_status": "error",
        }
