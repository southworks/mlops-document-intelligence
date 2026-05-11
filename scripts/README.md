# Local reset scripts

## prepare-demo.py

Prepares local runtime state for repeated demo/test cycles in one command:

- Resets ModelAdmin DB schema/data
- Keeps backend Postgres runtime state intact (does not drop/recreate backend DB)
- Clears storage containers (`documents`, `training-data`) using `AZURE_STORAGE_CONNECTION_STRING` from `.env.local`
- Seeds `training-data` from `training-data/procurement-dataset.v0`
- Applies bootstrap from `bootstrap.json`
- Restarts `backend-container` and `modeladmin-container`
- Prints verification counts and `DEMO_READY`

Usage from `procurement_automation`:

```powershell
python ./scripts/prepare-demo.py
```

Optional flags:

```powershell
# Preview actions only (no changes)
python ./scripts/prepare-demo.py --dry-run

# Skip container restarts
python ./scripts/prepare-demo.py --no-restart

# Skip bootstrap apply
python ./scripts/prepare-demo.py --skip-bootstrap
```

## upload-sidecars-with-guid-prefix.ps1

Uploads local sidecar files (`.pdf.labels.json` and `.pdf.ocr.json`) to blob storage next to the
matching GUID-prefixed PDF blob.

Matching rule:

- Script walks subfolders under dataset root (for example `goods-receipt-note/`)
- For each local sidecar, it derives the local PDF name (for example `GRN_low_confidence_001.pdf`)
- In the same blob subfolder, it looks for a blob name that ends with that PDF name
- If exactly one match is found, it uploads sidecar as:
	- `<matched-pdf-blob>.labels.json` or
	- `<matched-pdf-blob>.ocr.json`

Usage from `procurement_automation`:

```powershell
# Default: uses .env.local and training-data/procurement-dataset.v1
./scripts/upload-sidecars-with-guid-prefix.ps1

# Preview actions only
./scripts/upload-sidecars-with-guid-prefix.ps1 -DryRun

# Overwrite existing sidecars
./scripts/upload-sidecars-with-guid-prefix.ps1 -Overwrite

# Use custom dataset root
./scripts/upload-sidecars-with-guid-prefix.ps1 -DatasetRoot "training-data/procurement-dataset.v1"

# Use explicit connection string (instead of .env.local)
./scripts/upload-sidecars-with-guid-prefix.ps1 -ConnectionString "<your-connection-string>"
```
