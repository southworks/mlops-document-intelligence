"""Storage service factory - Azure Blob Storage only"""

from typing import Optional
from .base import StorageAdapter
from .azure import AzureBlobStorage
from app.config import get_settings


def get_storage(container: Optional[str] = None) -> StorageAdapter:
    """
    Factory function to get the Azure Blob Storage adapter

    Args:
        container: Optional container override (uses this container name instead of the default)

    Returns:
        AzureBlobStorage instance
    """
    settings = get_settings()
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure storage connection string is missing")
    return AzureBlobStorage(
        connection_string=settings.azure_storage_connection_string,
        container_name=container if container else settings.azure_storage_container_name,
    )


__all__ = ["StorageAdapter", "AzureBlobStorage", "get_storage"]
