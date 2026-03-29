# gdrive_store.py
# =================
# Google Drive storage backend.
# Uses OAuth 2.0 credentials (client_id, client_secret, refresh_token) stored
# in Streamlit Secrets. The access token is refreshed automatically — no user
# interaction needed after the initial one-time setup.
#
# PERFORMANCE: The Drive service, folder IDs, and file listings are all cached
# aggressively so that page reloads never trigger redundant API calls.

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
    Load OAuth credentials from Streamlit Secrets [gdrive] section.
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
        if not creds.valid:
            creds.refresh(Request())
        return creds
    except Exception:
        return None


def load_credentials_from_json(creds_json: str) -> Credentials | None:
    try:
        creds_dict = json.loads(creds_json)
        creds = _build_credentials(creds_dict)
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
        return creds
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Cached Drive service + folder IDs
# Keyed on refresh_token so different accounts get separate caches.
# TTL=3600 means the service is rebuilt at most once per hour.
# ---------------------------------------------------------------------------

@st.cache_resource(ttl=3600)
def _cached_service(refresh_token: str, client_id: str, client_secret: str):
    """Build and cache a Drive service. Rebuilt at most once per hour."""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds)


@st.cache_data(ttl=3600)
def _cached_folder_ids(refresh_token: str, client_id: str, client_secret: str) -> dict:
    """Find or create app folders. Cached for 1 hour — only 3 API calls max per hour."""
    svc = _cached_service(refresh_token, client_id, client_secret)

    def find_or_create(name, parent_id=None):
        q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        if parent_id:
            q += f" and '{parent_id}' in parents"
        items = svc.files().list(q=q, spaces="drive", fields="files(id)").execute().get("files", [])
        if items:
            return items[0]["id"]
        meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
        if parent_id:
            meta["parents"] = [parent_id]
        return svc.files().create(body=meta, fields="id").execute()["id"]

    app_id     = find_or_create(APP_FOLDER_NAME)
    uploads_id = find_or_create(UPLOADS_FOLDER_NAME, app_id)
    trans_id   = find_or_create(TRANSCRIPTIONS_FOLDER_NAME, app_id)
    return {"app": app_id, "uploads": uploads_id, "transcriptions": trans_id}


@st.cache_data(ttl=60)
def _cached_file_list(folder_id: str, refresh_token: str, client_id: str, client_secret: str) -> list[dict]:
    """List files in a folder. Cached for 60 seconds to avoid hammering the API."""
    svc = _cached_service(refresh_token, client_id, client_secret)
    results = []
    page_token = None
    while True:
        resp = svc.files().list(
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


def _get_cache_keys() -> tuple[str, str, str] | None:
    """Return (refresh_token, client_id, client_secret) from Secrets, or None."""
    try:
        section = st.secrets.get("gdrive", {})
        rt = section.get("refresh_token", "")
        ci = section.get("client_id", "")
        cs = section.get("client_secret", "")
        if rt and ci and cs:
            return rt, ci, cs
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Public GDriveStore class
# ---------------------------------------------------------------------------

class GDriveStore:
    """
    Thin wrapper around the Drive v3 API with aggressive caching.
    Instantiate with either:
      - GDriveStore()               → loads credentials from Streamlit Secrets
      - GDriveStore(creds_json=...) → loads from a JSON string (first-time auth)
    """

    def __init__(self, creds_json: str | None = None):
        if creds_json:
            # First-time auth: build service directly (no cache key available yet)
            creds = load_credentials_from_json(creds_json)
            if creds is None:
                raise RuntimeError("Invalid credentials JSON.")
            self._service = build("drive", "v3", credentials=creds)
            self._rt  = creds.refresh_token
            self._ci  = creds.client_id
            self._cs  = creds.client_secret
            folder_ids = _cached_folder_ids(self._rt, self._ci, self._cs)
        else:
            keys = _get_cache_keys()
            if keys is None:
                raise RuntimeError("Google Drive credentials not found in Streamlit Secrets.")
            self._rt, self._ci, self._cs = keys
            self._service = _cached_service(self._rt, self._ci, self._cs)
            folder_ids = _cached_folder_ids(self._rt, self._ci, self._cs)

        self.uploads_id       = folder_ids["uploads"]
        self.transcriptions_id = folder_ids["transcriptions"]

    @property
    def service(self):
        return self._service

    # ── File listing (cached 60s) ────────────────────────────────────────────

    def list_files(self, folder_id: str) -> list[dict]:
        return _cached_file_list(folder_id, self._rt, self._ci, self._cs)

    def invalidate_list_cache(self):
        """Call after uploading a file so the next list_files() is fresh."""
        _cached_file_list.clear()

    # ── File download ────────────────────────────────────────────────────────

    def get_file_content(self, file_id: str) -> bytes:
        request = self._service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()

    # ── File upload ──────────────────────────────────────────────────────────

    def upload_bytes(self, name: str, data: bytes, folder_id: str,
                     mimetype: str = "application/octet-stream") -> str:
        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mimetype)
        meta  = {"name": name, "parents": [folder_id]}
        f = self._service.files().create(body=meta, media_body=media, fields="id").execute()
        self.invalidate_list_cache()
        return f["id"]

    def upsert_json(self, name: str, data: dict, folder_id: str) -> str:
        """Upload a JSON file, replacing any existing file with the same name."""
        content = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        q = f"name='{name}' and '{folder_id}' in parents and trashed=false"
        existing = self._service.files().list(
            q=q, spaces="drive", fields="files(id)"
        ).execute().get("files", [])
        for f in existing:
            try:
                self._service.files().delete(fileId=f["id"]).execute()
            except Exception:
                pass
        result = self.upload_bytes(name, content, folder_id, mimetype="application/json")
        self.invalidate_list_cache()
        return result
