"""
transcribe_engine.py
====================
Core AI transcription logic shared by the upload pipeline and the app.
Sends a single image to the Gemini API and returns a structured JSON dict.

Accepts either a file Path OR raw bytes as the image input.
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

def _encode_image(image_input, filename: str = "card.jpg") -> tuple:
    """
    Return (base64_data, mime_type) for the given image.

    Accepts:
      - a Path object  (reads from disk, detects MIME from extension)
      - raw bytes      (detects MIME by sniffing magic bytes; falls back to image/jpeg)
    """
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".tif": "image/tiff", ".tiff": "image/tiff",
        ".bmp": "image/bmp",
        ".webp": "image/webp",
    }

    if isinstance(image_input, (str, Path)):
        # File path mode
        image_path = Path(image_input)
        mime = mime_map.get(image_path.suffix.lower(), "image/jpeg")
        with open(image_path, "rb") as f:
            raw_bytes = f.read()
        source_name = image_path.name
    else:
        # Raw bytes mode — sniff magic bytes to determine MIME type
        raw_bytes = bytes(image_input)
        if raw_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif raw_bytes[:4] in (b"RIFF", b"WEBP"):
            mime = "image/webp"
        elif raw_bytes[:2] in (b"MM", b"II"):
            mime = "image/tiff"
        elif raw_bytes[:2] == b"BM":
            mime = "image/bmp"
        else:
            # Default: JPEG (covers b'\xff\xd8\xff' and unknown formats)
            mime = "image/jpeg"
        # Try to get MIME from filename hint if available
        ext = Path(filename).suffix.lower()
        if ext in mime_map:
            mime = mime_map[ext]
        source_name = filename

    data = base64.standard_b64encode(raw_bytes).decode("utf-8")
    return data, mime, source_name


def build_client(api_key: str | None = None, base_url: str | None = None) -> OpenAI:
    """
    Build an OpenAI client pointing at the Gemini endpoint.
    Falls back to environment variables if parameters are not supplied.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY", "")
    url = base_url or os.environ.get(
        "OPENAI_BASE_URL",
        "https://generativelanguage.googleapis.com/v1beta/openai/"
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

    image_input: Path/str to an image file, OR raw bytes.
    filename:    Hint for the source filename when passing raw bytes
                 (used in metadata and MIME detection).

    Always returns a dict; on failure it contains an 'error' key.
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
