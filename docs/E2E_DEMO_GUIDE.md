# FinOptPlatform E2E Demo Guide

This guide documents the full end-to-end demo run from baseline model v0 to retrained model v1.

## Scope

- Start from a clean local environment.
- Ensure training data container contains only v0 seed files at demo start.
- Validate the expected behavior for low-confidence GRN handling.
- Retrain and activate v1.
- Re-validate using the same low-confidence GRNs.

## Script Inventory

- Preferred entrypoint: `procurement_automation/scripts/prepare-demo.py`
- Sidecar utility (kept separate): `procurement_automation/scripts/upload-sidecars-with-guid-prefix.ps1`
- Bootstrap config: `procurement_automation/scripts/bootstrap.json`

Legacy scripts were consolidated into `procurement_automation/scripts/prepare-demo.py`.

## Preconditions

1. Docker services are running.
2. `procurement_automation/.env.local` exists and has a valid `AZURE_STORAGE_CONNECTION_STRING`.
3. ADI model IDs in `procurement_automation/scripts/bootstrap.json` are valid and ready.
4. `training-data/procurement-dataset.v0` and `training-data/procurement-dataset.v1` exist locally.

## Phase 0: Prepare Environment (Reset + Seed v0 + Bootstrap)

Run from repository root:

```powershell
python procurement_automation/scripts/prepare-demo.py
```

Expected outcomes:

1. ModelAdmin DB is reset (backend Postgres DB remains intact).
2. Blob containers `documents` and `training-data` are cleared.
3. Backend processed-document index is rebuilt from new processing runs.
4. `training-data` container is seeded from `training-data/procurement-dataset.v0` only.
5. Bootstrap is applied and v0 compose model is active.
6. Verification checks print healthy counts and API responses.

### Automation Assertions

1. `GET http://localhost:8100/modeladmin/review-candidates?limit=100` returns 200 and zero candidates.
2. `GET http://localhost:8100/modeladmin/models/active` returns 200 and active compose model id is `procurement-compose-model.v0`.
3. `GET http://localhost:8000/documents/?limit=200` returns 200 and zero processed documents.
4. `GET http://localhost:8100/modeladmin/training-datasets` returns 200 and no dataset is in `training_in_progress`.
5. Applies to both mocked lane and nightly real-ADI lane.

## Phase 1: Upload 5 Invoices (v0)

Upload these files:

- `procurement_automation/training-data/procurement-dataset.v0/invoice/INV-2024-001.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/invoice/INV-2024-002.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/invoice/INV-2024-003.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/invoice/INV-2024-004.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/invoice/INV-2024-005.pdf`

Expected outcome:

- All ingested successfully.
- No review candidates created.

### Automation Assertions

1. Upload exactly 5 invoice files via `POST http://localhost:8000/upload/` and assert success for each call.
2. Poll `GET http://localhost:8000/documents/?limit=500` until 5 invoice documents appear or timeout.
3. `GET http://localhost:8100/modeladmin/review-candidates?limit=100` returns 200 and no new candidates from this phase.
4. Applies to both mocked lane and nightly real-ADI lane.

## Phase 2: Upload 5 Purchase Orders (v0)

Upload these files:

- `procurement_automation/training-data/procurement-dataset.v0/purchase-order/PO-2024-001.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/purchase-order/PO-2024-002.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/purchase-order/PO-2024-003.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/purchase-order/PO-2024-004.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/purchase-order/PO-2024-005.pdf`

Expected outcome:

- All ingested successfully.
- No review candidates created.

### Automation Assertions

1. Upload exactly 5 purchase-order files via `POST http://localhost:8000/upload/` and assert success for each call.
2. Poll `GET http://localhost:8000/documents/?limit=500` until 5 purchase-order documents appear or timeout.
3. `GET http://localhost:8100/modeladmin/review-candidates?limit=100` returns 200 and no new candidates from this phase.
4. Applies to both mocked lane and nightly real-ADI lane.

## Phase 3: Upload 5 Standard GRNs (v0)

Upload these files:

