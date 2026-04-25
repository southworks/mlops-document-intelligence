const datasetId = window.location.pathname.split('/').at(-1);
let dataset = null;
let members = [];

const errorBox = document.getElementById('errorBox');
const successBox = document.getElementById('successBox');
const memberTableBody = document.getElementById('memberTableBody');
const stageBtn = document.getElementById('stageBtn');
const recheckBtn = document.getElementById('recheckBtn');
const markReadyBtn = document.getElementById('markReadyBtn');
const startTrainingBtn = document.getElementById('startTrainingBtn');
const actionArea = document.getElementById('actionArea');
const actionHint = document.getElementById('actionHint');
const memberSummary = document.getElementById('memberSummary');
const recheckResultSection = document.getElementById('recheckResultSection');
const recheckBanner = document.getElementById('recheckBanner');
const recheckTableBody = document.getElementById('recheckTableBody');

function setError(message) {
  if (!message) {
    errorBox.classList.add('hidden');
    errorBox.textContent = '';
    return;
  }
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
  successBox.classList.add('hidden');
}

function setSuccess(message) {
  if (!message) {
    successBox.classList.add('hidden');
    successBox.textContent = '';
    return;
  }
  successBox.textContent = message;
  successBox.classList.remove('hidden');
  errorBox.classList.add('hidden');
}

