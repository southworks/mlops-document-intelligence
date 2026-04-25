"""SAS URL generation and URL validation helpers.

Provides utilities for generating secure SAS URLs for Azure Storage access
and validating whether URLs are publicly accessible or locally scoped.
"""

import ipaddress
from urllib.parse import urlparse

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
    """Generate a read SAS URL for a blob path across supported containers.

    Supports:
    - uploads/documents paths in configured upload container
    - thumbnail paths under the thumbnails container
    """
    settings = get_settings()
    if not settings.azure_storage_connection_string:
        raise ValueError("Azure Storage account credentials not configured")

    if blob_path.startswith("thumbnails/"):
        thumbnails_location = UploadLocation("thumbnails")
        target_blob_path = blob_path.replace("thumbnails/", "", 1)
        return thumbnails_location.build_read_sas_url(
            blob_path=target_blob_path,
            account_name=None,
            account_key=None,
            ttl_minutes=ttl_minutes,
            connection_string=settings.azure_storage_connection_string,
        )

    upload_location = UploadLocation(settings.azure_storage_container_name)
    return upload_location.build_read_sas_url(
        blob_path=blob_path,
        account_name=None,
        account_key=None,
        ttl_minutes=ttl_minutes,
        connection_string=settings.azure_storage_connection_string,
    )


def is_publicly_fetchable_url(url: str) -> bool:
    """Check whether a URL is publicly accessible (not local/private).
    
    Returns False for localhost, private IPs, link-local, and reserved addresses.
    Returns True for public Internet URLs.
    
    Args:
        url: URL to validate.
        
    Returns:
        True if URL is publicly accessible, False if local/private.
    """
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()

    if not host:
        return False

    local_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "azurite-service",
        "host.docker.internal",
    }
    if host in local_hosts:
        return False

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return False
    except ValueError:
        pass

    return True
