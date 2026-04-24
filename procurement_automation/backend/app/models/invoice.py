"""Invoice data models"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date
from decimal import Decimal


class InvoiceItem(BaseModel):
    """Individual line item in an invoice"""
    description: str
    quantity: Optional[float] = None
    unit_price: Optional[Decimal] = None
    total: Optional[Decimal] = None


class InvoiceData(BaseModel):
    """Structured invoice data extracted from OCR"""
    invoice_number: Optional[str] = None
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    
    # Vendor information
    vendor_name: Optional[str] = None
    vendor_address: Optional[str] = None
    vendor_tax_id: Optional[str] = None
    vendor_phone: Optional[str] = None
    
    # Customer/Bill To information
    customer_name: Optional[str] = None
    customer_address: Optional[str] = None
    customer_tax_id: Optional[str] = None
    
    # Financial data
    subtotal: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    tax_rate: Optional[float] = None
    total_amount: Optional[Decimal] = None
    currency: Optional[str] = "USD"
    
    # Line items
    items: List[InvoiceItem] = Field(default_factory=list)
    
    # Payment information
    payment_method: Optional[str] = None
    payment_status: Optional[str] = None


class Invoice(BaseModel):
    """Complete invoice model including raw OCR text"""
    job_id: str
    filename: str
    file_type: str
    raw_text: str
    structured_data: Optional[InvoiceData] = None
    confidence_score: Optional[float] = None  # 0-100
    pages: Optional[int] = None
    processing_time_seconds: Optional[float] = None
