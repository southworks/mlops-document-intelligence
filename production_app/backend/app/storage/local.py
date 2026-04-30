"""Local filesystem storage adapter"""

import logging
import aiofiles
import os
from pathlib import Path
from typing import BinaryIO, Optional, List
from .base import StorageAdapter

logger = logging.getLogger(__name__)


class LocalStorage(StorageAdapter):
    """Storage adapter for local filesystem"""
    
    def __init__(self, base_path: str = "./storage/documents"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
    
    def _get_full_path(self, file_path: str) -> Path:
        """Get full filesystem path"""
        return self.base_path / file_path
    
    async def upload(self, file: BinaryIO, filename: str, folder: Optional[str] = None) -> str:
        """Upload file to local storage"""
        # Create folder structure
        if folder:
            folder_path = self.base_path / folder
            folder_path.mkdir(parents=True, exist_ok=True)
            file_path = f"{folder}/{filename}"
        else:
            file_path = filename
        
        full_path = self._get_full_path(file_path)
        
        # Read content from file object
        content = file.read()
        if hasattr(file, 'seek'):
            file.seek(0)  # Reset file pointer
        
        # Write file asynchronously
        async with aiofiles.open(full_path, 'wb') as f:
            await f.write(content)
        
        return file_path
    
    async def download(self, file_path: str) -> bytes:
        """Download file from local storage"""
        full_path = self._get_full_path(file_path)
        
        if not full_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        
        async with aiofiles.open(full_path, 'rb') as f:
            return await f.read()
    
    async def delete(self, file_path: str) -> bool:
        """Delete file from local storage"""
        full_path = self._get_full_path(file_path)
        
        try:
            if full_path.exists():
                full_path.unlink()
                return True
            return False
        except Exception as e:
            logger.error("Error deleting file %s: %s", file_path, e)
            return False
    
    async def exists(self, file_path: str) -> bool:
        """Check if file exists in local storage"""
        full_path = self._get_full_path(file_path)
        return full_path.exists()
    
    def get_url(self, file_path: str) -> str:
        """Get file path (for local storage, returns the path)"""
        return str(self._get_full_path(file_path))
    
    async def upload_bytes(self, content: bytes, file_path: str) -> str:
        """Upload raw bytes directly to storage"""
        full_path = self._get_full_path(file_path)
        
        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write bytes asynchronously
        async with aiofiles.open(full_path, 'wb') as f:
            await f.write(content)
        
        return file_path
    
    async def list_files(self, prefix: str = "") -> List[str]:
        """List all files matching the given prefix"""
        prefix_path = self.base_path / prefix
        
        # If prefix doesn't exist as a directory, return empty list
        if not prefix_path.exists():
            return []
        
        files = []
        
        # If it's a directory, list all files recursively
        if prefix_path.is_dir():
            for root, _, filenames in os.walk(prefix_path):
                for filename in filenames:
                    full_file_path = Path(root) / filename
                    # Get relative path from base_path
                    relative_path = full_file_path.relative_to(self.base_path)
                    files.append(str(relative_path))
        # If it's a file, return just that file
        elif prefix_path.is_file():
            relative_path = prefix_path.relative_to(self.base_path)
            files.append(str(relative_path))
        
        return sorted(files)
