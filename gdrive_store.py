# gdrive_store.py
# =================
# Google Drive storage backend.
# Uses OAuth 2.0 credentials (client_id, client_secret, refresh_token) stored
# in Streamlit Secrets. The access token is refreshed automatically — no user
# interaction needed after the initial one-time setup.

import io
import json
from pathlib import Path

import streamlit as st
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- Constants ---
SCOPES = ["https://www.googleapis.com/auth/drive"]
APP_FOLDER_NAME = "Brovarski_Papers_App"
UPLOADS_FOLDER_NAME = "uploads"
TRANSCRIPTIONS_FOLDER_NAME = "transcriptions"


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _build_credentials(creds_dict: dict) -> Credentials:
    """Build a Credentials object from a dict with OAuth fields."""
    return Credentials(
        token=creds_dict.get("token"),
        refresh_token=creds_dict.get("refresh_token"),
        token_uri=creds_dict.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=creds_dict.get("client_id"),
        client_secret=creds_dict.get("client_secret"),
        scopes=SCOPES,
    )


def load_credentials_from_secrets() -> Credentials | None:
    """
    Try to load OAuth credentials from Streamlit Secrets.
    Secrets must contain a [gdrive] section with:
        client_id, client_secret, refresh_token
    Returns a valid, refreshed Credentials object or None.
    """
    try:
        section = st.secrets.get("gdrive", {})
        if not section:
            return None
        creds_dict = {
            "client_id":     section.get("client_id", ""),
            "client_secret": section.get("client_secret", ""),
            "refresh_token": section.get("refresh_token", ""),
            "token_uri":     section.get("token_uri", "https://oauth2.googleapis.com/token"),
            "token":         section.get("token", None),
        }
        if not creds_dict["client_id"] or not creds_dict["refresh_token"]:
            return None
        creds = _build_credentials(creds_dict)
        # Refresh if expired or no access token
        if not creds.valid:
            creds.refresh(Request())
        return creds
    except Exception:
        return None


def load_credentials_from_json(creds_json: str) -> Credentials | None:
    """Build credentials from a JSON string (used during first-time auth flow)."""
    try:
        creds_dict = json.loads(creds_json)
        creds = _build_credentials(creds_dict)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
        return creds
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Drive service (cached)
# ---------------------------------------------------------------------------

@st.cache_resource
def _get_service(_creds_token: str):
    """Cache the Drive service keyed on the access token string."""
    creds = load_credentials_from_secrets()
    if creds is None:
        raise RuntimeError("Google Drive credentials not available.")
    return build("drive", "v3", credentials=creds)


def _service():
    """Return a (possibly refreshed) Drive service."""
    creds = load_credentials_from_secrets()
    if creds is None:
        raise RuntimeError("Google Drive credentials not available.")
    return build("drive", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Folder helpers
# ---------------------------------------------------------------------------

def _find_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    results = service.files().list(q=q, spaces="drive", fields="files(id)").execute()
    items = results.get("files", [])
    if items:
        return items[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _get_folder_ids(service) -> dict:
    app_id = _find_or_create_folder(service, APP_FOLDER_NAME)
    uploads_id = _find_or_create_folder(service, UPLOADS_FOLDER_NAME, app_id)
    trans_id = _find_or_create_folder(service, TRANSCRIPTIONS_FOLDER_NAME, app_id)
    return {"app": app_id, "uploads": uploads_id, "transcriptions": trans_id}


# ---------------------------------------------------------------------------
# Public GDriveStore class
# ---------------------------------------------------------------------------

class GDriveStore:
    """
    Thin wrapper around the Drive v3 API.
    Instantiate with either:
      - GDriveStore()               → loads credentials from Streamlit Secrets
      - GDriveStore(creds_json=...) → loads from a JSON string (first-time auth)
    """

    def __init__(self, creds_json: str | None = None):
        if creds_json:
            creds = load_credentials_from_json(creds_json)
            if creds is None:
                raise RuntimeError("Invalid credentials JSON.")
            self.service = build("drive", "v3", credentials=creds)
        else:
            self.service = _service()

        folder_ids = _get_folder_ids(self.service)
        self.uploads_id = folder_ids["uploads"]
        self.transcriptions_id = folder_ids["transcriptions"]

    # ── File listing ────────────────────────────────────────────────────────

    def list_files(self, folder_id: str) -> list[dict]:
        """Return list of {id, name} dicts for all non-trashed files in folder."""
        results = []
        page_token = None
        while True:
            resp = self.service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                spaces="drive",
                fields="nextPageToken, files(id, name)",
                pageToken=page_token,
                pageSize=1000,
            ).execute()
            results.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return results

    # ── File download ────────────────────────────────────────────────────────

    def get_file_content(self, file_id: str) -> bytes:
        """Download a file and return its raw bytes."""
        request = self.service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    # ── File upload ──────────────────────────────────────────────────────────

    def upload_bytes(self, name: str, data: bytes, folder_id: str,
                     mimetype: str = "application/octet-stream") -> str:
        """Upload raw bytes as a new file. Returns the new file ID."""
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype)
        meta = {"name": name, "parents": [folder_id]}
        f = self.service.files().create(body=meta, media_body=media, fields="id").execute()
        return f["id"]

    def upsert_json(self, name: str, data: dict, folder_id: str) -> str:
        """
        Upload a JSON file, replacing any existing file with the same name.
        Returns the file ID.
        """
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        # Delete existing file if present
        q = f"name='{name}' and '{folder_id}' in parents and trashed=false"
        existing = self.service.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
        for f in existing:
            try:
                self.service.files().delete(fileId=f["id"]).execute()
            except Exception:
                pass
        return self.upload_bytes(name, content, folder_id, mimetype="application/json")
