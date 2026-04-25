"""Centralized upload container/path resolution helpers."""

from datetime import datetime, timedelta, timezone
from typing import Optional, Dict

from azure.storage.blob import BlobSasPermissions, BlobServiceClient, generate_blob_sas


class UploadLocation:
    def __init__(self, container_name: str):
        self.container_name = container_name or "documents"
        self.legacy_prefix = "uploads/"

    @property
    def prefix(self) -> str:
        return f"{self.container_name}/"

    def normalize_path(self, blob_path: Optional[str]) -> Optional[str]:
        if not blob_path:
            return None

        if blob_path.startswith(self.prefix):
            return blob_path
        if blob_path.startswith(self.legacy_prefix):
            return f"{self.prefix}{blob_path[len(self.legacy_prefix):]}"
        return f"{self.prefix}{blob_path}"

    def is_upload_path(self, blob_path: Optional[str]) -> bool:
        if not blob_path:
            return False
        return blob_path.startswith(self.prefix) or blob_path.startswith(self.legacy_prefix)

    def extract_blob_name(self, blob_path: str) -> str:
        if blob_path.startswith(self.prefix):
            return blob_path.replace(self.prefix, "", 1)
        if blob_path.startswith(self.legacy_prefix):
            return blob_path.replace(self.legacy_prefix, "", 1)
        return blob_path

    def get_container_client(self, blob_service_client):
        return blob_service_client.get_container_client(self.container_name)

    @staticmethod
    def _parse_connection_string(connection_string: str) -> Dict[str, str]:
        parts: Dict[str, str] = {}
        for segment in connection_string.split(";"):
            if not segment or "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            parts[key.strip()] = value.strip()
        return parts

    def _resolve_storage_identity(
        self,
        account_name: Optional[str],
        account_key: Optional[str],
        connection_string: Optional[str],
    ) -> tuple[str, str, str]:
        resolved_account_name = (account_name or "").strip()
        resolved_account_key = (account_key or "").strip()
        base_url: Optional[str] = None

        if connection_string:
            parsed = self._parse_connection_string(connection_string)
            resolved_account_name = resolved_account_name or parsed.get("AccountName", "").strip()
            resolved_account_key = resolved_account_key or parsed.get("AccountKey", "").strip()
            base_url = parsed.get("BlobEndpoint")

            if not base_url and resolved_account_name:
                endpoint_suffix = parsed.get("EndpointSuffix", "blob.core.windows.net").strip()
                default_protocol = parsed.get("DefaultEndpointsProtocol", "https").strip() or "https"
                base_url = f"{default_protocol}://{resolved_account_name}.blob.{endpoint_suffix}"

            if not resolved_account_name or not resolved_account_key or not base_url:
                blob_service_client = BlobServiceClient.from_connection_string(connection_string)
                resolved_account_name = resolved_account_name or (blob_service_client.account_name or "")
                credential = getattr(blob_service_client, "credential", None)
                resolved_account_key = resolved_account_key or (getattr(credential, "account_key", "") if credential else "")
                base_url = base_url or getattr(blob_service_client, "url", None)

        if not resolved_account_name or not resolved_account_key:
            raise ValueError("Azure Storage account credentials not configured")

        if not base_url:
            base_url = f"https://{resolved_account_name}.blob.core.windows.net"

        return resolved_account_name, resolved_account_key, base_url.rstrip("/")

    def build_read_sas_url(
        self,
        blob_path: str,
        account_name: Optional[str],
        account_key: Optional[str],
        ttl_minutes: int,
        connection_string: Optional[str] = None,
    ) -> str:
        blob_name = self.extract_blob_name(blob_path)
        if not blob_name:
            raise ValueError("Invalid upload blob path")

        resolved_account_name, resolved_account_key, base_url = self._resolve_storage_identity(
            account_name=account_name,
            account_key=account_key,
            connection_string=connection_string,
        )

        sas_token = generate_blob_sas(
            account_name=resolved_account_name,
            container_name=self.container_name,
            blob_name=blob_name,
            account_key=resolved_account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes),
        )

        return f"{base_url}/{self.container_name}/{blob_name}?{sas_token}"
