# gdrive_store.py
# =================
# Google Drive storage backend.
# Uses OAuth 2.0 credentials (client_id, client_secret, refresh_token) stored
# in Streamlit Secrets.
#
# IMPORTANT: We deliberately avoid @st.cache_resource for the Drive service
# object because caching C-extension objects causes "double free or corruption"
# crashes on Streamlit Cloud (known issue). Instead we use a plain module-level
# singleton that is safe across reruns.

import io
import json
import time

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

# Module-level singleton — rebuilt at most once per process restart
_singleton: "GDriveStore | None" = None
_singleton_key: str | None = None   # refresh_token used to build it


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

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
    """Load and refresh credentials from Streamlit Secrets."""
    try:
        keys = _get_cache_keys()
        if keys is None:
            return None
        rt, ci, cs = keys
        creds = Credentials(
            token=None,
            refresh_token=rt,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=ci,
            client_secret=cs,
            scopes=SCOPES,
        )
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
# Module-level singleton (no st.cache_resource to avoid double-free crash)
# ---------------------------------------------------------------------------

def get_store() -> "GDriveStore | None":
    """
    Return the module-level GDriveStore singleton.
    Builds it once per process; returns None if credentials are unavailable.
    """
    global _singleton, _singleton_key
    keys = _get_cache_keys()
    if keys is None:
        return None
    rt = keys[0]
    # Rebuild only if the refresh token changed (i.e. different account)
    if _singleton is None or _singleton_key != rt:
        try:
            _singleton = GDriveStore()
            _singleton_key = rt
        except Exception:
            _singleton = None
    return _singleton


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
        else:
            creds = load_credentials_from_secrets()
            if creds is None:
                raise RuntimeError("Google Drive credentials not found in Streamlit Secrets.")

        self._service = build("drive", "v3", credentials=creds)
        folder_ids = self._get_folder_ids()
        self.uploads_id        = folder_ids["uploads"]
        self.transcriptions_id = folder_ids["transcriptions"]

        # In-process file list cache: {folder_id: (timestamp, [files])}
        self._list_cache: dict[str, tuple[float, list]] = {}
        self._list_ttl = 60  # seconds

    def _get_folder_ids(self) -> dict:
        def find_or_create(name, parent_id=None):
            q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            if parent_id:
                q += f" and '{parent_id}' in parents"
            items = self._service.files().list(
                q=q, spaces="drive", fields="files(id)"
            ).execute().get("files", [])
            if items:
                return items[0]["id"]
            meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
            if parent_id:
                meta["parents"] = [parent_id]
            return self._service.files().create(body=meta, fields="id").execute()["id"]

        app_id     = find_or_create(APP_FOLDER_NAME)
        uploads_id = find_or_create(UPLOADS_FOLDER_NAME, app_id)
        trans_id   = find_or_create(TRANSCRIPTIONS_FOLDER_NAME, app_id)
        return {"app": app_id, "uploads": uploads_id, "transcriptions": trans_id}

    # ── File listing (in-process TTL cache) ─────────────────────────────────

    def list_files(self, folder_id: str) -> list[dict]:
        now = time.time()
        cached = self._list_cache.get(folder_id)
        if cached and (now - cached[0]) < self._list_ttl:
            return cached[1]

        results = []
        page_token = None
        while True:
            resp = self._service.files().list(
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

        self._list_cache[folder_id] = (now, results)
        return results

    def invalidate_list_cache(self):
        self._list_cache.clear()

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
        f = self._service.files().create(
            body=meta, media_body=media, fields="id"
        ).execute()
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