function statusBadgeHtml(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

/** Render per-class member count summary with warnings for classes below threshold. */
function renderPerClassSummary(memberList) {
  const MIN_CLASS = 5;
  const counts = {};
  memberList.forEach((m) => {
    const label = m.operator_label || 'unknown';
    counts[label] = (counts[label] || 0) + 1;
  });

  if (Object.keys(counts).length === 0) {
    memberSummary.innerHTML = '<span class="muted">No members yet.</span>';
    return;
  }

  memberSummary.innerHTML = Object.entries(counts)
    .map(([label, count]) => {
      const warnClass = count < MIN_CLASS ? ' warn' : '';
      return `<span class="label-count${warnClass}">${label}: <strong>${count}</strong></span>`;
    })
    .join('');
}

/** Render the per-file recheck results table. */
function renderRecheckResults(results, allVerified) {
  recheckResultSection.classList.remove('hidden');

  if (allVerified) {
    recheckBanner.innerHTML = '<p class="success">All sidecar files are present and all labels match fields.json.</p>';
    markReadyBtn.disabled = false;
    markReadyBtn.title = '';
  } else {
    const missingSidecars = results.filter((r) => !r.has_ocr || !r.has_labels);
    const schemaMismatches = results.filter((r) => r.has_labels && r.has_schema_match === false);

    const issues = [];
    if (missingSidecars.length) {
      issues.push(`Missing sidecar files for: ${missingSidecars.map((r) => r.filename).join(', ')}`);
    }
    if (schemaMismatches.length) {
      const schemaText = schemaMismatches
        .map((r) => {
          const missingText = (r.missing_field_keys || []).join(', ');
          const unexpectedText = (r.unexpected_field_keys || []).join(', ');
          if (missingText && unexpectedText) {
            return `${r.filename} (missing: ${missingText}; unexpected: ${unexpectedText})`;
          }
          if (missingText) {
            return `${r.filename} (missing: ${missingText})`;
          }
          if (unexpectedText) {
            return `${r.filename} (unexpected: ${unexpectedText})`;
          }
          return `${r.filename} (schema mismatch)`;
        })
        .join('; ');
      issues.push(`Fields mismatch between labels.json and fields.json: ${schemaText}`);
    }

    recheckBanner.innerHTML = `<p class="error">${issues.join(' | ')}</p>`;
    markReadyBtn.disabled = true;
    markReadyBtn.title = 'Missing sidecars or labels/fields.json schema mismatch';
  }

  recheckTableBody.innerHTML = results
    .map((r) => {
      const ocrIcon = r.has_ocr ? '✅' : '❌';
      const labelsIcon = r.has_labels ? '✅' : '❌';
      const missingText = (r.missing_field_keys || []).join(', ');
      const unexpectedText = (r.unexpected_field_keys || []).join(', ');
      const schemaIcon = r.has_schema_match === false
        ? `❌ missing: ${missingText || '-'} | unexpected: ${unexpectedText || '-'}`
        : '✅';
      return `<tr><td>${r.doc_type}</td><td>${r.filename}</td><td>${ocrIcon}</td><td>${labelsIcon}</td><td>${schemaIcon}</td></tr>`;
    })
    .join('');
}

function isVerificationComplete() {
  if (!dataset || !dataset.label_verification_status) {
    return false;
  }

  try {
    const savedResults = JSON.parse(dataset.label_verification_status);
    if (!Array.isArray(savedResults) || savedResults.length === 0) {
      return false;
    }
    return savedResults.every((r) => r.has_ocr && r.has_labels && (r.has_schema_match !== false));
  } catch (_) {
    return false;
  }
}

/** Show/hide and enable/disable the mark-ready button based on dataset state. */
function updateActionArea() {
  if (!dataset) return;

  if (dataset.status === 'draft') {
    actionArea.classList.remove('hidden');
    stageBtn.classList.remove('hidden');
    recheckBtn.classList.remove('hidden');
    recheckBtn.disabled = false;
    markReadyBtn.classList.add('hidden');
    startTrainingBtn.classList.add('hidden');

    if (members.length > 0) {
      stageBtn.disabled = false;
      stageBtn.title = '';
      actionHint.textContent = 'Stage dataset to copy selected blobs to training-data.';
    } else {
      stageBtn.disabled = true;
      stageBtn.title = 'Add at least one member';
      actionHint.textContent = 'Add at least one member before staging.';
    }
  } else if (dataset.status === 'staged') {
    actionArea.classList.remove('hidden');
    stageBtn.classList.add('hidden');
    recheckBtn.classList.remove('hidden');
    recheckBtn.disabled = false;
    markReadyBtn.classList.remove('hidden');
    const verified = isVerificationComplete();
    markReadyBtn.disabled = !verified;
    markReadyBtn.title = verified ? '' : 'Run Check Sidecar Files and ensure sidecars and field schema are valid';
    startTrainingBtn.classList.add('hidden');
    actionHint.textContent = verified
      ? 'All sidecars verified. You can mark ready for retrain.'
      : 'Run Check Sidecar Files and fix any missing sidecars or field mismatches before marking ready.';
  } else if (dataset.status === 'ready_for_retrain') {
    stageBtn.classList.add('hidden');
    recheckBtn.classList.remove('hidden');
    recheckBtn.disabled = false;
    markReadyBtn.classList.add('hidden');
    startTrainingBtn.classList.remove('hidden');
    startTrainingBtn.disabled = false;
    startTrainingBtn.title = '';
    actionArea.classList.remove('hidden');
    actionHint.textContent = 'Dataset is ready. Recheck sidecars anytime or start training to build a new compose model.';
    document.getElementById('mainPage').classList.add('read-only');
  } else {
    stageBtn.classList.add('hidden');
    recheckBtn.classList.remove('hidden');
    recheckBtn.disabled = false;
    markReadyBtn.classList.add('hidden');
    startTrainingBtn.classList.add('hidden');
    actionArea.classList.remove('hidden');
  }
}

stageBtn.addEventListener('click', async () => {
  stageBtn.disabled = true;
  const originalText = stageBtn.textContent;
  stageBtn.textContent = 'Staging\u2026';
  setError('');

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}/stage`, {
      method: 'POST',
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Stage failed');
    }

    setSuccess('Dataset staged. Running sidecar verification...');
    await loadDataset();
    await runRecheck({ auto: true });
  } catch (error) {
    setError(error.message || 'Stage failed');
    stageBtn.disabled = false;
    stageBtn.textContent = originalText;
  }
});

/** Render rows in the members table. Remove button visible only in draft. */
function renderMembers(memberList) {
  const isDraft = dataset && dataset.status === 'draft';

  // Show/hide the Remove column header
  const removeColHeader = document.getElementById('removeColHeader');
  removeColHeader.textContent = isDraft ? 'Action' : '';

  if (!memberList.length) {
    const colspan = isDraft ? 6 : 5;
    memberTableBody.innerHTML = `<tr><td colspan="${colspan}">No members in this dataset.</td></tr>`;
    return;
  }

  memberTableBody.innerHTML = memberList
    .map((m) => {
      const approvedAt = m.approved_at ? new Date(m.approved_at).toLocaleString() : '-';
      const shortDocId = m.document_id ? `${m.document_id.slice(0, 20)}\u2026` : '-';
      const removeCell = isDraft
        ? `<td><button type="button" class="danger" onclick="removeMember('${m.candidate_id}')">Remove</button></td>`
        : '';
      return `
        <tr>
          <td title="${m.document_id}">${shortDocId}</td>
          <td>${m.original_filename || '-'}</td>
          <td>${m.operator_label || '-'}</td>
          <td>${m.compose_model_id || '-'}</td>
          <td>${approvedAt}</td>
          ${removeCell}
        </tr>
      `;
    })
    .join('');
}

async function loadDataset() {
  setError('');
  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to load dataset');
    }

    const data = await response.json();
    dataset = data.item || {};
    members = data.membership || [];

    // Populate header and info card
    document.getElementById('datasetTitle').textContent = dataset.name || 'Training Dataset';
    document.getElementById('datasetStatusBadge').innerHTML = statusBadgeHtml(dataset.status || 'unknown');
    document.getElementById('datasetId').textContent = dataset.id || '-';
    document.getElementById('datasetName').textContent = dataset.name || '-';
    document.getElementById('infoStatus').innerHTML = statusBadgeHtml(dataset.status || 'unknown');
    document.getElementById('createdBy').textContent = dataset.created_by || '-';
    document.getElementById('createdAt').textContent = dataset.created_at
      ? new Date(dataset.created_at).toLocaleString()
      : '-';

    renderPerClassSummary(members);
    renderMembers(members);
    updateActionArea();

    if (dataset.label_verification_status) {
      try {
        const savedResults = JSON.parse(dataset.label_verification_status);
        const allVerified = savedResults.every((r) => r.has_ocr && r.has_labels && (r.has_schema_match !== false));
        renderRecheckResults(savedResults, allVerified);
      } catch (_) {
        // Ignore malformed stored JSON
      }
    }
  } catch (error) {
    setError(error.message || 'Failed to load dataset');
  }
}

/** Remove a single member (draft-only). */
async function removeMember(candidateId) {
  if (!confirm('Remove this document from the dataset?')) return;

  setError('');
  try {
    const response = await fetch(
      `/modeladmin/training-datasets/${datasetId}/members/${candidateId}`,
      { method: 'DELETE' }
    );

    if (response.status === 409) {
      throw new Error('Cannot modify a frozen dataset');
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Remove failed');
    }

    setSuccess('Member removed successfully.');
    await loadDataset();
  } catch (error) {
    setError(error.message || 'Remove failed');
  }
}

async function runRecheck({ auto = false } = {}) {
  recheckBtn.disabled = true;
  const originalText = recheckBtn.textContent;
  recheckBtn.textContent = auto ? 'Auto-checking\u2026' : 'Checking sidecar files\u2026';
  setError('');

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}/recheck`, {
      method: 'POST',
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Recheck failed');
    }

    const result = await response.json();
    dataset.label_verification_status = JSON.stringify(result.results || []);
    renderRecheckResults(result.results, result.all_verified);
    updateActionArea();

    if (result.all_verified) {
      setSuccess('All sidecar files are present and schema is valid. You can now mark ready for retrain.');
      await loadDataset();
    } else {
      setError('Some sidecar files are missing or labels do not match fields.json. Review the table below.');
      markReadyBtn.disabled = true;
      markReadyBtn.title = 'Missing sidecar files or labels/fields.json schema mismatch';
      recheckBtn.disabled = false;
      recheckBtn.textContent = originalText;
    }
  } catch (error) {
    setError(error.message || 'Recheck failed');
    recheckBtn.disabled = false;
    recheckBtn.textContent = originalText;
  }
}

