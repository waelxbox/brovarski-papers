# gdrive_store.py
# =================
# Google Drive storage backend for persistent file storage.

import os
import io
import json
from pathlib import Path

import streamlit as st
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

# --- Constants ---
SCOPES = ["https://www.googleapis.com/auth/drive"]
APP_FOLDER_NAME = "Brovarski_Papers_App"
UPLOADS_FOLDER_NAME = "uploads"
TRANSCRIPTIONS_FOLDER_NAME = "transcriptions"

# --- Caching ---
@st.cache_resource
def get_service(_credentials): # Underscore to mark credentials as unhashed
    """Build and cache the Google Drive API service object."""
    return build("drive", "v3", credentials=_credentials)

@st.cache_data(ttl=300) # Cache folder IDs for 5 minutes
def get_folder_ids(_service, app_folder_name, uploads_folder_name, transcriptions_folder_name):
    """Find or create the required folder structure in Google Drive."""
    # Find or create the main app folder
    q = f"name=\'{app_folder_name}\' and mimeType=\'application/vnd.google-apps.folder\' and trashed=false"
    results = _service.files().list(q=q, spaces="drive", fields="files(id)").execute()
    items = results.get("files", [])
    if not items:
        file_metadata = {"name": app_folder_name, "mimeType": "application/vnd.google-apps.folder"}
        app_folder = _service.files().create(body=file_metadata, fields="id").execute()
        app_folder_id = app_folder.get("id")
    else:
        app_folder_id = items[0].get("id")

    # Find or create subfolders
    folder_ids = {"app": app_folder_id}
    for name in [uploads_folder_name, transcriptions_folder_name]:
        q = f"name=\'{name}\' and \'{app_folder_id}\' in parents and mimeType=\'application/vnd.google-apps.folder\' and trashed=false"
        results = _service.files().list(q=q, spaces="drive", fields="files(id)").execute()
        items = results.get("files", [])
        if not items:
            file_metadata = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [app_folder_id]}
            folder = _service.files().create(body=file_metadata, fields="id").execute()
            folder_ids[name] = folder.get("id")
        else:
            folder_ids[name] = items[0].get("id")
    return folder_ids

# --- Public API ---

class GDriveStore:
    def __init__(self, credentials_json):
        self.creds = Credentials.from_authorized_user_info(json.loads(credentials_json), SCOPES)
        self.service = get_service(self.creds)
        self.folder_ids = get_folder_ids(self.service, APP_FOLDER_NAME, UPLOADS_FOLDER_NAME, TRANSCRIPTIONS_FOLDER_NAME)
        self.uploads_id = self.folder_ids[UPLOADS_FOLDER_NAME]
        self.transcriptions_id = self.folder_ids[TRANSCRIPTIONS_FOLDER_NAME]

    def list_files(self, folder_id):
        """List all files in a given folder ID."""
        q = f"\'{folder_id}\' in parents and trashed=false"
        results = self.service.files().list(q=q, spaces="drive", fields="files(id, name)").execute()
        return results.get("files", [])

    def download_file(self, file_id, local_path):
        """Download a file from Drive to a local path."""
        request = self.service.files().get_media(fileId=file_id)
        fh = io.FileIO(local_path, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

    def upload_file(self, local_path, folder_id):
        """Upload a local file to a Drive folder."""
        file_metadata = {"name": Path(local_path).name, "parents": [folder_id]}
        media = MediaIoBaseUpload(io.FileIO(local_path, "rb"), mimetype="application/octet-stream", resumable=True)
        file = self.service.files().create(body=file_metadata, media_body=media, fields="id").execute()
        return file.get("id")

    def get_file_content(self, file_id):
        """Get the content of a file as bytes."""
        return self.service.files().get_media(fileId=file_id).execute()
