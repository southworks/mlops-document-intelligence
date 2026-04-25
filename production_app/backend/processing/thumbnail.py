"""
Thumbnail Generation Module
Generates thumbnail images from first page of PDFs using PyMuPDF
"""

import logging
from datetime import datetime, timezone
from io import BytesIO
from azure.storage.blob import BlobServiceClient

try:
    import fitz  # PyMuPDF
    from PIL import Image
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

logger = logging.getLogger(__name__)


def generate_thumbnail(file_bytes: bytes, blob_service_client: BlobServiceClient, 
                       original_filename: str, job_id: str) -> str:
    """
    Generate thumbnail from first page of PDF
    
    Args:
        file_bytes: PDF file bytes
        blob_service_client: Azure Blob Storage client
        original_filename: Original document filename
        job_id: Job identifier for naming
        
    Returns:
        Thumbnail blob path (e.g. "thumbnails/job123_20250106_doc.pdf.jpg") or None if failed
    """
    if not PDF_SUPPORT:
        logger.warning("Thumbnail generation skipped - PyMuPDF not available")
        return None
    
    try:
        logger.info("📸 Generating thumbnail from first page...")
        
        # Open PDF with PyMuPDF
        pdf_document = fitz.open(stream=file_bytes, filetype="pdf")
        
        if pdf_document.page_count == 0:
            logger.warning("PDF has no pages")
            pdf_document.close()
            return None
        
        # Get first page and render as image at 150 DPI
        first_page = pdf_document[0]
        zoom = 150 / 72  # Convert DPI to zoom factor (72 is default)
        mat = fitz.Matrix(zoom, zoom)
        pix = first_page.get_pixmap(matrix=mat)
        
        # Convert pixmap to PIL Image
        img_data = pix.tobytes("png")
        img = Image.open(BytesIO(img_data))
        
        pdf_document.close()
        
        # Resize to thumbnail (max 400px width, maintain aspect ratio)
        img.thumbnail((400, 600), Image.LANCZOS)
        
        # Convert to JPEG bytes
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG', quality=85, optimize=True)
        img_bytes.seek(0)
        
        # Generate thumbnail filename
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        thumbnail_filename = f"{job_id}_{timestamp}_{original_filename}.jpg"
        
        # Ensure thumbnails container exists
        try:
            container_client = blob_service_client.get_container_client("thumbnails")
            container_client.create_container()
            logger.info("Created thumbnails container")
        except Exception:
            pass  # Container already exists
        
        # Upload thumbnail
        thumbnail_blob_client = blob_service_client.get_blob_client(
            container="thumbnails",
            blob=thumbnail_filename
        )
        thumbnail_blob_client.upload_blob(img_bytes.getvalue(), overwrite=True)
        
        thumbnail_url = f"thumbnails/{thumbnail_filename}"
        logger.info(f"✅ Thumbnail generated: {thumbnail_url}")
        
        return thumbnail_url
        
    except Exception as e:
        logger.warning(f"⚠️ Could not generate thumbnail: {str(e)}")
        return None
