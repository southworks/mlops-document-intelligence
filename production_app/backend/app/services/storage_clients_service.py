"""Azure Storage clients initialization and management.

Handles creation and safe access to Azure Blob and Table Service clients.
"""

from azure.storage.blob import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError

from app.config import get_settings


def get_blob_client() -> BlobServiceClient:
    """Initialize Azure Blob Storage client.
    
    Returns:
        BlobServiceClient configured from Azure Storage connection string.
        
    Raises:
        ValueError: If Azure Storage connection string is not configured.
    """
    settings = get_settings()
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure Storage connection string not configured")
    return BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)


def get_container_client_safe(blob_client: BlobServiceClient, container_name: str, create_if_missing: bool = False):
    """Get container client safely; optionally create container if missing.
    
    Args:
        blob_client: Initialized BlobServiceClient.
        container_name: Name of the container to access.
        create_if_missing: If True, creates container if it doesn't exist.
        
    Returns:
        Container client if found or created, None if not found and create_if_missing=False.
    """
    container_client = blob_client.get_container_client(container_name)
    try:
        container_client.get_container_properties()
        return container_client
    except ResourceNotFoundError:
        if not create_if_missing:
            return None
        try:
            container_client.create_container()
        except ResourceExistsError:
            pass
        return container_client


