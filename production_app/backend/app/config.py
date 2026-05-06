"""
Configuration management using environment variables
"""

from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    # ADI API version
    azure_document_intelligence_api_version: str = "2024-11-30"
    
    # Application
    environment: str = "development"
    debug: bool = True
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Azure Storage (required)
    azure_storage_connection_string: Optional[str] = None
    azure_storage_container_name: str = "documents"
    
    # Database
    database_url: str = "sqlite:///./invoice_ocr.db"
    
    # Webhooks
    webhook_enabled: bool = False
    
    # Azure Document Intelligence
    azure_document_intelligence_endpoint: Optional[str] = None
    azure_document_intelligence_key: Optional[str] = None
    azure_compose_model_id: Optional[str] = None  # Compose model ID (e.g., "procurement-compose-model.v2")
    document_intelligence_sas_ttl_minutes: int = 5

    # ModelAdmin Candidate Intake
    modeladmin_enabled: bool = True
    modeladmin_confidence_threshold: float = 0.75
    modeladmin_always_flag_unknown: bool = True
    modeladmin_external_endpoint: Optional[str] = None
    modeladmin_external_timeout_seconds: int = 5
    modeladmin_external_retry_attempts: int = 2
    modeladmin_external_retry_backoff_ms: int = 200
    modeladmin_external_api_key: Optional[str] = None
    
    # PO Matching Configuration
    matching_tolerance_percentage: float = 5.0  # ±5%
    matching_tolerance_fixed: float = 50.0      # ±$50
    matching_line_item_tolerance_pct: float = 2.0  # ±2% per line item
    matching_line_item_tolerance_fixed: float = 10.0  # ±$10 per line item
    matching_description_similarity: float = 0.80  # 80% similarity threshold
    
    model_config = ConfigDict(env_file="../.env", case_sensitive=False)


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Convenience function
def is_azure_storage_configured() -> bool:
    """Check if Azure Storage is properly configured"""
    settings = get_settings()
    return settings.azure_storage_connection_string is not None
