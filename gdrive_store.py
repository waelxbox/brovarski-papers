import io
import json
import time
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from google.oauth2.credentials import Credentials

INDEX_FILENAME = "_index.json"

class GDriveStore:
    def __init__(self, credentials_info):
        self.creds = Credentials.from_authorized_user_info(
            credentials_info,
            scopes=['https://www.googleapis.com/auth/drive']
        )
        self.service = build('drive', 'v3', credentials=self.creds)

        self.root_folder_name = "Brovarski_Papers_App"
        self.uploads_folder_name = "uploads"
        self.transcriptions_folder_name = "transcriptions"

        self._ensure_folders()

        # In-process file list cache: {folder_id: (timestamp, [files])}
        self._list_cache: dict = {}
        self._list_ttl = 60  # seconds

    def _ensure_folders(self):
        """Ensure the app folder structure exists in Google Drive."""
        self.root_id = self._get_or_create_folder(self.root_folder_name)
        self.uploads_id = self._get_or_create_folder(self.uploads_folder_name, self.root_id)
        self.transcriptions_id = self._get_or_create_folder(self.transcriptions_folder_name, self.root_id)

    def _get_or_create_folder(self, name, parent_id=None):
        query = f"name = '{name}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = self.service.files().list(q=query, fields="files(id, name)").execute()
        files = results.get('files', [])

        if files:
            return files[0]['id']

        file_metadata = {
            'name': name,
            'mimeType': 'application/vnd.google-apps.folder'
        }
        if parent_id:
            file_metadata['parents'] = [parent_id]

        file = self.service.files().create(body=file_metadata, fields='id').execute()
        return file.get('id')

    def list_files(self, folder_id):
        """List files with a 60-second in-process cache to avoid hammering the API."""
        now = time.time()
        cached = self._list_cache.get(folder_id)
        if cached and (now - cached[0]) < self._list_ttl:
            return cached[1]

        query = f"'{folder_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields="files(id, name)", pageSize=1000).execute()
        files = results.get('files', [])
        self._list_cache[folder_id] = (now, files)
        return files

    def invalidate_list_cache(self):
        self._list_cache.clear()

    def get_file_content(self, file_id):
        request = self.service.files().get_media(fileId=file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return fh.getvalue()

    def upload_file(self, name, content, folder_id, mime_type='application/octet-stream'):
        """Upload a file, updating it in place if it already exists."""
        query = f"name = '{name}' and '{folder_id}' in parents and trashed = false"
        results = self.service.files().list(q=query, fields="files(id)").execute()
        existing = results.get('files', [])

        media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=True)

        if existing:
            file_id = existing[0]['id']
            f = self.service.files().update(fileId=file_id, media_body=media).execute()
        else:
            file_metadata = {'name': name, 'parents': [folder_id]}
            f = self.service.files().create(body=file_metadata, media_body=media).execute()

        self.invalidate_list_cache()
        return f.get('id', existing[0]['id'] if existing else None)

    # Aliases used by data_store.py
    def upload_bytes(self, name, data, folder_id, mimetype='application/octet-stream'):
        return self.upload_file(name, data, folder_id, mime_type=mimetype)

    def upsert_json(self, name, data, folder_id):
        content = json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8')
        return self.upload_file(name, content, folder_id, mime_type='application/json')
