"""Health check and utility endpoints"""

from fastapi import APIRouter
from app.config import get_settings, is_azure_storage_configured
from app.database import engine
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])
settings = get_settings()


@router.get("/")
async def health_check():
    """
    Comprehensive health check endpoint
    
    Returns system status including:
    - API status
    - Database connectivity
    - Tesseract availability
    - Storage configuration
    """
    
    # Check database
    db_status = "healthy"
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        
    # Storage info
    storage_info = {
        "type": "Azure Blob Storage",
        "configured": is_azure_storage_configured()
    }
    
    return {
        "status": "healthy" if db_status == "healthy" else "degraded",
        "environment": settings.environment,
        "database": db_status,
        "storage": storage_info,
        "tesseract": {"delegated": True, "note": "OCR moved to Azure Functions"},
        "webhooks_enabled": settings.webhook_enabled
    }
