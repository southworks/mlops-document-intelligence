"""Configuration for ModelAdmin dedicated service runtime."""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings

DEFAULT_MODELADMIN_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/mlops_modeladmin"


class ModelAdminServiceSettings(BaseSettings):
    service_name: str = "modeladmin-service"
    service_version: str = "v1"
    service_host: str = "0.0.0.0"
    service_port: int = 8100
    environment: str = "development"
    boundary_api_key: str = ""
    modeladmin_database_url: str = DEFAULT_MODELADMIN_DATABASE_URL
    adi_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "ADI_ENDPOINT"),
    )
    adi_key: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_DOCUMENT_INTELLIGENCE_KEY", "ADI_KEY"),
    )
    azure_storage_connection_string: str = Field(
        default="",
        validation_alias=AliasChoices("AZURE_STORAGE_CONNECTION_STRING"),
    )
    training_data_container: str = Field(
        default="training-data",
        validation_alias=AliasChoices("TRAINING_DATA_CONTAINER", "MODELADMIN_TRAINING_DATA_CONTAINER"),
    )
    confidence_threshold_invoice: float = Field(
        default=0.70,
        validation_alias=AliasChoices("CONFIDENCE_THRESHOLD_INVOICE"),
    )
    confidence_threshold_po: float = Field(
        default=0.70,
        validation_alias=AliasChoices("CONFIDENCE_THRESHOLD_PO"),
    )
    confidence_threshold_grn: float = Field(
        default=0.70,
        validation_alias=AliasChoices("CONFIDENCE_THRESHOLD_GRN"),
    )


@lru_cache()
def get_modeladmin_sidecar_settings() -> ModelAdminServiceSettings:
    return ModelAdminServiceSettings()
