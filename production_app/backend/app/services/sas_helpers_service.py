"""SAS URL generation helpers.

Provides utilities for generating secure SAS URLs for Azure Storage access.
"""

from app.config import get_settings
from app.services.upload_location import UploadLocation


def build_upload_blob_sas_url(blob_path: str) -> str:
    """Generate SAS URL for blob access.
    
    Args:
        blob_path: Path to the blob (e.g., "documents/file.pdf").
        
    Returns:
        SAS URL with read access and TTL configured from settings.
        
    Raises:
        ValueError: If Azure Storage credentials not configured.
    """
    settings = get_settings()
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure Storage account credentials not configured")

    upload_location = UploadLocation(settings.azure_storage_container_name)
    return upload_location.build_read_sas_url(
        blob_path=blob_path,
        account_name=None,
        account_key=None,
        ttl_minutes=settings.document_intelligence_sas_ttl_minutes,
        connection_string=settings.azure_storage_connection_string,
    )


def build_read_sas_url_for_blob_path(blob_path: str, ttl_minutes: int = 60) -> str:
    """Generate a read SAS URL for a blob path in the configured upload container."""
    settings = get_settings()
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure Storage account credentials not configured")

    upload_location = UploadLocation(settings.azure_storage_container_name)
    return upload_location.build_read_sas_url(
        blob_path=blob_path,
        account_name=None,
        account_key=None,
        ttl_minutes=ttl_minutes,
        connection_string=settings.azure_storage_connection_string,
    )
