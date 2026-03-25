# Brovarski Papers — AI Transcription & Review Platform

A fully integrated Streamlit web application for digitising and reviewing Dr. Edward Brovarski's Egyptology index card archive.

## Features

- **Upload & Auto-Transcribe** — Drag-and-drop scanned card images. Each image is immediately sent to the Gemini AI for transcription and placed in the review queue automatically.
- **Human-in-the-Loop Review** — Side-by-side interface: original scan on the left, editable AI transcription on the right. Supports filtering by status, hieroglyph presence, and more.
- **Export** — Download reviewed data as CSV, JSON, or a full archive ZIP containing images and JSON files.
- **Settings** — Configure your API key, model, and base URL from the UI. Includes a live connection test.
- **Dashboard** — Real-time progress metrics and quick-action shortcuts.

## Running Locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

Then open http://localhost:8501 in your browser.

## Deploying to Streamlit Community Cloud (Free)

1. Push this folder to a GitHub repository.
2. Go to [share.streamlit.io](https://share.streamlit.io) and click **New app**.
3. Select your repository and set the main file path to `app.py`.
4. Under **Advanced settings → Secrets**, add:
   ```toml
   OPENAI_API_KEY = "your-gemini-api-key-here"
   OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
   GEMINI_MODEL = "gemini-2.5-flash"
   ```
5. Click **Deploy**. Your app will be live at a public URL within minutes.

> **Note on data persistence:** Streamlit Community Cloud does not persist files between sessions. For a production deployment with persistent storage, use a cloud storage backend (e.g. Google Drive, AWS S3) or deploy to a VPS. See the deployment guide below.

## Deploying to a VPS (Persistent Storage)

For a permanent installation with persistent data:

```bash
# On your server (Ubuntu 22.04+)
git clone <your-repo-url> brovarski_app
cd brovarski_app
pip install -r requirements.txt

# Run with nohup to keep it alive
nohup streamlit run app.py --server.port 8501 &

# Or use systemd / screen / tmux for production
```

## File Structure

```
brovarski_app/
├── app.py                  # Main entry point and navigation
├── transcribe_engine.py    # AI transcription logic (shared module)
├── data_store.py           # Data I/O helpers (shared module)
├── requirements.txt
├── .streamlit/
│   └── config.toml         # Theme and server settings
├── pages/
│   ├── dashboard.py        # Overview metrics
│   ├── upload.py           # Upload + auto-transcription pipeline
│   ├── review.py           # HITL correction interface
│   ├── export.py           # CSV / JSON / ZIP download
│   └── settings.py         # API key, model, configuration
└── data/
    ├── uploads/            # Uploaded card images
    ├── transcriptions/     # AI-generated JSON files
    └── corrections_export.csv
```

## Supported Models

| Model | Speed | Est. Cost / 10k cards | Best For |
|---|---|---|---|
| `gemini-2.5-flash` | Fast | ~$5–10 | Most cards |
| `gemini-2.5-pro` | Slow | ~$50–100 | Difficult handwriting |
| `gpt-4o` | Medium | ~$30–50 | OpenAI alternative |
