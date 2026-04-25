"""API Routes"""

from .upload import router as upload_router
from .jobs import router as jobs_router
from .health import router as health_router

__all__ = ["upload_router", "jobs_router", "health_router"]