- `procurement_automation/training-data/procurement-dataset.v0/goods-receipt-note/GRN-2024-200.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/goods-receipt-note/GRN-2024-201.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/goods-receipt-note/GRN-2024-202.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/goods-receipt-note/GRN-2024-203.pdf`
- `procurement_automation/training-data/procurement-dataset.v0/goods-receipt-note/GRN-2024-204.pdf`

Expected outcome:

- All ingested successfully.
- No low-confidence review candidates created.

### Automation Assertions

1. Upload exactly 5 standard GRN files via `POST http://localhost:8000/upload/` and assert success for each call.
2. Poll `GET http://localhost:8000/documents/?limit=500` until 5 standard GRN documents appear or timeout.
3. `GET http://localhost:8100/modeladmin/review-candidates?limit=100` returns 200 and no new low-confidence candidates from this phase.
4. Applies to both mocked lane and nightly real-ADI lane.

## Phase 4: Upload 5 Low-Confidence GRNs (v1)

Upload these files:

- `procurement_automation/training-data/procurement-dataset.v1/goods-receipt-note/GRN_low_confidence_001.pdf`
- `procurement_automation/training-data/procurement-dataset.v1/goods-receipt-note/GRN_low_confidence_002.pdf`
- `procurement_automation/training-data/procurement-dataset.v1/goods-receipt-note/GRN_low_confidence_003.pdf`
- `procurement_automation/training-data/procurement-dataset.v1/goods-receipt-note/GRN_low_confidence_004.pdf`
- `procurement_automation/training-data/procurement-dataset.v1/goods-receipt-note/GRN_low_confidence_005.pdf`

Expected outcome:

- Five review candidates are generated.
- Trigger reason is low field confidence.

### Automation Assertions

1. Upload exactly 5 low-confidence GRN files via `POST http://localhost:8000/upload/` and assert success for each call.
2. Poll `GET http://localhost:8100/modeladmin/review-candidates?limit=100` until candidates appear or timeout.
3. Assert exactly 5 new candidates are created for this upload set.
4. Assert candidates are in `pending_review`.
5. Assert trigger reason indicates low field confidence behavior.
6. Applies to both mocked lane and nightly real-ADI lane.

## Phase 5: Review and Approve Candidates in ModelAdmin UI

1. Open ModelAdmin Review Candidates queue.
2. Open each of the five low-confidence candidates.
3. Set label to `goods-receipt-note`.
4. Approve for training.

Expected outcome:

- Five candidates are in approved-for-training state.

### Automation Assertions

1. Use browser automation to open the review queue in ModelAdmin UI.
2. For each of the 5 target candidates, set label `goods-receipt-note` and approve.
3. `GET http://localhost:8100/modeladmin/review-candidates?limit=100` confirms all 5 candidates are `approved_for_training`.
4. Applies to both mocked lane and nightly real-ADI lane.

## Phase 6: Create Training Dataset

1. Create a new training dataset from approved items.
2. Name it (example: `procurement-dataset.v1-grn-low-confidence-fix`).

Expected outcome:

- Dataset created and ready for sidecar validation.

### Automation Assertions

1. Create a dataset from approved candidates via UI flow or `POST http://localhost:8100/modeladmin/training-datasets`.
2. Assert creation response is successful.
3. `GET http://localhost:8100/modeladmin/training-datasets` contains the new dataset.
4. `GET http://localhost:8100/modeladmin/training-datasets/{dataset_id}` confirms expected members were included.
5. Applies to both mocked lane and nightly real-ADI lane.

## Phase 7: Upload Sidecars and Recheck

If sidecars are missing in dataset checks, run:

```powershell
.\procurement_automation\scripts\upload-sidecars-with-guid-prefix.ps1 `
  -DatasetRoot "training-data/procurement-dataset.v1" `
  -ContainerName "training-data"
```

Expected outcome:

- Missing sidecars are uploaded to blob storage with matching GUID-prefixed names.
- Dataset sidecar checks become green.

### Automation Assertions

