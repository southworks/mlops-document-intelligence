# FinOptPlatform — Architecture Reference

> Diagrams reflect the codebase as of Phase 4 simplification (May 2026).
> Rendered by GitHub Markdown, VS Code Markdown Preview (with Mermaid extension), and MkDocs.

---

## 0. Concept Pipeline

End-to-end lifecycle that the platform demonstrates. Each stage shows its concept role and the primary file or class that implements it.

```mermaid
flowchart TD
    ING["1 · Ingestion\nPOST /upload → worker\ndocument_processor.py"]
    GATE["2 · Confidence Gate\nconfidence_gate.py\ncompute_confidence + notify_modeladmin"]
    RC["3 · Review Candidates\nreview_candidates route\nlabel + approve"]
    DS["4 · Dataset Curation\ntraining_datasets route\nTrainingDatasetRepository"]
    STAGE["5 · Staging\nTrainingDatasetService\n.stage_dataset()"]
    LABEL["6 · Labeling\nTrainingDatasetService\n.recheck_labels()"]
    TRAIN["7 · Training\nTrainingJobOrchestration\nADI build + compose"]
    LIN["8 · Model Lineage\nTrainedModel\nComposeModel + Extractors"]
    PROM["9 · Model Promotion\nActiveModelConfig\nPOST /models/{id}/activate"]
    REG["10 · Model Registry\nactive_model_config_repository\nsingle active compose model ID"]
    BETTER["11 · Improved Ingestion\nactive compose model\nbetter extraction"]

    ING --> GATE --> RC --> DS --> STAGE --> LABEL --> TRAIN --> LIN --> PROM --> REG --> BETTER
    BETTER -.->|"next cycle"| ING
```

> Stages 1–2 live in `production_app/backend`. Stages 3–11 live in `modeladmin_sidecar`.

### Stage-to-article mapping

| Stage | Article section | Primary source file(s) |
|-------|----------------|------------------------|
| 1 · Ingestion | "Document Ingestion: Upload, Queue, and Worker" | `production_app/backend/document_processor.py` |
| 2 · Confidence Gate | "Confidence Scoring and Triage" | `production_app/backend/confidence_gate.py` |
| 3 · Review Candidates | "Human-in-the-Loop (HITL): Labeling and Approval" | `modeladmin_sidecar/routes/review_candidates.py` |
| 4 · Dataset Curation | "Training Requirements: Curating the Dataset" | `modeladmin_sidecar/routes/training_datasets.py` |
| 5 · Staging | "Training Requirements: The Data Staging" | `modeladmin_sidecar/services/training_dataset_service.py` |
| 6 · Labeling | "Training Requirements: The Data Staging" | `modeladmin_sidecar/services/training_dataset_service.py` |
| 7 · Training | "Triggering a Training Job with ADI Custom Models" | `modeladmin_sidecar/services/training_job_orchestration.py` |
| 8 · Model Lineage | "Model Governance: Tracking Trained and Compose Models" | `modeladmin_sidecar/repositories/trained_model_repository.py`, `compose_model_repository.py` |
| 9 · Model Promotion | "Model Governance: Promoting a New Active Model" | `modeladmin_sidecar/routes/models.py` |
| 10 · Model Registry | "Model Governance: Promoting a New Active Model" | `modeladmin_sidecar/repositories/active_model_config_repository.py` |
| 11 · Improved Ingestion | "Closing the Loop: The Next Iteration" | `production_app/backend/confidence_gate.py` |

---

## 1. System Topology

Four Docker Compose services sharing a bridge network. All storage operations target real Azure services.

```mermaid
graph TB
    Browser["🌐 Browser / API Client"]

    subgraph compose["Docker Compose — local-dev network"]
        direction TB

        FE["Frontend  :3000\nReact + Vite · Nginx\n(production_app/frontend)"]

        subgraph backend_group["production_app/backend — one image, two roles"]
            BAPI["Backend API  :8000\nFastAPI async"]
            WRK["Worker\nAzure Queue consumer"]
        end

        MA["ModelAdmin Sidecar  :8100\nFastAPI sync\n(modeladmin_sidecar)"]

        DB_B[("mlops-backend-data\nSQLite · jobs")]
        DB_M[("mlops-modeladmin-data\nSQLite · 10 tables")]
    end

    subgraph azure["☁️  Azure"]
        AZ_BLOB["Blob Storage\ndocuments · training-data"]
        AZ_QUEUE["Queue Storage\ndocument-processing-queue"]
        AZ_TABLE["Table Storage\ndocument metadata index"]
        ADI["Azure Document Intelligence\nOCR · Extraction\nClassifier + Compose training"]
    end

    SHARED["📦 shared/\nadi_helpers · logging_helpers"]

    Browser --> FE
    FE -->|"REST"| BAPI

    BAPI -->|"POST /boundary/modeladmin/candidate-created"| MA
    WRK  -->|"POST /boundary/..."| MA

    BAPI <-->|"Blob / Queue / Table"| AZ_BLOB
    WRK  <-->|"Blob / Queue"| AZ_BLOB
    MA   <-->|"Blob (training data)"| AZ_BLOB

    BAPI --- DB_B
    WRK  --- DB_B
    MA   --- DB_M

    MA   -->|"Admin API — build / poll / compose"| ADI
    BAPI -->|"Analyze API — OCR + extraction"| ADI

    MA   --> SHARED
```

