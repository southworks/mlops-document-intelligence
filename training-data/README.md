# Training Data for ADI Compose Model

## Article context: v0 and v1 datasets

This directory contains two versioned datasets that map directly to the article's iterative MLOps lifecycle.

| Dataset | Role in the article | Used by |
|---------|--------------------|---------:|
| `procurement-dataset.v0` | **Seed dataset** — pre-labeled data used to train the initial v0 compose model. Represents the team's existing model before the iterative cycle begins. | `bootstrap.json` seeds this into ModelAdmin at demo reset; `prepare-demo.py` uploads it to blob storage. |
| `procurement-dataset.v1` | **Post-HITL dataset** — represents the curated training data that would emerge after a complete Human-in-the-Loop review cycle (Stages 3–6 in the concept pipeline). Staging and labeling this dataset triggers the v1 training run, closing the first loop. | Manually staged via the ModelAdmin UI to demonstrate Stage 5 "Data Staging" and the subsequent training job. |

This maps to the article sections:
- **"Training Requirements: The Data Staging"** — describes how v1 data is assembled from approved review candidates and staged for ADI training.
- **"Closing the Loop: The Next Iteration"** — the promoted v1 compose model becomes the new active model, improving confidence scores on future ingested documents.

---

## Overview

This directory contains organized training data for Azure Document Intelligence (ADI) Compose Model development. The data has been consolidated from multiple test folders to provide comprehensive samples for custom model training.

## Directory Structure

```
training-data/
├── invoices/                    (28 PDFs - full set)
├── purchase-orders/             (66 PDFs - full set)
├── goods-receipt-notes/         (8 PDFs - full set)
├── minimum/
│   ├── invoices/                (5 PDFs - minimum trainable set)
│   ├── purchase-orders/         (5 PDFs - minimum trainable set)
│   └── goods-receipt-notes/     (5 PDFs - minimum trainable set)
└── test-scenarios/
    ├── UNKNOWN_SCENARIO_RANDOM_DOCUMENT.pdf
    └── LOW_CONFIDENCE_SCENARIO_NOISY_INVOICE.pdf
```

## Minimum Required Files (Classification + Extraction)

To keep only the minimum practical data for custom training, use the `minimum/` folders.

- `minimum/invoices/` → 5 invoice PDFs
- `minimum/purchase-orders/` → 5 PO PDFs
- `minimum/goods-receipt-notes/` → 5 GRN PDFs

This gives a minimal trainable dataset for each type. Accuracy will be lower than the full dataset, but it is enough for baseline experimentation and quick retraining cycles.

> Decision in this repo: keep full corpus plus a curated minimum subset (non-destructive approach).

## Test PDFs for ModelAdmin Scenarios

Two synthetic PDFs were added in `test-scenarios/` for smoke validation of US-01 candidate intake:

1. `UNKNOWN_SCENARIO_RANDOM_DOCUMENT.pdf`
   - Content intentionally does not resemble Invoice/PO/GRN.
   - Expected outcome: classified as `unknown` and captured as ModelAdmin candidate.

2. `LOW_CONFIDENCE_SCENARIO_NOISY_INVOICE.pdf`
   - Content resembles an invoice but with ambiguous/noisy fields.
   - Expected outcome: low confidence and captured as ModelAdmin candidate.

### Important Note

Low-confidence behavior depends on the currently active ADI compose model and thresholds. In some runs, this PDF may classify as `unknown` instead of low-confidence invoice. Both outcomes are valid for US-01 candidate intake because both should be flagged.

## Data Categories

### Invoices (28 samples)
- **Location:** `invoices/`
- **Source:** Combined from:
  - `test_invoices/` (20 PDFs) - Standard business invoices
  - `test_matching_invoices/` (8 PDFs) - Three-way matching validation set
- **Use Case:** Training invoice extraction model
- **Key Fields:** InvoiceId, InvoiceDate, DueDate, VendorName, VendorAddress, CustomerName, CustomerAddress, Items, SubTotal, TotalTax, InvoiceTotal, AmountDue, PurchaseOrder
- **Recommended Model Name:** `invoice-extraction-model` or `custom-invoice-model`

### Purchase Orders (66 samples)
- **Location:** `purchase-orders/`
- **Source:** Combined from:
  - `test_purchase_orders/` (58 PDFs) - Diverse vendor and format samples
  - `test_matching_purchase_orders/` (8 PDFs) - Three-way matching validation set
