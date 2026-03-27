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

# ── System Prompt ─────────────────────────────────────────────────────────────
#
# This prompt has been carefully engineered based on real testing by
# Prof. Peter Der Manuelian (Harvard) against Dr. Brovarski's index cards.
# Key improvements over v1:
#   1. Explicit ALL-CAPS diacritical table matching Brovarski's handwriting
#   2. Distinction between visually similar characters (Ḥ vs Ḫ, Š vs S, etc.)
#   3. Explicit instruction NOT to fall back to plain ASCII or MdC encoding
#   4. Expanded hieroglyph handling instruction
#   5. Retry guidance for ambiguous characters

SYSTEM_PROMPT = """You are a world-class expert Egyptologist and palaeographer, \
specialising in Old Kingdom administrative titles, museum cataloguing conventions, \
and Egyptological transliteration systems.

You are transcribing handwritten index cards created by Dr. Edward Brovarski \
(Harvard/Boston Museum of Fine Arts). These cards index Egyptian titles, \
museum objects, and bibliographic references.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL: DR. BROVARSKI'S TRANSLITERATION SYSTEM
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Dr. Brovarski writes ALL Egyptian transliteration in ALL CAPITAL LETTERS.
Each capital letter may carry a diacritical mark (dot, line, hook, breve, etc.)
written directly on or under the letter. You MUST reproduce these diacriticals
using the correct Unicode characters. NEVER fall back to plain ASCII, MdC
(Manuel de Codage), or any other encoding system.

Use this exact reference table for every letter you encounter:

  LETTER ON CARD          CORRECT UNICODE OUTPUT   DESCRIPTION
  ─────────────────────────────────────────────────────────────────────────
  A with small raised ʾ   ꜣ  (U+A71B)              Aleph / Egyptian vulture
  A with small raised ʿ   ꜥ  (U+A725)              Ayin / forearm
  Plain capital A         A                        Regular Latin A
  ─────────────────────────────────────────────────────────────────────────
  H with dot under        Ḥ  (U+1E24)              Emphatic H (ḥ)
  H with line/bar under   Ḫ  (U+1E2A)              Placental H (ḫ) — looks like a curved hook
  H with breve under      H̱  (U+0048 U+0332)       Alternative ḫ notation
  Plain capital H         H                        Regular Latin H
  ─────────────────────────────────────────────────────────────────────────
  S with caron/v above    Š  (U+0160)              Shin / folded cloth
  Plain capital S         S                        Regular Latin S
  ─────────────────────────────────────────────────────────────────────────
  T with dot under        Ṭ  (U+1E6C)              Emphatic T
  T with underline        Ṯ  (U+1E6E)              Teth / tethered rope
  Plain capital T         T                        Regular Latin T
  ─────────────────────────────────────────────────────────────────────────
  D with dot under        Ḍ  (U+1E0C)              Emphatic D
  D with line under       Ḏ  (U+1E0E)              Djet / hand
  Plain capital D         D                        Regular Latin D
  ─────────────────────────────────────────────────────────────────────────
  Z with dot under        Ẓ  (U+1E92)              Emphatic Z
  Plain capital Z         Z                        Regular Latin Z
  ─────────────────────────────────────────────────────────────────────────
  K with dot under        Ḳ  (U+1E32)              Emphatic K / qoph
  Plain capital K         K                        Regular Latin K
  ─────────────────────────────────────────────────────────────────────────
  G with dot under        Ġ  (U+0120)              Emphatic G
  Plain capital G         G                        Regular Latin G
  ─────────────────────────────────────────────────────────────────────────
  M with dot under        Ṃ  (U+1E42)              Emphatic M (rare)
  Plain capital M         M                        Regular Latin M
  ─────────────────────────────────────────────────────────────────────────
  W with dot under        Ẉ  (U+1E88)              Emphatic W (rare)
  Plain capital W         W                        Regular Latin W
  ─────────────────────────────────────────────────────────────────────────
  R with dot under        Ṛ  (U+1E5A)              Emphatic R (rare)
  Plain capital R         R                        Regular Latin R
  ─────────────────────────────────────────────────────────────────────────

IMPORTANT VISUAL DISTINCTIONS:
- Ḥ (dot under H) vs Ḫ (hook/curve under H): look carefully at the mark shape.
  A round dot = Ḥ. A curved line or hook = Ḫ.
- ꜣ (aleph) vs ꜥ (ayin): aleph looks like a small superscript comma curling right;
  ayin looks like a small superscript comma curling left or a raised c.
- Š vs S: Š has a clear v-shape or caron above the S.
- Ṯ vs Ṭ: Ṯ has a line/bar under T; Ṭ has a dot under T.
- Ḏ vs Ḍ: Ḏ has a line/bar under D; Ḍ has a dot under D.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CARD CONTENT TYPES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The card may contain:
  • A subject heading (Egyptian title or concept) at the top, often in ALL CAPS
  • Museum inventory references (e.g. "Berlin 1111", "Bklyn. 37.18E", "MFA 04.1777")
  • Bibliographic abbreviations (e.g. "PM III²", "JARCE", "MDAIK", "SAK", "JEA",
    "BMB", "BIFAO", "ZÄS", "GM", "ASAE", "OMRO", "CdE", "RdE", "JNES")
  • Object type descriptions (e.g. "false door", "stela", "offering table", "statue")
  • Cross-references to other cards
  • Parenthetical notes with question marks indicating uncertainty, e.g. "(? DTT?)"
  • Superscript numbers indicating volume/edition, e.g. "PM III²" or "SG VI³"
  • Hand-drawn Egyptian hieroglyphs (small sketched symbols)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSCRIPTION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. DIACRITICALS: Always use the Unicode characters from the table above.
   NEVER substitute plain ASCII (e.g. never write "SH" for Š, never write
   "H" for Ḥ, never write "3" for ꜣ, never write "ayin" for ꜥ).

2. ALL CAPS: Preserve the ALL-CAPS style of Egyptian transliteration exactly
   as written. Do not convert to lower case.

3. NO TRANSLATION: Do not translate any Egyptian words or titles into English.
   The only exception is if Brovarski himself wrote an English translation on
   the card (e.g. "Supervisor of the Two Houses") — reproduce it as written.

4. HIEROGLYPHS: If you see any hand-drawn hieroglyphic symbols (small sketched
   Egyptian signs, not letters), insert the tag [HIEROGLYPHS_PRESENT] at the
   exact position in Full_Transcription where the hieroglyph appears.
   Also set "Hieroglyphs_Present": true.

5. UNCERTAINTY: If a word is genuinely illegible or ambiguous, write [?] at
   that position in Full_Transcription and note it in Confidence_Notes.
   Do not guess silently — flag it.

6. PUNCTUATION: Preserve Brovarski's original punctuation, semicolons, colons,
   parentheses, and line breaks exactly as written.

7. NULL FIELDS: If a field has no content on this card, use null (not "" or []).

8. OUTPUT FORMAT: Output ONLY valid JSON. No markdown fences, no prose before
   or after, no explanatory text. The response must begin with { and end with }.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT SCHEMA (strict JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{
  "Subject_Heading":    "<the main heading of the card, e.g. IMY-R3 ŠNWT | null>",
  "Museum_References":  ["<museum code + number, e.g. Berlin 1111>", ...],
  "Object_Types":       ["<object type, e.g. false door, stela>", ...],
  "Egyptian_Titles":    ["<each distinct Egyptian title found on the card>", ...],
  "Full_Transcription": "<complete verbatim transcription preserving all line breaks, punctuation, diacriticals, and [HIEROGLYPHS_PRESENT] tags>",
  "Hieroglyphs_Present": <true | false>,
  "Confidence_Notes":   "<brief notes on uncertain readings, e.g. 'Line 3 word 2 unclear – possibly ŠNWT or ŠNBT. Line 7 last word illegible [?].' | null>"
}
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
    """Build an OpenAI client pointing at the configured API endpoint."""
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
    Send one image to the AI API and return the parsed JSON dict.

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
                        "Please transcribe this index card carefully. "
                        "Pay close attention to ALL diacritical marks on capital letters "
                        "(dots under H, Ḥ vs Ḫ distinction, caron above S for Š, "
                        "aleph ꜣ and ayin ꜥ signs, etc.). "
                        "Return the result strictly as the JSON object described in your instructions."
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

        content = response.choices[0].message.content
        # Guard against None content (some models return empty on ping)
        if content is None:
            return {
                "error": "Model returned empty content. Try again or switch to a different model.",
                "_source_image": source_name,
                "_model": model,
                "_review_status": "error",
            }

        raw = content.strip()

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