---

## 2. Internal Layer Architecture

### ModelAdmin Sidecar

```mermaid
graph LR
    subgraph sidecar["ModelAdmin Sidecar  (FastAPI sync · port 8100)"]
        direction TB

        subgraph routes["Routes (9 modules)"]
            R1["boundary_intake\n  POST /boundary/modeladmin/candidate-created"]
            R2["review_candidates\n  GET|POST /modeladmin/review-candidates/…"]
            R3["training_datasets\n  GET|POST /modeladmin/training-datasets/…"]
            R4["training_jobs ← thin\n  POST …/start-training\n  GET …/training-jobs/{id}"]
            R5["retrain_jobs\n  GET /modeladmin/retrain-jobs/…"]
            R6["models\n  GET|POST /modeladmin/models/…"]
            R7["admin\n  POST /admin/reset-demo"]
            R8["ui  (HTML pages)"]
            R9["health"]
        end

        subgraph services["Services"]
            SVC1["training_job_orchestration ✦\n  TrainingJobOrchestration\n  serialize_operation / serialize_job"]
            SVC2["document_intelligence_service\n  ADI build / poll / compose\n  uses shared.adi_helpers"]
            SVC3["azure_blob_storage_service\n  SAS URLs · blob list"]
            SVC4["training_dataset_service ✦\n  TrainingDatasetService\n  stage / recheck / mark_ready / retrain"]
        end

        subgraph repos["Repositories (7 modules)"]
            RP["training_job · training_dataset\nreview_candidate · retrain_job\ncompose_model · trained_model\nactive_model_config"]
        end

        subgraph core["modeladmin_core/"]
            MC["boundary_contracts · doc_types\nnormalization · policy\ntraining_dataset_contracts\nservice_api_contracts"]
        end

        DB_M[("SQLite\nreview_candidates · training_datasets\ntraining_dataset_memberships\ntraining_jobs · training_job_operations\nretrain_jobs · trained_models\ncompose_models · active_model_config")]

        routes --> services
        routes --> core
        services --> repos
        services --> core
        repos --> DB_M
    end

    SHARED["📦 shared/\nadi_helpers.py\nlogging_helpers.py"]
    SVC2 --> SHARED
    SVC1 --> SHARED
```

### Backend API + Worker

```mermaid
graph LR
    subgraph backend["Backend  (FastAPI async · port 8000)"]
        direction TB

        subgraph b_routes["Routes"]
            BR1["upload  POST /upload"]
            BR2["jobs    GET|DELETE /jobs/…"]
            BR3["documents  GET|POST /documents/…"]
            BR4["health  GET /health"]
        end

        subgraph b_services["Services"]
            BS1["document_processor\n  OCR + extraction pipeline"]
            BS2["confidence_gate\n  compute_confidence()\n  notify_modeladmin()"]
            BS3["queue_jobs  Azure Queue helpers"]
            BS4["blob_parse · documents_query\nsas_helpers · storage_clients\nupload_location"]
        end

        subgraph b_storage["Storage Adapters"]
            BSA["azure · local · base"]
        end

        REPO["document_repository"]
        DB_B[("SQLite\njobs")]

        b_routes --> b_services
        b_services --> REPO
        b_services --> b_storage
        REPO --> DB_B
    end
```

---

## 3. Training Job Flow

End-to-end sequence from API call through ADI polling to compose model creation.

