from __future__ import annotations

import os
from functools import lru_cache


class SecretsBackend:
    def get(self, key: str, default: str | None = None) -> str | None:
        raise NotImplementedError


class EnvSecretsBackend(SecretsBackend):
    def get(self, key: str, default: str | None = None) -> str | None:
        return os.environ.get(key, default)


class AWSSecretsBackend(SecretsBackend):
    def __init__(self, region: str = "us-east-1") -> None:
        import boto3

        self._client = boto3.client("secretsmanager", region_name=region)
        self._cache: dict[str, str] = {}

    def get(self, key: str, default: str | None = None) -> str | None:
        if key in self._cache:
            return self._cache[key]
        try:
            response = self._client.get_secret_value(SecretId=key)
            value: str = response.get("SecretString", default)
            self._cache[key] = value
            return value
        except Exception:
            return default


class GCPSecretsBackend(SecretsBackend):
    def __init__(self, project_id: str) -> None:
        from google.cloud import secretmanager

        self._client = secretmanager.SecretManagerServiceClient()
        self._project_id = project_id
        self._cache: dict[str, str] = {}

    def get(self, key: str, default: str | None = None) -> str | None:
        if key in self._cache:
            return self._cache[key]
        try:
            name = f"projects/{self._project_id}/secrets/{key}/versions/latest"
            response = self._client.access_secret_version(request={"name": name})
            value = response.payload.data.decode("utf-8")
            self._cache[key] = value
            return value
        except Exception:
            return default


def _make_backend() -> SecretsBackend:
    backend = os.getenv("SECRETS_BACKEND", "env").lower()
    if backend == "aws":
        return AWSSecretsBackend(region=os.getenv("AWS_REGION", "us-east-1"))
    if backend == "gcp":
        return GCPSecretsBackend(project_id=os.getenv("GCP_PROJECT_ID", ""))
    return EnvSecretsBackend()


@lru_cache
def get_secrets() -> SecretsBackend:
    return _make_backend()


def get_secret(key: str, default: str | None = None) -> str | None:
    return get_secrets().get(key, default)
