let page = 1;
const limit = 20;
let pagination = { page: 1, total_pages: 1, total: 0 };
const itemsById = new Map();
const busyById = new Set();
const LABEL_OPTIONS = ['invoice', 'purchase-order', 'goods-receipt-note'];

const tableBody = document.getElementById('tableBody');
const errorBox = document.getElementById('errorBox');
const messageBox = document.getElementById('messageBox');
const paginationInfo = document.getElementById('paginationInfo');

function setError(message) {
  if (!message) {
    errorBox.classList.add('hidden');
    errorBox.textContent = '';
    return;
  }
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

function setMessage(message) {
  if (!message) {
    messageBox.classList.add('hidden');
    messageBox.textContent = '';
    return;
  }
  messageBox.textContent = message;
  messageBox.classList.remove('hidden');
}

function toUiLabel(storageLabel) {
  if (storageLabel === 'invoices') {
    return 'invoice';
  }
  return LABEL_OPTIONS.includes(storageLabel) ? storageLabel : '';
}

function canLabel(item) {
  return item.status !== 'approved_for_training' && item.status !== 'archived';
}

function canApprove(item) {
  return item.status === 'new' || item.status === 'reviewed';
}

function canReject(item) {
  return item.status === 'new' || item.status === 'reviewed';
}

function isBusy(candidateId) {
  return busyById.has(candidateId);
}

function getSelectedLabel(candidateId) {
  const select = document.getElementById(`labelSelect-${candidateId}`);
  return select ? select.value : '';
}

function buildQuery() {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('limit', String(limit));
  params.set('sort_by', 'created_at');
  params.set('sort_order', 'desc');

  const status = document.getElementById('statusFilter').value.trim();
  const documentType = document.getElementById('docTypeFilter').value.trim();
  const modelVersion = document.getElementById('modelVersionFilter').value.trim();
  const minConfidence = document.getElementById('minConfidenceFilter').value.trim();
  const maxConfidence = document.getElementById('maxConfidenceFilter').value.trim();

  if (status) params.set('status', status);
  if (documentType) params.set('document_type', documentType);
  if (modelVersion) params.set('compose_model_id', modelVersion);
  if (minConfidence) params.set('min_confidence', minConfidence);
  if (maxConfidence) params.set('max_confidence', maxConfidence);

  return params.toString();
}

function renderLowFieldsSummary(item) {
  if (item.trigger_reason !== 'low_field_confidence') {
    return '-';
  }

  const fields = Array.isArray(item.low_confidence_fields)
    ? item.low_confidence_fields.filter((value) => typeof value === 'string' && value.trim().length > 0)
    : [];

  const count = Number.isFinite(item.low_confidence_field_count)
    ? Number(item.low_confidence_field_count)
    : fields.length;

  if (!fields.length && count > 0) {
    return `${count} field${count === 1 ? '' : 's'}`;
  }

  if (!fields.length) {
    return '-';
  }

  const shown = fields.slice(0, 3).join(', ');
  const remaining = Math.max(0, count - 3);
  return remaining > 0 ? `${shown} +${remaining} more` : shown;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function getBlobName(item) {
  const fullPath = item.blob_path || item.original_filename || item.document_id || item.id || '-';
  const parts = String(fullPath).split(/[\\/]/);
  const blobName = parts[parts.length - 1] || String(fullPath);
  const shortName = blobName.length > 8 ? `...${blobName.slice(-8)}` : blobName;

  return {
    fullName: blobName,
    shortName,
  };
}

function renderActionCell(item) {
  if (item.status === 'approved_for_training') {
    return `
    <td>
      <select id="labelSelect-${item.id}" data-candidate-id="${item.id}" class="row-label-select" disabled>
        <option value="">Select label</option>
        <option value="invoice" ${toUiLabel(item.operator_label) === 'invoice' ? 'selected' : ''}>invoice</option>
        <option value="purchase-order" ${toUiLabel(item.operator_label) === 'purchase-order' ? 'selected' : ''}>purchase-order</option>
        <option value="goods-receipt-note" ${toUiLabel(item.operator_label) === 'goods-receipt-note' ? 'selected' : ''}>goods-receipt-note</option>
      </select>
    </td>
    <td><button type="button" class="row-approve-btn approved-state" disabled>Approved</button></td>
  `;
  }

  const selected = toUiLabel(item.operator_label);
  const disabledLabel = isBusy(item.id) || !canLabel(item);
  const disabledApprove = isBusy(item.id) || !canApprove(item) || !selected;
  const disabledReject = isBusy(item.id) || !canReject(item);

  return `
    <td>
      <select id="labelSelect-${item.id}" data-candidate-id="${item.id}" class="row-label-select" ${disabledLabel ? 'disabled' : ''}>
        <option value="">Select label</option>
        <option value="invoice" ${selected === 'invoice' ? 'selected' : ''}>invoice</option>
        <option value="purchase-order" ${selected === 'purchase-order' ? 'selected' : ''}>purchase-order</option>
        <option value="goods-receipt-note" ${selected === 'goods-receipt-note' ? 'selected' : ''}>goods-receipt-note</option>
      </select>
    </td>
    <td>
      <div class="row-actions">
        <button type="button" class="row-approve-btn" data-candidate-id="${item.id}" ${disabledApprove ? 'disabled' : ''}>Approve</button>
        <button type="button" class="row-reject-btn danger" data-candidate-id="${item.id}" ${disabledReject ? 'disabled' : ''}>Reject</button>
      </div>
    </td>
  `;
}

function renderRows(items) {
  itemsById.clear();
  items.forEach((item) => itemsById.set(item.id, item));

  if (!items.length) {
    tableBody.innerHTML = '<tr><td colspan="9">No candidates found</td></tr>';
    return;
  }

  tableBody.innerHTML = items
    .map((item) => {
      const created = item.created_at ? new Date(item.created_at).toLocaleString() : '-';
      const { fullName, shortName } = getBlobName(item);

      return `
        <tr id="row-${item.id}">
          <td><span title="${escapeHtml(fullName)}">${escapeHtml(shortName)}</span></td>
          <td>${item.predicted_document_type || '-'}</td>
          <td>${item.classification_confidence ?? '-'}</td>
          <td>${item.trigger_reason || '-'}</td>
          <td>${renderLowFieldsSummary(item)}</td>
          <td>${item.compose_model_id || '-'}</td>
          <td>${created}</td>
          ${renderActionCell(item)}
        </tr>
      `;
    })
    .join('');
}

function refreshRow(candidate) {
  const row = document.getElementById(`row-${candidate.id}`);
  if (!row) {
    return;
  }

  itemsById.set(candidate.id, candidate);

  const created = candidate.created_at ? new Date(candidate.created_at).toLocaleString() : '-';
  const { fullName, shortName } = getBlobName(candidate);

  row.innerHTML = `
    <td><span title="${escapeHtml(fullName)}">${escapeHtml(shortName)}</span></td>
    <td>${candidate.predicted_document_type || '-'}</td>
    <td>${candidate.classification_confidence ?? '-'}</td>
    <td>${candidate.trigger_reason || '-'}</td>
    <td>${renderLowFieldsSummary(candidate)}</td>
    <td>${candidate.compose_model_id || '-'}</td>
    <td>${created}</td>
    ${renderActionCell(candidate)}
  `;
}

async function callActionEndpoint(candidateId, action, payload) {
  const endpoint = `/modeladmin/review-candidates/${candidateId}/${action}`;
  const response = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {}),
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Action '${action}' failed`);
  }

  return response.json();
}

async function handleLabelChange(candidateId) {
  const item = itemsById.get(candidateId);
  if (!item || isBusy(candidateId) || !canLabel(item)) {
    return;
  }

  const selectedLabel = getSelectedLabel(candidateId);
  if (!selectedLabel) {
    return;
  }

  busyById.add(candidateId);
  refreshRow(item);
  setError('');
  setMessage('');

  try {
    const data = await callActionEndpoint(candidateId, 'label', { label: selectedLabel });
    refreshRow(data.item);
    setMessage(`Label saved for candidate ${candidateId.slice(0, 8)}...`);
  } catch (error) {
    const failed = itemsById.get(candidateId) || item;
    refreshRow(failed);
    setError(error.message || 'Failed to save label');
  } finally {
    busyById.delete(candidateId);
    const latest = itemsById.get(candidateId);
    if (latest) {
      refreshRow(latest);
    }
  }
}

async function handleApprove(candidateId) {
  const item = itemsById.get(candidateId);
  if (!item || isBusy(candidateId) || !canApprove(item)) {
    return;
  }

  const selectedLabel = getSelectedLabel(candidateId);
  if (!selectedLabel) {
    setError('Select an operator label before approving.');
    return;
  }

  busyById.add(candidateId);
  refreshRow(item);
  setError('');
  setMessage('');

  try {
    const currentUiLabel = toUiLabel(item.operator_label);
    let currentItem = item;

    if (currentUiLabel !== selectedLabel) {
      const labelResult = await callActionEndpoint(candidateId, 'label', { label: selectedLabel });
      currentItem = labelResult.item;
      refreshRow(currentItem);
    }

    const approveResult = await callActionEndpoint(candidateId, 'approve', {});
    refreshRow(approveResult.item);
    setMessage(`Candidate ${candidateId.slice(0, 8)}... approved.`);
  } catch (error) {
    const failed = itemsById.get(candidateId) || item;
    refreshRow(failed);
    setError(error.message || 'Failed to approve candidate');
  } finally {
    busyById.delete(candidateId);
    const latest = itemsById.get(candidateId);
    if (latest) {
      refreshRow(latest);
    }
  }
}

async function handleReject(candidateId) {
  const item = itemsById.get(candidateId);
  if (!item || isBusy(candidateId) || !canReject(item)) {
    return;
  }

  busyById.add(candidateId);
  refreshRow(item);
  setError('');
  setMessage('');

  try {
    const rejectResult = await callActionEndpoint(candidateId, 'reject', {});
    refreshRow(rejectResult.item);
    setMessage(`Candidate ${candidateId.slice(0, 8)}... moved back to new.`);
  } catch (error) {
    const failed = itemsById.get(candidateId) || item;
    refreshRow(failed);
    setError(error.message || 'Failed to reject candidate');
  } finally {
    busyById.delete(candidateId);
    const latest = itemsById.get(candidateId);
    if (latest) {
      refreshRow(latest);
    }
  }
}

async function loadCandidates() {
  setError('');
  setMessage('');
  try {
    const response = await fetch(`/modeladmin/review-candidates?${buildQuery()}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to load review candidates');
    }

    const data = await response.json();
    const items = data.items || [];
    pagination = data.pagination || { page: 1, total_pages: 1, total: 0 };

    renderRows(items);
    paginationInfo.textContent = `Total: ${pagination.total || 0} • Page ${pagination.page || 1} of ${Math.max(1, pagination.total_pages || 1)}`;

    document.getElementById('prevBtn').disabled = (pagination.page || 1) <= 1;
    document.getElementById('nextBtn').disabled = (pagination.page || 1) >= Math.max(1, pagination.total_pages || 1);
  } catch (error) {
    setError(error.message || 'Failed to load review candidates');
    renderRows([]);
  }
}