- **Use Case:** Training purchase order extraction model
- **Key Fields:** PurchaseOrder, OrderDate, VendorName, VendorAddress, CustomerName, CustomerAddress, Items, SubTotal, TotalTax, InvoiceTotal
- **Recommended Model Name:** `po-extraction-model` or `custom-po-model`

### Goods Receipt Notes (8 samples)
- **Location:** `goods-receipt-notes/`
- **Source:** `test_matching_grn/` (all 8 PDFs)
- **Use Case:** Training GRN extraction model (or retraining existing)
- **Key Fields:** GrnId, ReceiptDate, PurchaseOrder, OrderDate, VendorName, VendorAddress, CustomerName, CustomerAddress, Items (with QuantityOrdered/Received/Rejected), AdditionalNotes, Status
- **Recommended Model Name:** `grn-extraction-model` or `custom-grn-model-v2`
- **Note:** Only 8 samples (minimum). Consider collecting 10-20 additional samples for better accuracy.

### Invoices - Retail (20 samples) [Optional]
- **Location:** `invoices-retail/`
- **Source:** `test_invoices_retail/` (all 20 PDFs)
- **Use Case:** **OPTIONAL** - Training specialized model for e-commerce/retail invoices
- **Key Fields:** Same as standard invoices
- **Recommended Model Name:** `retail-invoice-model` or `custom-retail-invoice-model`
- **When to Use:** If retail invoices have significantly different formats (layouts, fields, vendors) than standard business invoices

## Using This Data with Azure Document Intelligence Studio

### Step 1: Upload to Azure Storage (if needed)

If your training data isn't already in Azure Storage:

1. Create an Azure Storage account or use existing account
2. Create a container (e.g., `training-data/`)
3. Upload the subdirectories:
   ```bash
   az storage blob upload-batch \
     --account-name <storage-account> \
     --container-name training-data \
     --source ./training-data/invoices \
     --destination-path invoices
   
   az storage blob upload-batch \
     --account-name <storage-account> \
     --container-name training-data \
     --source ./training-data/purchase-orders \
     --destination-path purchase-orders
   
   # ... repeat for other directories
   ```

### Step 2: Train with ADI Studio