recheckBtn.addEventListener('click', async () => {
  await runRecheck();
});

markReadyBtn.addEventListener('click', async () => {
  if (!isVerificationComplete()) {
    markReadyBtn.disabled = true;
    markReadyBtn.title = 'Run Check Sidecar Files and resolve sidecar/schema issues';
    setError('Cannot mark ready: sidecar files are missing or labels do not match fields.json.');
    return;
  }

  markReadyBtn.disabled = true;
  const originalText = markReadyBtn.textContent;
  markReadyBtn.textContent = 'Marking ready\u2026';
  setError('');

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}/mark-ready`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),  
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Mark ready failed');
    }

    setSuccess('Dataset marked as ready for retrain. Page is now read-only.');
    await loadDataset();
  } catch (error) {
    setError(error.message || 'Mark ready failed');
    markReadyBtn.disabled = false;
    markReadyBtn.textContent = originalText;
  }
});

let trainingJobPollTimer = null;
let currentTrainingJobId = null;

function stopPolling() {
  if (trainingJobPollTimer) {
    clearInterval(trainingJobPollTimer);
    trainingJobPollTimer = null;
  }
}

function renderTrainingJob(job) {
  const panel = document.getElementById('trainingJobPanel');
  panel.classList.remove('hidden');
  document.getElementById('trainingJobId').textContent = job.id;
  document.getElementById('trainingJobStatus').innerHTML = statusBadgeHtml(job.status);

  const ops = job.operations || [];
  const tbody = document.getElementById('trainingJobOpsTable');
  if (!ops.length) {
    tbody.innerHTML = '<tr><td colspan="5">No operations yet.</td></tr>';
  } else {
    tbody.innerHTML = ops
      .map(
        (op) => `
      <tr>
        <td>${op.operation_type}</td>
        <td>${op.doc_type || '-'}</td>
        <td>${op.adi_model_id || '-'}</td>
        <td>${statusBadgeHtml(op.status)}</td>
        <td>${op.error_message || '-'}</td>
      </tr>`
      )
      .join('');
  }

  const pollingIndicator = document.getElementById('trainingJobPollingIndicator');
  const jobBanner = document.getElementById('trainingJobBanner');

  if (job.status === 'completed') {
    startTrainingBtn.disabled = false;
    startTrainingBtn.title = '';
    pollingIndicator.textContent = '';
    const composeOp = ops.find((o) => o.operation_type === 'compose');
    const modelId = composeOp?.adi_model_id || 'N/A';
    jobBanner.innerHTML = `<p class="success">Training complete! Compose model: <strong>${modelId}</strong>. <a href="/modeladmin/ui/retrain-jobs" class="link">View Models</a></p>`;
    stopPolling();
  } else if (job.status === 'failed') {
    startTrainingBtn.disabled = false;
    startTrainingBtn.title = '';
    pollingIndicator.textContent = '';
    jobBanner.innerHTML = `<p class="error">Training failed: ${job.error_message || 'Unknown error'}</p>`;
    stopPolling();
  } else {
    startTrainingBtn.disabled = true;
    startTrainingBtn.title = 'Training is currently running';
    jobBanner.innerHTML = '';
    pollingIndicator.textContent = 'Auto-refreshing every 10\u202fs\u2026';
  }
}

async function pollTrainingJob() {
  if (!currentTrainingJobId) return;
  try {
    const response = await fetch(`/modeladmin/training-jobs/${currentTrainingJobId}`);
    if (!response.ok) return;
    const job = await response.json();
    renderTrainingJob(job);
  } catch (_) {
    // Network error – keep polling
  }
}

startTrainingBtn.addEventListener('click', async () => {
  startTrainingBtn.disabled = true;
  const originalText = startTrainingBtn.textContent;
  startTrainingBtn.textContent = 'Starting training\u2026';
  setError('');
  stopPolling();

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}/start-training`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to start training');
    }

    const body = await response.json();
    const job = body?.item;
    if (!job) throw new Error('Unexpected response from server');

    currentTrainingJobId = job.id;
    renderTrainingJob(job);

    if (job.status !== 'completed' && job.status !== 'failed') {
      trainingJobPollTimer = setInterval(pollTrainingJob, 10000);
    }

    startTrainingBtn.textContent = originalText;
  } catch (error) {
    setError(error.message || 'Failed to start training');
    startTrainingBtn.disabled = false;
    startTrainingBtn.textContent = originalText;
  }
});

loadDataset();
