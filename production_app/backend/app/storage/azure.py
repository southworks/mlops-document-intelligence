"""Azure Blob Storage adapter"""

import logging
from typing import BinaryIO, Optional, List
from azure.storage.blob.aio import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError
from .base import StorageAdapter

logger = logging.getLogger(__name__)


class AzureBlobStorage(StorageAdapter):
    """Storage adapter for Azure Blob Storage"""
    
    def __init__(self, connection_string: str, container_name: str):
        self.connection_string = connection_string
        self.container_name = container_name
        self._client: Optional[BlobServiceClient] = None
    
    async def _get_client(self) -> BlobServiceClient:
        """Get or create Azure Blob Service Client"""
        if self._client is None:
            self._client = BlobServiceClient.from_connection_string(self.connection_string)
            # Ensure container exists
            try:
                container_client = self._client.get_container_client(self.container_name)
                if not await container_client.exists():
                    await container_client.create_container()
            except Exception as e:
                logger.warning("Could not verify/create container: %s", e)
        return self._client
    
    def _get_blob_name(self, file_path: str) -> str:
        """Get blob name from file path"""
        return file_path.lstrip('/')
    
    async def upload(self, file: BinaryIO, filename: str, folder: Optional[str] = None) -> str:
        """Upload file to Azure Blob Storage"""
        # Create blob name with folder structure
        if folder:
            blob_name = f"{folder}/{filename}"
        else:
            blob_name = filename
        
        # Read content
        content = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)
        
        # Upload to Azure
        client = await self._get_client()
        blob_client = client.get_blob_client(container=self.container_name, blob=blob_name)
        
        await blob_client.upload_blob(content, overwrite=True)
        
        return blob_name
    
    async def download(self, file_path: str) -> bytes:
        """Download file from Azure Blob Storage"""
        blob_name = self._get_blob_name(file_path)
        
        client = await self._get_client()
        blob_client = client.get_blob_client(container=self.container_name, blob=blob_name)
        
        try:
            stream = await blob_client.download_blob()
            return await stream.readall()
        except ResourceNotFoundError:
            raise FileNotFoundError(f"Blob not found: {file_path}")
    
    async def delete(self, file_path: str) -> bool:
        """Delete file from Azure Blob Storage"""
        blob_name = self._get_blob_name(file_path)
        
        client = await self._get_client()
        blob_client = client.get_blob_client(container=self.container_name, blob=blob_name)
        
        try:
            await blob_client.delete_blob()
            return True
        except ResourceNotFoundError:
            return False
        except Exception as e:
            logger.error("Error deleting blob %s: %s", file_path, e)
            return False
    
    async def exists(self, file_path: str) -> bool:
        """Check if file exists in Azure Blob Storage"""
        blob_name = self._get_blob_name(file_path)
        
        client = await self._get_client()
        blob_client = client.get_blob_client(container=self.container_name, blob=blob_name)
        
        return await blob_client.exists()
    
    def get_url(self, file_path: str) -> str:
        """Get Azure Blob URL"""
        blob_name = self._get_blob_name(file_path)
        # Construct blob URL
        account_name = self.connection_string.split('AccountName=')[1].split(';')[0]
        return f"https://{account_name}.blob.core.windows.net/{self.container_name}/{blob_name}"
    
    async def upload_bytes(self, content: bytes, file_path: str) -> str:
        """Upload raw bytes directly to Azure Blob Storage"""
        blob_name = self._get_blob_name(file_path)
        
        client = await self._get_client()
        blob_client = client.get_blob_client(container=self.container_name, blob=blob_name)
        
        await blob_client.upload_blob(content, overwrite=True)
        
        return blob_name
    
    async def list_files(self, prefix: str = "") -> List[str]:
        """List all blobs matching the given prefix"""
        client = await self._get_client()
        container_client = client.get_container_client(self.container_name)
        
        files = []
        
        # List blobs with name starting with prefix
        async for blob in container_client.list_blobs(name_starts_with=prefix):
            files.append(blob.name)
        
        return sorted(files)
    
    async def close(self):
        """Close the client connection"""
        if self._client:
            await self._client.close()