1. Run `upload-sidecars-with-guid-prefix.ps1` and assert script exits successfully.
2. `POST http://localhost:8100/modeladmin/training-datasets/{dataset_id}/recheck` returns 200.
3. Recheck response reports sidecar readiness success.
4. `GET http://localhost:8100/modeladmin/training-datasets/{dataset_id}/class-counts` returns expected class counts for retraining readiness.
5. Applies to both mocked lane and nightly real-ADI lane.

## Phase 8: Approve Dataset and Start Training

1. Approve dataset for training.
2. Click Start Training.
3. Monitor progress until all model build steps complete.

Expected outcome:

- New model artifacts are created successfully.

### Automation Assertions

1. Use browser automation to approve dataset and click Start Training.
2. `GET http://localhost:8100/modeladmin/training-jobs` returns a new job linked to the dataset.
3. Poll `GET http://localhost:8100/modeladmin/training-jobs/{job_id}` until terminal state or timeout.
4. Mocked lane expectation: success within short timeout budget.
5. Nightly lane expectation: success within extended timeout budget for real ADI.

## Phase 9: Activate v1 Compose Model

1. Open compose model list.
2. Confirm v0 is currently active and v1 exists.
3. Activate v1.

Expected outcome:

- Active compose model is now v1.

### Automation Assertions

1. Use browser automation to activate v1 compose model from model list UI.
2. `GET http://localhost:8100/modeladmin/models/active` returns 200 and active compose model id equals expected v1 id for the run.
3. Applies to both mocked lane and nightly real-ADI lane.

## Phase 10: Re-Validate with Same 5 Low-Confidence GRNs

Re-upload the same five files from Phase 4.

Expected outcome:

- All five process successfully.
- No new review candidates are created.

### Automation Assertions

1. Re-upload the same 5 low-confidence GRN files from Phase 4 and assert upload success.
2. Poll `GET http://localhost:8000/documents/?limit=500` until processing completes or timeout.
3. `GET http://localhost:8100/modeladmin/review-candidates?limit=200` confirms no new candidates were created by the re-upload set.
4. This is the primary regression guard and applies to both mocked lane and nightly real-ADI lane.

## Phase C: Agent Automation Coverage

The table below identifies what an agent can run directly from this guide.

| Step | Automation Level | Notes |
|---|---|---|
| Phase 0 prep (`prepare-demo.py`) | Fully automatable | One command handles reset, seed, bootstrap, verification |
| Phase 1-4 document uploads | Semi-automatable | Agent can run upload commands if upload endpoint/CLI and auth are provided |
| Candidate list/count verification | Fully automatable | API calls can assert candidate counts by phase |
| Candidate labeling and approval | Manual-only by default | Requires review decisions in UI unless a dedicated approval API workflow is approved |
| Dataset creation | Semi-automatable | Can be API-driven if endpoint + naming convention provided |
| Sidecar upload (`upload-sidecars-with-guid-prefix.ps1`) | Fully automatable | Deterministic utility script |
| Training start and status polling | Semi-automatable | Start and poll can be scripted if endpoints are stable |
| Compose model activation | Semi-automatable | Can be automated through ModelAdmin API if enabled |
| Final re-validation checks | Fully automatable | Re-upload + API assertions for zero new candidates |

## Agent-Ready Command Blocks

### 1. Dry-run prep

```powershell
python procurement_automation/scripts/prepare-demo.py --dry-run
```

### 2. Real prep

```powershell
python procurement_automation/scripts/prepare-demo.py
```

### 3. Sidecar upload for v1

```powershell
.\procurement_automation\scripts\upload-sidecars-with-guid-prefix.ps1 `
  -DatasetRoot "training-data/procurement-dataset.v1" `
  -ContainerName "training-data"
```

### 4. Candidate count checkpoint

```powershell
Invoke-RestMethod "http://localhost:8100/modeladmin/review-candidates?limit=100"
```

### 5. Active model checkpoint

```powershell
Invoke-RestMethod "http://localhost:8100/modeladmin/models/active"
```

## Notes

- Keep sidecar upload separate from baseline setup by design.
- At demo start, training-data must align to v0 seed files only.
- Consolidated setup/reset flow is `prepare-demo.py`; keep sidecar upload as a separate step.
