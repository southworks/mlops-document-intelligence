"""FastAPI application with Azure integration"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import get_settings
from app.database import init_db
from app.model_registry import initialize_from_config
from app.routes import upload_router, jobs_router, health_router
from app.routes.documents import router as documents_router

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application lifespan events"""
    # Startup
    print("🚀 Starting Invoice OCR API...")
    print(f"Environment: {settings.environment}")
    print("Storage: Azure Blob Storage")

    # Initialize database
    init_db()
    print("✓ Database initialized")

    # Initialize model registry from config
    initialize_from_config(compose_model_id=settings.azure_compose_model_id)
    print("✓ Model registry initialized")

    yield

    # Shutdown
    print("👋 Shutting down Invoice OCR API...")


# Create FastAPI app
app = FastAPI(
    title="Invoice OCR API with Azure",
    description="OCR service for processing invoices with Azure Blob Storage integration",
    version="2.0.0",
    lifespan=lifespan
)

class HTTPSRedirectMiddleware(BaseHTTPMiddleware):
    """Ensure redirects use HTTPS when behind a proxy"""
    async def dispatch(self, request: Request, call_next):
        # Check if request came via HTTPS proxy
        proto = request.headers.get("x-forwarded-proto", "http")
        if proto == "https":
            request.scope["scheme"] = "https"
        response = await call_next(request)
        return response

app.add_middleware(HTTPSRedirectMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(upload_router)
app.include_router(jobs_router)
app.include_router(documents_router)

@app.get("/")
async def root():
    """Root endpoint with API information"""
    return {
        "name": "Document Processing API",
        "version": "2.0.0",
        "environment": settings.environment,
        "storage": "Azure Blob Storage",
        "related_services": {
            "modeladmin": settings.modeladmin_external_endpoint or "external-service",
        },
        "endpoints": {
            "/health": "System health check",
            "/upload": "Upload document for processing",
            "/jobs/{job_id}": "Get job status and results",
            "/jobs": "List all jobs",
            "/documents": "List all documents (invoices, POs, unknown)",
            "/documents/{blob_name}": "Get document details",
            "/docs": "Interactive API documentation"
        }
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