document.getElementById('applyFiltersBtn').addEventListener('click', () => {
  page = 1;
  loadCandidates();
});

document.getElementById('clearFiltersBtn').addEventListener('click', () => {
  document.getElementById('statusFilter').value = '';
  document.getElementById('docTypeFilter').value = '';
  document.getElementById('modelVersionFilter').value = '';
  document.getElementById('minConfidenceFilter').value = '';
  document.getElementById('maxConfidenceFilter').value = '';
  page = 1;
  loadCandidates();
});

document.getElementById('prevBtn').addEventListener('click', () => {
  if (page > 1) {
    page -= 1;
    loadCandidates();
  }
});

document.getElementById('nextBtn').addEventListener('click', () => {
  if (page < Math.max(1, pagination.total_pages || 1)) {
    page += 1;
    loadCandidates();
  }
});

tableBody.addEventListener('change', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) {
    return;
  }
  if (!target.classList.contains('row-label-select')) {
    return;
  }

  const candidateId = target.dataset.candidateId;
  if (candidateId) {
    handleLabelChange(candidateId);
  }
});

tableBody.addEventListener('click', (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) {
    return;
  }

  const candidateId = target.dataset.candidateId;
  if (!candidateId) {
    return;
  }

  if (target.classList.contains('row-approve-btn')) {
    handleApprove(candidateId);
    return;
  }

  if (target.classList.contains('row-reject-btn')) {
    handleReject(candidateId);
  }
});

loadCandidates();
