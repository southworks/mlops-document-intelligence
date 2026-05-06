# bootstrap.json — What it represents

`bootstrap.json` seeds the ModelAdmin sidecar with a pre-existing model configuration.

## Article context

In the article _"MLOps for Azure Document Intelligence: Orchestrating the Iterative Development of Custom Models"_, the platform assumes a team that **already has a trained ADI compose model** and wants to begin the iterative MLOps lifecycle — not start from scratch.

`bootstrap.json` simulates that starting state. When applied via `POST /admin/reset-demo`, it registers the v0 compose model, its classifier, and the three extractor sub-models into the ModelAdmin database and marks the compose model as active. This places the system at the **beginning of the loop** (Stage 10 → Stage 11 → Stage 1 in the concept pipeline), ready to ingest documents using a real model.

```
bootstrap.json
│
├── compose_model_id        → the ADI compose model ID to activate
├── classifier_model_id     → the ADI classifier sub-model
├── extractors              → map of doc-type → extractor sub-model ID
├── training_data.dataset_path → seeds the v0 training dataset record
└── activate: true          → marks this compose model as the live active model
```

## Relationship to training-data

`training_data.dataset_path` points at `training-data/procurement-dataset.v0`, which is the labeled
dataset used to train the v0 models. Importing it alongside the model registration lets the UI show
the originating dataset for the active model, establishing a traceable lineage from data → trained
models → active model from the very first demo step.

## Usage

The file is consumed by two paths:

| Path | When to use |
|------|------------|
| `POST /admin/reset-demo` (HTTP) | Normal demo and test resets — resets DB, re-seeds, activates. |
| `scripts/prepare-demo.py` | Full environment reset — also clears storage, restarts containers. |
