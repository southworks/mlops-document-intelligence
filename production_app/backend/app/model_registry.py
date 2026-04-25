"""
Model Registry for Dynamic Model Version Management
Allows updating model versions without restarting the backend
"""

import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    Central registry for ADI model IDs with version management
    
    Allows hot-swapping model versions without backend restart
    """
    
    def __init__(self):
        self._models = {
            "compose": {
                "current": None,
                "versions": {},
                "last_updated": None
            }
        }
    
    def register_model(self, model_type: str, version: str, model_id: str):
        """Register a model version"""
        if model_type not in self._models:
            self._models[model_type] = {
                "current": None,
                "versions": {},
                "last_updated": None
            }
        
        self._models[model_type]["versions"][version] = model_id
        self._models[model_type]["last_updated"] = datetime.now(timezone.utc).isoformat()
        
        logger.info(f"✅ Registered {model_type} model: {version} → {model_id}")
    
    def set_active_version(self, model_type: str, version: str):
        """Set the active version for a model type"""
        if model_type not in self._models:
            raise ValueError(f"Unknown model type: {model_type}")
        
        if version not in self._models[model_type]["versions"]:
            raise ValueError(f"Unknown version: {version} for {model_type}")
        
        self._models[model_type]["current"] = version
        logger.info(f"🔄 Activated {model_type} version: {version}")
    
    def get_active_model_id(self, model_type: str) -> Optional[str]:
        """Get the currently active model ID for a type"""
        if model_type not in self._models:
            return None
        
        current_version = self._models[model_type]["current"]
        if not current_version:
            return None
        
        return self._models[model_type]["versions"].get(current_version)
    
    def get_all_versions(self, model_type: str) -> dict:
        """Get all registered versions for a model type"""
        if model_type not in self._models:
            return {}
        
        return self._models[model_type]["versions"].copy()
    
    def get_registry_status(self) -> dict:
        """Get complete registry status"""
        return {
            model_type: {
                "current_version": data["current"],
                "current_model_id": data["versions"].get(data["current"]) if data["current"] else None,
                "available_versions": list(data["versions"].keys()),
                "last_updated": data["last_updated"]
            }
            for model_type, data in self._models.items()
        }


# Global singleton
_registry = None


def get_model_registry() -> ModelRegistry:
    """Get or create the global model registry"""
    global _registry
    if _registry is None:
        _registry = ModelRegistry()
    return _registry


def initialize_from_config(compose_model_id: Optional[str]):
    """Initialize registry from configuration"""
    registry = get_model_registry()
    
    if compose_model_id:
        # Extract version from model ID (e.g., "procurement-compose-model.v2" → "v2")
        if ".v" in compose_model_id:
            version = compose_model_id.split(".v")[-1]
            version = f"v{version}"
        else:
            version = "v1"
        
        registry.register_model("compose", version, compose_model_id)
        registry.set_active_version("compose", version)
    
    logger.info("✅ Model registry initialized")