```mermaid
sequenceDiagram
    participant Client
    participant Routes as training_jobs.py<br/>(thin handler)
    participant Orch as TrainingJobOrchestration
    participant Blob as AzureBlobStorageService
    participant ADI as DocumentIntelligenceService
    participant Repo as TrainingJobRepository
    participant DB as SQLite

    Client->>Routes: POST /training-datasets/{id}/start-training
    Routes->>Orch: .start_training(dataset_id)
    Orch->>Repo: create_job()
    Orch->>Blob: get_container_sas_url()
    Orch->>ADI: begin_build_document_model() × N extractors
    Orch->>ADI: begin_build_classifier()
    Orch->>Repo: update_operation_running() per op
    Orch->>DB: job status → building_components
    Routes-->>Client: 201 {success, item}

    Note over Client,DB: Later — client polls for status

    Client->>Routes: GET /training-jobs/{job_id}
    Routes->>Orch: .get_job(job_id)
    Orch->>ADI: get_operation_status() per running op
    Note over Orch: all extractors + classifier done?
    Orch->>ADI: begin_compose_model()
    Orch->>DB: job status → building_compose
    Routes-->>Client: 200 {status: building_compose}

    Note over Client,DB: Later — client polls again

    Client->>Routes: GET /training-jobs/{job_id}
    Routes->>Orch: .get_job(job_id)
    Orch->>ADI: get_compose_status()
    Orch->>DB: upsert ComposeModel catalog
    Orch->>DB: job status → completed
    Routes-->>Client: 200 {status: completed}
```

---

## 4. Document Processing Flow

```mermaid
sequenceDiagram
    participant Client
    participant Upload as upload route
    participant Queue as Azure Queue
    participant Worker
    participant DocProc as document_processor
    participant ADI as Azure Document Intelligence
    participant ConfGate as confidence_gate
    participant Sidecar as ModelAdmin Sidecar

    Client->>Upload: POST /upload (file)
    Upload->>Queue: enqueue job message
    Upload-->>Client: 202 {job_id}

    Worker->>Queue: dequeue message
    Worker->>DocProc: process(blob_path)
    DocProc->>ADI: analyze_document (compose model)
    ADI-->>DocProc: extraction result
    DocProc->>ConfGate: compute_confidence(result)
    alt low-confidence or unknown doc_type
        ConfGate->>Sidecar: POST /boundary/modeladmin/candidate-created
        Sidecar-->>ConfGate: 201 accepted
    end
    DocProc->>DB: persist job result
```

---

## 5. Shared Package

`shared/` lives at the repo root and is importable by both services via `PYTHONPATH`.

```mermaid
graph TD
    subgraph shared["📦  shared/"]
        ADI_H["adi_helpers.py\n  redact_adi_url(url) → str\n  format_adi_error(info) → str\n  _ADI_SENSITIVE_PARAMS: frozenset"]
        LOG_H["logging_helpers.py\n  audit_log(event, **kwargs)\n  Wraps logger + audit_logger + print"]
    end

    MA_SVC["modeladmin_sidecar/services/\n  document_intelligence_service.py\n  training_job_orchestration.py"] --> ADI_H
    MA_SVC --> LOG_H
```

---

## 6. Database Schema (ModelAdmin Sidecar)

```mermaid
erDiagram
    REVIEW_CANDIDATES {
        string id PK
        string document_type
        string status
        string compose_model_id
        json low_confidence_snapshot
        datetime created_at
    }

    TRAINING_DATASETS {
        string id PK
        string name
        string status
        int version_number
        string parent_id FK
        datetime created_at
    }

    TRAINING_DATASET_MEMBERSHIPS {
        string dataset_id FK
        string candidate_id FK
    }

    TRAINING_JOBS {
        string id PK
        string dataset_version_id FK
        string status
        datetime started_at
        datetime completed_at
        string error_message
    }

    TRAINING_JOB_OPERATIONS {
        string id PK
        string job_id FK
        string operation_type
        string doc_type
        string adi_operation_id
        string adi_model_id
        string status
        string error_message
    }

    COMPOSE_MODELS {
        string id PK
        int version_number
        string status
        bool is_active
        string classifier_model_id
        string dataset_version_id FK
    }

    COMPOSE_MODEL_EXTRACTORS {
        string compose_model_id FK
        string trained_model_id
    }

    TRAINED_MODELS {
        string trained_model_id PK
        string model_type
        string status
        string dataset_version_id FK
    }

    ACTIVE_MODEL_CONFIG {
        string id PK
        string active_compose_model_id
    }

    TRAINING_DATASETS ||--o{ TRAINING_DATASET_MEMBERSHIPS : "has members"
    REVIEW_CANDIDATES ||--o{ TRAINING_DATASET_MEMBERSHIPS : "member of"
    TRAINING_DATASETS ||--o{ TRAINING_JOBS : "triggers"
    TRAINING_JOBS ||--o{ TRAINING_JOB_OPERATIONS : "has operations"
    COMPOSE_MODELS ||--o{ COMPOSE_MODEL_EXTRACTORS : "uses"
    TRAINING_DATASETS ||--o{ COMPOSE_MODELS : "produces"
```
