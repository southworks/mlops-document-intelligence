"""
One-time script to generate regression test dataset PDFs.
Generates 10 test documents:
- 5 POs/Invoices with column-based layout (high confidence for ModelV1)
- 5 GRNs with vertical list layout (low confidence for ModelV1)

Run once, commit PDFs and manifest, keep script in docs for reference.
Not executed during test runs.

Usage:
    python generate_regression_pdfs.py
"""

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from pathlib import Path
import json
from datetime import datetime, timedelta
import random

# Seed for reproducibility
random.seed(42)

SCRIPT_DIR = Path(__file__).parent
DOC_DIR = SCRIPT_DIR / "sample_documents"
PO_DIR = DOC_DIR / "po_invoices"
GRN_DIR = DOC_DIR / "grn_documents"


def ensure_directories():
    """Create output directories."""
    PO_DIR.mkdir(parents=True, exist_ok=True)
    GRN_DIR.mkdir(parents=True, exist_ok=True)


def generate_po_invoice(filename, doc_type, doc_number, amount, item_count):
    """Generate a PO or Invoice PDF with column-based layout (HIGH confidence)."""
    filepath = PO_DIR / filename

    doc = SimpleDocTemplate(str(filepath), pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()

    # Header
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=12
    )
    header_style = ParagraphStyle(
        'HeaderText',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6
    )

    title = f"{'PURCHASE ORDER' if doc_type == 'PO' else 'INVOICE'}"
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.1*inch))

    # Document info - horizontal layout
    doc_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d")
    story.append(Paragraph(f"<b>Document Number:</b> {doc_number} &nbsp;&nbsp;&nbsp; <b>Date:</b> {doc_date}", header_style))
    story.append(Spacer(1, 0.15*inch))

    # Supplier/Vendor info
    supplier_names = ["Acme Corp", "Global Supplies Ltd", "International Traders", "Premium Goods Inc", "Quality Imports"]
    supplier = random.choice(supplier_names)
    story.append(Paragraph(f"<b>Supplier/Vendor:</b> {supplier}", header_style))
    story.append(Spacer(1, 0.15*inch))

    # Line items table (COLUMN-BASED - key for HIGH confidence)
    line_items = []
    line_items.append(["Item No.", "Description", "Qty", "Unit Price", "Amount"])

    total_calc = 0
    unit_prices = [100, 250, 500, 75, 150, 200, 300, 400, 120, 180]

    for i in range(item_count):
        qty = random.randint(1, 10)
        unit_price = random.choice(unit_prices)
        line_amount = qty * unit_price
        total_calc += line_amount

        descriptions = [
            "Office Supplies", "Raw Materials", "Equipment", "Services",
            "Components", "Tools", "Hardware", "Software License"
        ]

        line_items.append([
            str(i + 1),
            random.choice(descriptions),
            str(qty),
            f"${unit_price}",
            f"${line_amount:,}"
        ])

    # Create table with column headers (TABULAR LAYOUT = HIGH CONFIDENCE)
    table = Table(line_items, colWidths=[0.8*inch, 2.2*inch, 0.6*inch, 0.9*inch, 0.9*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#cccccc')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9f9f9')])
    ]))

    story.append(table)
    story.append(Spacer(1, 0.2*inch))

    # Total line
    total_style = ParagraphStyle(
        'TotalStyle',
        parent=styles['Normal'],
        fontSize=11,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#000000')
    )
    story.append(Paragraph(f"<b>Total Amount: ${total_calc:,}</b>", total_style))

    doc.build(story)
    return total_calc, item_count


