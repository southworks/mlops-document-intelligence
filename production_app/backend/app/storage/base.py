"""Base storage interface"""

from abc import ABC, abstractmethod
from typing import BinaryIO, Optional, List
from pathlib import Path


class StorageAdapter(ABC):
    """Abstract base class for storage adapters"""
    
    @abstractmethod
    async def upload(self, file: BinaryIO, filename: str, folder: Optional[str] = None) -> str:
        """
        Upload a file to storage
        
        Args:
            file: File-like object to upload
            filename: Name of the file
            folder: Optional folder/prefix for the file
            
        Returns:
            Full path/URL to the uploaded file
        """
        pass
    
    @abstractmethod
    async def upload_bytes(self, content: bytes, file_path: str) -> str:
        """
        Upload bytes directly to storage
        
        Args:
            content: File content as bytes
            file_path: Full path where to save the file
            
        Returns:
            Full path/URL to the uploaded file
        """
        pass
    
    @abstractmethod
    async def download(self, file_path: str) -> bytes:
        """
        Download a file from storage
        
        Args:
            file_path: Path to the file in storage
            
        Returns:
            File content as bytes
        """
        pass
    
    @abstractmethod
    async def delete(self, file_path: str) -> bool:
        """
        Delete a file from storage
        
        Args:
            file_path: Path to the file in storage
            
        Returns:
            True if successful, False otherwise
        """
        pass
    
    @abstractmethod
    async def exists(self, file_path: str) -> bool:
        """
        Check if a file exists in storage
        
        Args:
            file_path: Path to the file in storage
            
        Returns:
            True if exists, False otherwise
        """
        pass
    
    @abstractmethod
    async def list_files(self, prefix: str = "") -> List[str]:
        """
        List all files with given prefix
        
        Args:
            prefix: Folder/prefix to filter files
            
        Returns:
            List of file paths
        """
        pass
    
    @abstractmethod
    def get_url(self, file_path: str) -> str:
        """
        Get a URL to access the file
        
        Args:
            file_path: Path to the file in storage
            
        Returns:
            URL or path string
        """
        pass
