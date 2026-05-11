# Getting Started

Step-by-step instructions to run the platform locally and walk through the full MLOps cycle.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Docker Desktop | Compose V2 required |
| Azure subscription | Free tier is sufficient for low-volume testing |
| Azure Document Intelligence resource | Custom Neural model tier (S0) |
| Azure Storage account | Blob storage used |
| Pre-trained ADI compose model | See note below |

> **Pre-trained model requirement**: The demo starts from Stage 10 — a model already exists and is active. You need a compose model (`procurement-compose-model.v0`), a classifier, and three extractor sub-models already created in ADI Studio before running the bootstrap step. `training-data/procurement-dataset.v0` contains the labeled data to train them. See the article section "Bootstrapping an Existing Model" for details.

---

## 1. Clone and configure

```bash
git clone https://github.com/<your-org>/MLOpsPlatform.git
cd MLOpsPlatform
cp .env.example .env.local
```

Open `.env.local` and fill in:

```bash
# Azure Document Intelligence
AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=https://<your-resource>.cognitiveservices.azure.com/
AZURE_DOCUMENT_INTELLIGENCE_KEY=<key>

# Azure Storage (used for documents and training data blobs)
AZURE_STORAGE_CONNECTION_STRING=DefaultEndpointsProtocol=https;AccountName=...

# Backend database (PostgreSQL service in docker compose)
DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres-service:5432/mlops_backend
MODELADMIN_DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres-service:5432/mlops_modeladmin

# Active compose model ID — must match an existing model in your ADI resource
AZURE_COMPOSE_MODEL_ID=procurement-compose-model.v0
```

### Confidence gate thresholds (optional tuning)

These control Stage 2. Documents whose extraction confidence falls below the threshold are routed as review candidates rather than accepted. Defaults to `0.70` for all types.

```bash
CONFIDENCE_THRESHOLD_INVOICE=0.70   # raise to capture more borderline invoices
CONFIDENCE_THRESHOLD_PO=0.70
CONFIDENCE_THRESHOLD_GRN=0.70
```

---

## 2. Start the platform

```bash
docker-compose up -d
```

Four services start:

| Service | URL | Role |
|---|---|---|
| `frontend-service` | http://localhost:3000 | Upload UI + document list |
| `backend-service` | http://localhost:8000 | FastAPI API + BackgroundTasks |
| `modeladmin-service` | http://localhost:8100 | MLOps control plane |
| `postgres-service` | localhost:5432 | Backend + ModelAdmin databases |

Wait for all health checks to pass:

```bash
docker-compose ps
```

---

## 3. Bootstrap the model registry

Seed the ModelAdmin database with your pre-trained v0 compose model. Edit `scripts/bootstrap.json` to match your actual ADI model IDs, then POST it to the reset-demo endpoint:

```bash
curl -X POST http://localhost:8100/admin/reset-demo \
  -H "Content-Type: application/json" \
  -d @scripts/bootstrap.json
```

Expected response:

```json
{
  "compose_model_id": "procurement-compose-model.v0",
  "trained_model_ids": [...],
  "active": true
}
```

Verify the active model:

```bash
curl http://localhost:8100/modeladmin/models/active
```

---

## 4. Walk through the pipeline

### Stage 1–2: Ingest a document

1. Open http://localhost:3000 and upload a PDF from `training-data/`.
2. A FastAPI background task runs ADI extraction and applies the confidence gate.
3. A low-confidence result creates a review candidate in ModelAdmin.

### Stage 3: Label a review candidate

1. Open http://localhost:8100/ui (ModelAdmin UI).
2. Find the review candidate, assign the correct doc-type label, and approve it.

### Stage 4–6: Curate and stage a training dataset

1. From the ModelAdmin UI, create a training dataset and add approved candidates to it.
2. Stage the dataset — `TrainingDatasetService.stage_dataset()` uploads labeled files to blob storage.
3. Recheck labels — `TrainingDatasetService.recheck_labels()` verifies ADI can read the staged data.

### Stage 7: Trigger training

1. Submit a training job from the ModelAdmin UI.
2. `TrainingJobOrchestration` calls ADI to build individual extractors and then assemble the compose model.
3. Poll `GET /modeladmin/training-jobs/{id}` until status is `complete`.

### Stage 9–10: Promote the new model

```bash
curl -X POST http://localhost:8100/modeladmin/models/<new-compose-model-id>/activate
```

Subsequent ingested documents will use the new model. The loop closes at Stage 11.

---

## 5. Full environment reset

To reset everything (DB, storage, bootstrap) in one command:

```bash
python scripts/prepare-demo.py
```

This resets ModelAdmin tables, clears blob storage, re-uploads `procurement-dataset.v0`, and calls `POST /admin/reset-demo`. Backend and ModelAdmin runtime state use separate databases on the same Postgres server with current-schema create-only initialization (no migration chain).

For this demo, Postgres storage is intentionally non-persistent: recreating `postgres-service` resets both databases.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `POST /admin/reset-demo` returns 409 | Model IDs in `bootstrap.json` do not exist in your ADI resource |
| Background processing never completes | Check `backend-service` logs — the background task runs in-process |
| Confidence gate never fires | Thresholds are too low — raise `CONFIDENCE_THRESHOLD_*` above your model's typical score |
| ModelAdmin tables missing after restart | Postgres container was recreated (stateless mode) — re-run `POST /admin/reset-demo` |
