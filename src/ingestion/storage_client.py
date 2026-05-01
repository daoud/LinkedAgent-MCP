from __future__ import annotations

import shutil
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class StorageClient(ABC):
    @abstractmethod
    def upload(self, file_path: Path) -> str:
        """Copy/upload file and return the storage path or URL."""

    @abstractmethod
    def download(self, storage_path: str) -> bytes:
        """Return file contents as bytes."""

    @abstractmethod
    def exists(self, storage_path: str) -> bool:
        """True if the file exists in storage."""

    @abstractmethod
    def delete(self, storage_path: str) -> None:
        """Remove the file from storage."""


class LocalStorageClient(StorageClient):
    """Stores files on the local filesystem under base_dir."""

    def __init__(self, base_dir: str) -> None:
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def upload(self, file_path: Path) -> str:
        src = Path(file_path).resolve()
        dest = self.base_dir / src.name
        if src != dest:
            shutil.copy2(src, dest)
        return str(dest)

    def download(self, storage_path: str) -> bytes:
        return Path(storage_path).read_bytes()

    def exists(self, storage_path: str) -> bool:
        return Path(storage_path).exists()

    def delete(self, storage_path: str) -> None:
        path = Path(storage_path)
        if path.exists():
            path.unlink()


class S3StorageClient(StorageClient):
    """Stores files in AWS S3 (or any S3-compatible store)."""

    def __init__(
        self,
        bucket: str,
        region: str,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
    ) -> None:
        import boto3  # noqa: PLC0415

        self.bucket = bucket
        self._s3 = boto3.client(
            "s3",
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def upload(self, file_path: Path) -> str:
        fp = Path(file_path)
        key = f"uploads/{uuid.uuid4()}/{fp.name}"
        self._s3.upload_file(str(fp), self.bucket, key)
        return f"s3://{self.bucket}/{key}"

    def download(self, storage_path: str) -> bytes:
        bucket, key = _parse_s3_url(storage_path)
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def exists(self, storage_path: str) -> bool:
        try:
            bucket, key = _parse_s3_url(storage_path)
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def delete(self, storage_path: str) -> None:
        bucket, key = _parse_s3_url(storage_path)
        self._s3.delete_object(Bucket=bucket, Key=key)


def _parse_s3_url(url: str) -> tuple[str, str]:
    without_scheme = url.removeprefix("s3://")
    bucket, _, key = without_scheme.partition("/")
    return bucket, key


def get_storage_client(config) -> StorageClient:
    """Factory: returns the correct StorageClient for the configured STORAGE_MODE."""
    if config.storage_mode == "local":
        return LocalStorageClient(config.local_content_dir)
    if config.storage_mode == "s3":
        return S3StorageClient(
            bucket=config.aws_s3_bucket or "",
            region=config.aws_region,
            access_key_id=config.aws_access_key_id,
            secret_access_key=config.aws_secret_access_key,
        )
    if config.storage_mode == "gcs":
        raise NotImplementedError("GCS storage is not yet implemented")
    raise ValueError(f"Unknown STORAGE_MODE: {config.storage_mode!r}")
