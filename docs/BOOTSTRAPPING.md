# ModelAdmin Bootstrap (Minimal MVP)

## Objective
Bootstrap ModelAdmin using models already created in Azure Document Intelligence (ADI) Studio, with the minimum manual steps and no direct SQL edits.

## Current MVP Scope
- Single-bundle JSON contract
- One validation endpoint (schema + ADI existence in one call)
- Transactional apply endpoint (DB upsert + optional activation)
- CLI command using the same shared service logic as API
- Manual execution only (operator-triggered)

---

## JSON Contract

```json
{
  "compose_model_id": "invoice-extractor.v0",
  "classifier_model_id": "procurement-classificator.v0",
  "extractors": {
    "invoice": "invoice-extractor.v0",
    "purchase-order": "purchase-order-extractor.v0"
  },
  "activate": true
}
```

> **Note — compose model placeholder:** No dedicated compose model exists in the current ADI resource
> (`fin-opt-invoice-scan.cognitiveservices.azure.com`). `invoice-extractor.v0` is used as a stand-in for
> `compose_model_id` until `procurement-compose.v0` (or equivalent) is created in ADI Studio.
> Once the compose model is created, update both `bootstrap.json` and this sample.

### Rules
- `extractors` must contain at least one entry.
- Allowed keys: `invoice`, `purchase-order`, `goods-receipt-note`.
- `activate: true` (default) sets the compose model as the active model immediately.

### No training dataset required
Bootstrap registers models that were created manually in ADI Studio.
The system does not require a training dataset record; trained models and compose models are
registered without a dataset FK. If you later trigger a retrain cycle, a proper dataset will
be created through the normal review → retrain pipeline.

---

## Endpoint

### Reset and seed
`POST /admin/reset-demo`

- Drops and recreates all ModelAdmin tables.
- Re-validates all model IDs exist in ADI.
- Upserts DB entities in one transaction:
  - `trained_models` (classifier + extractors)
  - `compose_models` + `compose_model_extractors`
  - `active_model_config` (when `activate=true`)
- On ADI validation failure, returns HTTP 409 and writes nothing.
- Idempotent — safe to re-run; each call starts from a clean schema.

> The separate `/models/bootstrap/validate` and `/models/bootstrap/apply` endpoints were removed. `POST /admin/reset-demo` combines validation, schema reset, and seeding in one call.

---

## Operator Runbook
1. Create compose model, classifier, and extractor models in ADI Studio.
2. Build `scripts/bootstrap.json` using the contract above.
3. Call `POST /admin/reset-demo` with the bootstrap payload.
4. Verify active model via `GET /modeladmin/models/active`.

---

## Troubleshooting

### ADI endpoint/key not configured
- Symptom: validation fails on service initialization.
- Check `ADI_ENDPOINT` and `ADI_KEY` in the `modeladmin_service` environment.

### Missing model IDs
- Symptom: `validate` returns `missing_model_ids`.
- Verify IDs match exactly what was generated in ADI Studio.
- Ensure the models are in the same ADI resource configured by `ADI_ENDPOINT`/`ADI_KEY`.

### Apply returns 409
- Symptom: `One or more model IDs were not found in ADI`.
- Verify IDs in `bootstrap.json` match exactly what exists in your ADI resource.
- Correct the payload and retry `POST /admin/reset-demo`.

### Model still running / not ready
- Symptom: compose or extractor model exists in ADI but shows status `running` or `building`.
- ADI models must finish building before bootstrap can register them.
- Simply retry `validate` and `apply` until all IDs resolve successfully.
- There is no auto-polling — rerun when ADI reports the build as complete.

