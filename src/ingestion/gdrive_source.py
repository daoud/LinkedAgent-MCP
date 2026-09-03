"""Pull new post files from a Google Drive folder.

Uses the same service-account credentials JSON as the Sheets approval
integration (``GOOGLE_SHEETS_CREDENTIALS_FILE``) — just add the Drive
read-only scope and share the target folder with the service-account email.

Google Docs in the folder are exported as plain text; uploaded .md/.txt/.pdf
/.docx files are downloaded as-is. Each file is imported once, keyed by its
Drive file id (stored on ``content_uploads.external_id``).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Drive mime -> (export mime, extension) for native Google types
_EXPORT = {
    "application/vnd.google-apps.document": ("text/plain", ".txt"),
}
_KEEP_EXT = {".md", ".markdown", ".txt", ".pdf", ".doc", ".docx"}


@dataclass
class DriveFile:
    file_id: str
    name: str
    data: bytes
    mime_type: str


class GDriveSource:
    def __init__(self, folder_id: str, credentials_file: str) -> None:
        self.folder_id = folder_id
        self._credentials_file = credentials_file
        self._svc = None

    def _service(self):
        if self._svc is not None:
            return self._svc
        from google.oauth2.service_account import Credentials  # noqa: PLC0415
        from googleapiclient.discovery import build  # noqa: PLC0415

        creds = Credentials.from_service_account_file(self._credentials_file, scopes=_SCOPES)
        self._svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._svc

    def list_files(self) -> list[dict]:
        """Return metadata for every non-trashed file directly in the folder."""
        svc = self._service()
        out: list[dict] = []
        page_token = None
        while True:
            resp = (
                svc.files()
                .list(
                    q=f"'{self.folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
                    pageSize=200,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            out.extend(resp.get("files", []))
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return out

    def fetch_new(self, known_ids: set[str]) -> list[DriveFile]:
        """Download files whose id is not in *known_ids*. Skips folders/unsupported."""
        from pathlib import PurePosixPath  # noqa: PLC0415

        from googleapiclient.http import MediaIoBaseDownload  # noqa: PLC0415

        svc = self._service()
        new: list[DriveFile] = []
        for meta in self.list_files():
            fid = meta["id"]
            if fid in known_ids:
                continue
            mime = meta.get("mimeType", "")
            name = meta.get("name", fid)
            ext = PurePosixPath(name).suffix.lower()

            if mime == "application/vnd.google-apps.folder":
                continue
            if mime in _EXPORT:
                export_mime, add_ext = _EXPORT[mime]
                request = svc.files().export_media(fileId=fid, mimeType=export_mime)
                if not name.lower().endswith(add_ext):
                    name = name + add_ext
                out_mime = export_mime
            elif ext in _KEEP_EXT or mime.startswith("text/"):
                request = svc.files().get_media(fileId=fid, supportsAllDrives=True)
                out_mime = mime or "text/plain"
            else:
                continue  # image / sheet / slide / unknown — not a post

            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
            new.append(DriveFile(file_id=fid, name=name, data=buf.getvalue(), mime_type=out_mime))
        return new