def generate_grn(filename, grn_number, item_count):
    """Generate a GRN PDF with VERTICAL list layout (LOW confidence)."""
    filepath = GRN_DIR / filename

    doc = SimpleDocTemplate(str(filepath), pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
    story = []
    styles = getSampleStyleSheet()

    # Header
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=12
    )
    header_style = ParagraphStyle(
        'HeaderText',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=4
    )

    story.append(Paragraph("GOODS RECEIPT NOTICE", title_style))
    story.append(Spacer(1, 0.1*inch))

    # GRN Receiving Details - VERTICAL LABEL:VALUE PAIRS (KEY FOR LOW CONFIDENCE)
    grn_date = (datetime.now() - timedelta(days=random.randint(1, 30))).strftime("%Y-%m-%d")
    supplier_names = ["Acme Corp", "Global Supplies Ltd", "International Traders", "Premium Goods Inc", "Quality Imports"]
    supplier = random.choice(supplier_names)

    receiving_details = {
        "GRN Number": grn_number,
        "Date Received": grn_date,
        "Supplier": supplier,
        "PO Reference": f"PO-{random.randint(1000, 9999)}",
        "Receiving Location": random.choice(["Warehouse A", "Warehouse B", "Warehouse C", "Distribution Center"]),
        "Received By": random.choice(["John Smith", "Maria Garcia", "Ahmed Hassan", "Lisa Chen"])
    }

    # Output receiving details as vertical pairs (BAD FOR OCR - causes low confidence)
    for key, value in receiving_details.items():
        story.append(Paragraph(f"<b>{key}:</b> {value}", header_style))

    story.append(Spacer(1, 0.2*inch))

    # Line Items - VERTICAL SPREAD (NOT TABULAR = DIFFERENT FROM PO)
    story.append(Paragraph("<b>Line Items</b>", ParagraphStyle('SubHeader', parent=styles['Normal'], fontSize=11, spaceAfter=8)))
    story.append(Spacer(1, 0.1*inch))

    line_style = ParagraphStyle(
        'LineItem',
        parent=styles['Normal'],
        fontSize=9,
        spaceAfter=2,
        leftIndent=0.2*inch
    )

    separator_style = ParagraphStyle(
        'Separator',
        parent=styles['Normal'],
        fontSize=8,
        spaceAfter=8,
        textColor=colors.gray
    )

    total_calc = 0
    unit_prices = [100, 250, 500, 75, 150, 200, 300, 400, 120, 180]
    sku_list = ["SKU-001", "SKU-002", "SKU-003", "SKU-004", "SKU-005",
                "SKU-006", "SKU-007", "SKU-008", "SKU-009", "SKU-010"]

    for i in range(item_count):
        qty = random.randint(1, 10)
        unit_price = random.choice(unit_prices)
        line_amount = qty * unit_price
        total_calc += line_amount

        descriptions = [
            "Office Supplies", "Raw Materials", "Equipment", "Services",
            "Components", "Tools", "Hardware", "Software License"
        ]

        sku = random.choice(sku_list)
        description = random.choice(descriptions)
        condition = random.choice(["Acceptable", "Acceptable", "Acceptable", "Damaged (Minor)"])

        # VERTICAL LIST FORMAT (NOT TABULAR - causes low OCR confidence)
        story.append(Paragraph(f"Item: {i + 1}", line_style))
        story.append(Paragraph(f"SKU: {sku}", line_style))
        story.append(Paragraph(f"Description: {description}", line_style))
        story.append(Paragraph(f"Qty: {qty}", line_style))
        story.append(Paragraph(f"Unit Price: ${unit_price}", line_style))
        story.append(Paragraph(f"Amount: ${line_amount:,}", line_style))
        story.append(Paragraph(f"Condition: {condition}", line_style))
        story.append(Paragraph("─" * 50, separator_style))

    story.append(Spacer(1, 0.1*inch))

    # QC Status and signature
    qc_status = random.choice(["ACCEPTED", "ACCEPTED", "ACCEPTED", "PARTIAL ACCEPTED"])
    story.append(Paragraph(f"<b>QC Status:</b> {qc_status}", header_style))
    story.append(Paragraph(f"<b>Total Amount:</b> ${total_calc:,}", header_style))
    story.append(Spacer(1, 0.15*inch))
    story.append(Paragraph("Signature: _____________________", header_style))

    doc.build(story)
    return total_calc, item_count


