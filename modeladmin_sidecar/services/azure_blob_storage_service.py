"""Azure Blob Storage service for training data container access."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from azure.storage.blob import BlobServiceClient, ContainerSasPermissions, generate_container_sas


class AzureBlobStorageService:
    def __init__(self, connection_string: str) -> None:
        self._client = BlobServiceClient.from_connection_string(connection_string)
        self._connection_string = connection_string

    def list_blobs_by_prefix(self, container: str, prefix: str) -> list[str]:
        """Return all blob names under the given prefix in the container."""
        container_client = self._client.get_container_client(container)
        return [b.name for b in container_client.list_blobs(name_starts_with=prefix)]

    def list_available_doc_type_folders(self, container: str) -> list[str]:
        """Return unique folder names (doc types) at the root of the container, excluding hidden folders."""
        container_client = self._client.get_container_client(container)
        doc_types = set()
        for blob in container_client.list_blobs():
            blob_path = blob.name
            # Extract first path segment (folder name)
            if "/" in blob_path:
                folder = blob_path.split("/", 1)[0]
                if folder and not folder.startswith("."):
                    doc_types.add(folder)
        return sorted(doc_types)

    def blob_exists(self, container: str, blob_name: str) -> bool:
        """Return True if the blob exists in the container."""
        blob_client = self._client.get_blob_client(container=container, blob=blob_name)
        return blob_client.exists()

    def download_blob_text(self, container: str, blob_name: str, encoding: str = "utf-8") -> str:
        """Download a blob and return it as decoded text."""
        blob_client = self._client.get_blob_client(container=container, blob=blob_name)
        payload = blob_client.download_blob().readall()
        return payload.decode(encoding)

    def get_container_sas_url(self, container: str, expiry_hours: int = 24) -> str:
        """Return a SAS URL for the container with read+list permissions."""
        account_name = self._client.account_name
        account_key = self._client.credential.account_key

        sas_token = generate_container_sas(
            account_name=account_name,
            container_name=container,
            account_key=account_key,
            permission=ContainerSasPermissions(read=True, list=True),
            expiry=datetime.now(timezone.utc) + timedelta(hours=expiry_hours),
        )
        blob_endpoint = self._client.url.rstrip("/")
        return f"{blob_endpoint}/{container}?{sas_token}"

    def ensure_container(self, container: str) -> None:
        """Ensure the target container exists."""
        container_client = self._client.get_container_client(container)
        if not container_client.exists():
            container_client.create_container()

    def copy_blob(
        self,
        *,
        source_container: str,
        source_blob: str,
        destination_container: str,
        destination_blob: str,
        overwrite: bool = True,
    ) -> None:
        """Copy a blob by downloading then uploading into destination."""
        source_client = self._client.get_blob_client(container=source_container, blob=source_blob)
        payload = source_client.download_blob().readall()
        destination_client = self._client.get_blob_client(
            container=destination_container,
            blob=destination_blob,
        )
        destination_client.upload_blob(payload, overwrite=overwrite)

    def upload_blob(
        self,
        *,
        container: str,
        blob_name: str,
        local_file_path: str,
        overwrite: bool = False,
    ) -> None:
        """Upload a file from local filesystem to blob storage."""
        file_path = Path(local_file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"Local file not found: {local_file_path}")

        with open(file_path, "rb") as file_data:
            blob_client = self._client.get_blob_client(container=container, blob=blob_name)
            blob_client.upload_blob(file_data, overwrite=overwrite)
