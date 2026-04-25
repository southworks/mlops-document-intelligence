"""Document repository for accessing processed documents from blob storage"""

from typing import Dict, List, Optional
import json

from app.config import get_settings
from app.storage import get_storage

settings = get_settings()
container_name = settings.azure_storage_container_name

class DocumentRepository:
    """Repository for accessing document data from blob storage"""
    
    def __init__(self):
        """Initialize document repository with storage backend"""
        self.storage = get_storage(container=container_name)
    
    @staticmethod
    def _extract_value(field: any) -> any:
        """Extract value from Azure Document Intelligence format {value, confidence}"""
        if field is None:
            return None
        if isinstance(field, dict) and "value" in field:
            return field["value"]
        return field
    
    async def get_document_by_blob_name(self, blob_name: str) -> Optional[Dict]:
        """
        Get document data by blob name
        
        Args:
            blob_name: Full blob path (e.g., "invoice/abc123.json")
            
        Returns:
            Document data or None if not found
        """
        try:
            # Download from storage
            content = await self.storage.download(blob_name)
            
            # Parse JSON
            doc_data = json.loads(content)
            return doc_data
        except Exception as e:
            print(f"Error loading document {blob_name}: {str(e)}")
            return None
    
    async def get_documents_by_type(
        self,
        doc_type: str
    ) -> List[Dict]:
        """
        Get all documents of a specific type
        
        Args:
            doc_type: Document type (invoice, purchase-order, unknown)
            
        Returns:
            List of documents
        """
        try:
            # Map type to folder
            folder_map = {
                "invoice": "invoices",
                "purchase-order": "purchase-orders",
                "goods-receipt-note": "goods-receipt-notes",
                "unknown": "unknown"
            }
            folder = folder_map.get(doc_type, doc_type)
            
            # Azure Storage mode
            blob_names = await self.storage.list_files(prefix=folder)

            documents = []
            for blob_name in blob_names:
                try:
                    content = await self.storage.download(blob_name)
                    doc_data = json.loads(content)
                    doc_data['blob_name'] = blob_name
                    documents.append(doc_data)
                except Exception as e:
                    print(f"Error loading document {blob_name}: {str(e)}")
                    continue

            return documents

        except Exception as e:
            print(f"Error getting documents by type {doc_type}: {str(e)}")
            return []
    

    async def find_by_po_number(self, po_number: str) -> List[Dict]:
        """
        Find all documents (invoices and POs) with a specific PO number
        
        Args:
            po_number: Purchase order number to search for
            
        Returns:
            List of documents matching the PO number
        """
        results = []
        
        # Search in purchase orders
        pos = await self.get_documents_by_type("purchase-order")
        for po in pos:
            structured_data = po.get("structured_data", {})
            po_num = self._extract_value(structured_data.get("po_number"))
            if po_num == po_number:
                results.append({
                    "blob_name": po.get("blob_name"),
                    "document_type": "purchase-order",
                    "data": po
                })
        
        # Search in invoices (check for po_reference or po_number)
        invoices = await self.get_documents_by_type("invoice")
        for invoice in invoices:
            structured_data = invoice.get("structured_data", {})
            # Check both po_reference and po_number fields
            inv_po_ref = (
                self._extract_value(structured_data.get("po_reference")) or 
                self._extract_value(structured_data.get("po_number"))
            )
            if inv_po_ref == po_number:
                results.append({
                    "blob_name": invoice.get("blob_name"),
                    "document_type": "invoice",
                    "data": invoice
                })
        
        return results
    
    async def find_invoice_by_number(self, invoice_number: str) -> Optional[Dict]:
        """
        Find an invoice by invoice number
        
        Args:
            invoice_number: Invoice number to search for
            
        Returns:
            Invoice document or None if not found
        """
        invoices = await self.get_documents_by_type("invoice")
        for invoice in invoices:
            structured_data = invoice.get("structured_data", {})
            inv_num = self._extract_value(structured_data.get("invoice_number"))
            if inv_num == invoice_number:
                return invoice
        return None
    
    async def find_po_by_number(self, po_number: str) -> Optional[Dict]:
        """
        Find a purchase order by PO number

        Args:
            po_number: PO number to search for

        Returns:
            PO document or None if not found
        """
        purchase_orders = await self.get_documents_by_type("purchase-order")
        for po in purchase_orders:
            structured_data = po.get("structured_data", {})
            po_num = self._extract_value(structured_data.get("po_number"))
            if po_num == po_number:
                return po
        return None

    async def find_grn_by_po_reference(self, po_reference: str) -> Optional[Dict]:
        """
        Find a Goods Receipt Note by PO reference

        Args:
            po_reference: PO reference number to search for

        Returns:
            GRN document or None if not found. If multiple GRNs exist,
            returns the most recent one by receipt_date.
        """
        grns = await self.get_documents_by_type("goods-receipt-note")
        matching_grns = []
        for grn in grns:
            structured_data = grn.get("structured_data", {})
            reference = self._extract_value(structured_data.get("po_reference"))
            if reference == po_reference:
                matching_grns.append(grn)

        if not matching_grns:
            return None

        matching_grns.sort(
            key=lambda item: self._extract_value(
                item.get("structured_data", {}).get("receipt_date")
            ) or "",
            reverse=True,
        )
        return matching_grns[0]