def generate_test_manifest(po_data, grn_data):
    """Create regression_test_manifest.json mapping files to expected confidence."""
    manifest = {
        "regression_dataset": {
            "description": "Regression test dataset for Document Classification Model V1 vs V2",
            "generated": datetime.now().isoformat(),
            "model_v1_baseline": {
                "description": "PO/Invoice documents - high confidence for ModelV1",
                "documents": po_data
            },
            "model_v1_challenge": {
                "description": "GRN documents with vertical layout - low confidence for ModelV1",
                "documents": grn_data
            },
            "model_v2_improvements": {
                "description": "Same GRN documents - high confidence for ModelV2 (trained on GRNs)",
                "documents": [
                    {
                        "filename": d["filename"],
                        "document_type": d["document_type"],
                        "expected_confidence": 0.92 if "GRN" in d["filename"] else d["expected_confidence"],
                        "reason": "ModelV2 trained on GRN dataset"
                    }
                    for d in grn_data
                ]
            }
        }
    }

    manifest_path = DOC_DIR / "regression_test_manifest.json"
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)

    return manifest_path


def main():
    """Generate all regression test PDFs."""
    ensure_directories()
    print(f"Creating directories: {PO_DIR} and {GRN_DIR}")

    po_data = []
    grn_data = []

    # Generate 5 PO/Invoice PDFs
    print("\nGenerating PO/Invoice PDFs (HIGH confidence for ModelV1)...")
    po_amounts = [2000, 5000, 8000, 12000, 15000]
    po_items = [2, 5, 5, 8, 12]

    for i in range(5):
        filename = f"PO_high_confidence_{i+1:03d}.pdf"
        doc_num = f"PO-{2000 + i}"
        doc_type = "PO" if i < 3 else "INV"

        amount, items = generate_po_invoice(filename, doc_type, doc_num, po_amounts[i], po_items[i])
        print(f"  [OK] {filename} (${amount:,}, {items} items)")

        po_data.append({
            "filename": str(PO_DIR.name + "/" + filename),
            "document_type": doc_type,
            "amount": amount,
            "item_count": items,
            "expected_confidence": random.uniform(0.90, 0.96),
            "reason": "Clear tabular layout, typical for ModelV1"
        })

    # Generate 5 GRN PDFs
    print("\nGenerating GRN PDFs (LOW confidence for ModelV1, vertical layout)...")
    grn_amounts = [2000, 5000, 8000, 12000, 15000]
    grn_items = [2, 5, 5, 8, 12]

    for i in range(5):
        filename = f"GRN_low_confidence_{i+1:03d}.pdf"
        grn_num = f"GRN-2026-{501 + i}"

        amount, items = generate_grn(filename, grn_num, grn_items[i])
        print(f"  [OK] {filename} (${amount:,}, {items} items)")

        grn_data.append({
            "filename": str(GRN_DIR.name + "/" + filename),
            "document_type": "GRN",
            "amount": amount,
            "item_count": items,
            "expected_confidence": random.uniform(0.35, 0.50),
            "reason": "Vertical label-value layout confuses ModelV1 OCR engines"
        })

    # Generate manifest
    print("\nGenerating regression_test_manifest.json...")
    manifest_path = generate_test_manifest(po_data, grn_data)
    print(f"  [OK] Manifest: {manifest_path}")

    print(f"\n[COMPLETE] Generated 10 PDF documents + manifest")
    print(f"   - POs/Invoices: {PO_DIR}")
    print(f"   - GRNs: {GRN_DIR}")
    print(f"   - Manifest: {manifest_path}")
    print(f"\n   Ready to commit to repository")


if __name__ == "__main__":
    main()
