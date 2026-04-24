"""Azure service mocking fixtures for test suite.

Provides mock implementations of Azure clients used in backend services.
Enables isolated testing without requiring actual Azure resources.
"""

from unittest.mock import MagicMock, patch
from typing import Any, Dict, Optional


class MockBlobContainerClient:
    """Mock implementation of Azure Blob Container Client."""

    def __init__(self, container_name: str = "test-container"):
        self.container_name = container_name
        self.blobs = {}

    def upload_blob(self, name: str, data: bytes, **kwargs) -> Dict[str, Any]:
        """Upload a blob to the container."""
        self.blobs[name] = data
        return {"name": name, "container": self.container_name, "size": len(data)}

    def download_blob(self, blob_name: str) -> "MockBlobDownloader":
        """Download a blob from the container."""
        if blob_name not in self.blobs:
            raise ValueError(f"Blob {blob_name} not found")
        return MockBlobDownloader(self.blobs[blob_name])

    def delete_blob(self, blob_name: str, **kwargs) -> None:
        """Delete a blob from the container."""
        if blob_name in self.blobs:
            del self.blobs[blob_name]

    def list_blobs(self, name_starts_with: Optional[str] = None):
        """List blobs in the container."""
        blobs = []
        for name in self.blobs:
            if name_starts_with is None or name.startswith(name_starts_with):
                blobs.append({"name": name, "size": len(self.blobs[name])})
        return blobs


class MockBlobDownloader:
    """Mock implementation of Azure Blob Downloader."""

    def __init__(self, content: bytes):
        self.content = content

    def readall(self) -> bytes:
        """Read all blob content."""
        return self.content


class MockDocumentAnalysisPoller:
    """Mock implementation of Document Analysis async operation poller."""

    def __init__(self, result: Dict[str, Any]):
        self._result = result

    def result(self) -> Dict[str, Any]:
        """Get the result of the analysis operation."""
        return self._result


class MockDocumentIntelligenceClient:
    """Mock implementation of Azure Document Intelligence Client."""

    def __init__(self):
        self.operations = []

    def begin_analyze_document(self, model_id: str, document, **kwargs) -> MockDocumentAnalysisPoller:
        """Begin analyzing a document."""
        self.operations.append({
            "model_id": model_id,
            "timestamp": "2026-03-26T16:00:00Z"
        })

        # Return mock analysis result
        result = {
            "documents": [
                {
                    "content": "Mock document content",
                    "pages": [
                        {
                            "page_number": 1,
                            "width": 8.5,
                            "height": 11.0,
                        }
                    ],
                }
            ],
            "pages": 1,
        }
        return MockDocumentAnalysisPoller(result)


class MockAzureTableClient:
    """Mock implementation of Azure Table Client for tabular data."""

    def __init__(self, table_name: str = "test-table"):
        self.table_name = table_name
        self.entities = {}

    def create_entity(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Create an entity in the table."""
        partition_key = entity.get("PartitionKey")
        row_key = entity.get("RowKey")
        key = f"{partition_key}#{row_key}"
        self.entities[key] = entity
        return entity

    def get_entity(self, partition_key: str, row_key: str) -> Dict[str, Any]:
        """Get an entity from the table."""
        key = f"{partition_key}#{row_key}"
        if key not in self.entities:
            raise ValueError(f"Entity not found: {key}")
        return self.entities[key]

    def update_entity(self, entity: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        """Update an entity in the table."""
        partition_key = entity.get("PartitionKey")
        row_key = entity.get("RowKey")
        key = f"{partition_key}#{row_key}"
        self.entities[key] = entity
        return entity

    def delete_entity(self, partition_key: str, row_key: str) -> None:
        """Delete an entity from the table."""
        key = f"{partition_key}#{row_key}"
        if key in self.entities:
            del self.entities[key]

    def list_entities(self) -> list:
        """List all entities in the table."""
        return list(self.entities.values())


class MockAzureServiceClient:
    """Base mock for Azure service clients with common patterns."""

    def __init__(self, service_name: str = "MockService"):
        self.service_name = service_name
        self.call_history = []

    def record_call(self, method: str, *args, **kwargs) -> None:
        """Record a method call for testing/verification."""
        self.call_history.append({
            "method": method,
            "args": args,
            "kwargs": kwargs,
        })

    def get_call_count(self, method: str) -> int:
        """Get number of times a method was called."""
        return sum(1 for call in self.call_history if call["method"] == method)

    def reset_history(self) -> None:
        """Clear call history."""
        self.call_history = []
