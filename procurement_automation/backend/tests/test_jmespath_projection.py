import json

from app.services.documents_query_service import query_documents_from_table
from processing.compose_extractor import parse_compose_result


def test_parse_compose_result_maps_purchase_order_from_schema() -> None:
    raw_adi = {
        "documents": [
            {
                "docType": "purchase-order-extractor.v1",
                "confidence": 0.88,
                "fields": {
                    "PurchaseOrder": {
                        "type": "string",
                        "valueString": "PO-123",
                        "confidence": 0.99,
                    },
                    "Date": {
                        "type": "date",
                        "valueDate": "2026-04-15",
                        "confidence": 0.95,
                    },
                    "VendorName": {
                        "type": "string",
                        "valueString": "Northwind Traders",
                        "confidence": 0.97,
                    },
                    "CustomerName": {
                        "type": "string",
                        "valueString": "Contoso Ltd",
                        "confidence": 0.96,
                    },
                    "Total": {
                        "type": "currency",
                        "valueCurrency": {"amount": 1250.75},
                        "confidence": 0.94,
                    },
                    "Items": {
                        "type": "array",
                        "valueArray": [
                            {
                                "type": "object",
                                "valueObject": {
                                    "Description": {
                                        "type": "string",
                                        "valueString": "Widget",
                                        "confidence": 0.91,
                                    },
                                    "Quantity": {
                                        "type": "number",
                                        "valueNumber": 5,
                                        "confidence": 0.92,
                                    },
                                    "UnitPrice": {
                                        "type": "currency",
                                        "valueCurrency": {"amount": 250.15},
                                        "confidence": 0.9,
                                    },
                                    "Amount": {
                                        "type": "currency",
                                        "valueCurrency": {"amount": 1250.75},
                                        "confidence": 0.93,
                                    },
                                },
                            }
                        ],
                    },
                },
            }
        ]
    }

    result = parse_compose_result(raw_adi)

    assert result["document_type"] == "purchase-order"
    assert result["structured_data"]["purchase_order"]["value"] == "PO-123"
    assert result["structured_data"]["date"]["value"] == "2026-04-15"
    assert result["structured_data"]["total"]["value"] == 1250.75
    assert result["structured_data"]["items"][0]["quantity"]["value"] == 5
    assert "diagnostics" not in result


def test_parse_compose_result_reports_missing_required_field() -> None:
    raw_adi = {
        "documents": [
            {
                "docType": "invoice-extractor.v1",
                "confidence": 0.82,
                "fields": {
                    "InvoiceDate": {
                        "type": "date",
                        "valueDate": "2026-04-01",
                        "confidence": 0.89,
                    },
                    "VendorName": {
                        "type": "string",
                        "valueString": "Northwind",
                        "confidence": 0.95,
                    },
                    "CustomerName": {
                        "type": "string",
                        "valueString": "Contoso",
                        "confidence": 0.95,
                    },
                    "InvoiceTotal": {
                        "type": "currency",
                        "valueCurrency": {"amount": 99.5},
                        "confidence": 0.9,
                    },
                },
            }
        ]
    }

    result = parse_compose_result(raw_adi)

    assert result["document_type"] == "invoice"
    assert result["structured_data"]["invoice_id"]["value"] is None
    assert "diagnostics" not in result


def test_query_documents_from_table_reads_full_projection_summary_json() -> None:
    projection = {
        "document_type": "purchase-order",
        "confidence": 0.88,
        "structured_data": {
            "purchase_order": {
                "value": "PO-123",
                "confidence": 0.99,
            },
            "date": {
                "value": "2026-04-15",
                "confidence": 0.95,
            },
            "vendor_name": {
                "value": "Northwind Traders",
                "confidence": 0.97,
            },
            "customer_name": {
                "value": "Contoso Ltd",
                "confidence": 0.96,
            },
            "total": {
                "value": 1250.75,
                "confidence": 0.94,
            },
            "items": [],
        },
    }

    class _FakeTableClient:
        def list_entities(self):
            return [
                {
                    "blob_path": "documents/purchase-orders/job-123_parsed.json",
                    "document_type": "purchase-order",
                    "classification_confidence": 0.88,
                    "summary_json": json.dumps(projection),
                    "job_id": "job-123",
                    "Timestamp": "2026-04-15T00:00:00+00:00",
                }
            ]

    documents = query_documents_from_table(_FakeTableClient(), "all")

    assert documents is not None
    assert len(documents) == 1
    assert documents[0]["document_type"] == "purchase-order"
    assert documents[0]["fields"]["purchase_order"]["value"] == "PO-123"
    assert documents[0]["fields"]["total"]["value"] == 1250.75
    assert "diagnostics" not in documents[0]