See [ADI_COMPOSE_MODEL_IMPLEMENTATION.md](ADI_COMPOSE_MODEL_IMPLEMENTATION.md#part-2-training-custom-models-in-adi-studio) for detailed training instructions.

## Data Quality Guidelines

### Before Training

✅ **Ensure your data is ready:**
- [ ] All PDFs are valid (not corrupted)
- [ ] Files are searchable PDFs (not scans without OCR) - or can add OCR if needed
- [ ] Document types are correctly sorted by folder
- [ ] No duplicate files across categories
- [ ] File names are descriptive (e.g., `INV-2024-001.pdf`, not `document.pdf`)

⚠️ **Known Issues:**
- If PDFs are scans without OCR, ADI will still work but may need more samples for accuracy
- Mixed document types in a single folder will confuse the model
- Very small samples (< 5 per category) may result in poor model performance

### Sample Count Recommendations

| Category | Samples | Quality | Expected Accuracy |
|----------|---------|---------|-------------------|
| 5-10 | Minimum | May vary | 50-70% |
| 20-30 | Good | Consistent | 75-85% |
| 50+ | Excellent | High | 85-95% |
| 100+ | Premium | Very High | 90%+ |

**Current Status:**
- Invoices: 28 samples (Good - should achieve 75-85% accuracy)
- Purchase Orders: 66 samples (Excellent - should achieve 85-95% accuracy)
- GRN: 8 samples (Minimum - consider collecting more)
- Invoices-Retail: 20 samples (Good - if trained separately)

## Labeling Instructions for ADI Studio

When training models, you'll need to label fields in each document:

### Invoice Model - Fields to Label

1. **InvoiceId** - The unique invoice number (e.g., INV-2024-001)
2. **InvoiceDate** - Date invoice was issued
3. **DueDate** - Payment due date
4. **VendorName** - Name of supplier/vendor
5. **VendorAddress** - Full address of vendor
6. **CustomerName** - Name of customer/buyer
7. **CustomerAddress** - Full address of customer
8. **Items** - Line items table with:
   - Description
   - Quantity
   - UnitPrice
   - Amount
9. **SubTotal** - Subtotal before taxes
10. **TotalTax** - Total tax amount
11. **InvoiceTotal** - Total invoice amount
12. **AmountDue** - Final amount due (may equal total after payments)
13. **PurchaseOrder** - PO number reference (if present)

### PO Model - Fields to Label

Same as Invoice model, using PurchaseOrder instead of InvoiceId

### GRN Model - Fields to Label

1. **GrnId** - GRN number
2. **ReceiptDate** - Date goods received
3. **PurchaseOrder** - Reference PO number
4. **OrderDate** - Original PO order date
5. **VendorName** - Supplier name
6. **VendorAddress** - Supplier address
7. **CustomerName** - Receiver name
8. **CustomerAddress** - Receiver address
9. **Items** - Received goods with:
   - Description
   - QuantityOrdered (from PO)
   - QuantityReceived (actual receipt)
   - QuantityRejected (if any)
   - Status (OK/Damaged/Short/etc)
10. **AdditionalNotes** - Any notes about receipt
11. **Notes** - Item-level notes

## Refreshing Training Data

When you have new documents to add to training:

1. **Validate document type** - Ensure it's correctly classified
2. **Add to appropriate folder:**
   ```bash
   cp new_invoice.pdf training-data/invoices/
   cp new_po.pdf training-data/purchase-orders/
   # ... etc
   ```
3. **Re-label in ADI Studio** when adding new documents
4. **Retrain model** to incorporate new samples
5. **Test and validate** before deploying to production

## File Naming Convention

For future reference, documents follow this naming pattern:

- **Invoices:** `INV-YYYY-NNN.pdf` (e.g., `INV-2024-001.pdf`)
- **Purchase Orders:** `PO-YYYY-NNN.pdf` (e.g., `PO-2024-001.pdf`)
- **GRN:** `GRN-YYYY-NNN.pdf` (e.g., `GRN-2024-200.pdf`)
- **Retail Invoices:** `RET-YYYY-NNN.pdf` (e.g., `RET-2024-001.pdf`)

This naming convention helps:
- Quickly identify document types
- Track document generation time
- Maintain consistent organization

## Original Source Data (Reference)

The training data was originally scattered across test folders:

| Original Folder | Documents | Consolidated To |
|-----------------|-----------|-----------------|
| `data/test_invoices/` | 20 PDFs | `training-data/invoices/` |
| `data/test_invoices_retail/` | 20 PDFs | `training-data/invoices-retail/` |
| `data/test_purchase_orders/` | 58 PDFs | `training-data/purchase-orders/` |
| `data/test_matching_grn/` | 8 PDFs | `training-data/goods-receipt-notes/` |
| `data/test_matching_invoices/` | 8 PDFs | `training-data/invoices/` |
| `data/test_matching_purchase_orders/` | 8 PDFs | `training-data/purchase-orders/` |

**Original test folders remain unchanged** for backward compatibility with existing scripts and documentation.

## Next Steps

1. **Review Training Data:**
   - [ ] Examine sample documents to understand format variety
   - [ ] Validate no corrupted PDFs
   - [ ] Check file organization

2. **Train Models:**
   - [ ] Follow [ADI_COMPOSE_MODEL_IMPLEMENTATION.md](ADI_COMPOSE_MODEL_IMPLEMENTATION.md)
   - [ ] Create extraction models for each category
   - [ ] Compose into unified Compose model

3. **Validate Models:**
   - [ ] Test with training data samples
   - [ ] Test with new unseen documents
   - [ ] Compare extraction accuracy against expectations

4. **Refactor Code:**
   - [ ] Implement `compose_extractor.py`
   - [ ] Update `documents.py` orchestration layer
   - [ ] Deploy and monitor metrics

## Questions & Support

For questions about:
- **Training data:** See original folders in `procurement_automation/data/`
- **ADI Studio:** See [Microsoft ADI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/)
- **Refactoring:** See [ADI_COMPOSE_MODEL_IMPLEMENTATION.md](ADI_COMPOSE_MODEL_IMPLEMENTATION.md)
- **Generation scripts:** See `spikes/generate_documents/` folder

---

**Created:** 2026-02-20  
**Total Samples:** 122 PDFs  
**Ready for Training:** ✅ Yes
