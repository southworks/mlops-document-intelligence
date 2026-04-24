let page = 1;
const limit = 20;
let pagination = { page: 1, total_pages: 1, total: 0 };
let selectedCandidateIds = new Set();

const tableBody = document.getElementById('tableBody');
const errorBox = document.getElementById('errorBox');
const paginationInfo = document.getElementById('paginationInfo');
const selectAllCheckbox = document.getElementById('selectAllCheckbox');
const actionBar = document.getElementById('actionBar');
const selectionCountText = document.getElementById('selectionCountText');

function updateActionBarState() {
  const selectedCount = selectedCandidateIds.size;
  selectionCountText.textContent = String(selectedCount);
  actionBar.classList.toggle('hidden', selectedCount === 0);
}

function setError(message) {
  if (!message) {
    errorBox.classList.add('hidden');
    errorBox.textContent = '';
    return;
  }
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

function updateSelectionHeaderState() {
  const rowCheckboxes = Array.from(document.querySelectorAll('.row-checkbox'));
  if (!rowCheckboxes.length) {
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
    return;
  }

  const selectedOnPage = rowCheckboxes.filter((checkbox) => checkbox.checked).length;
  selectAllCheckbox.checked = selectedOnPage > 0 && selectedOnPage === rowCheckboxes.length;
  selectAllCheckbox.indeterminate = selectedOnPage > 0 && selectedOnPage < rowCheckboxes.length;
}

function setSelectedRowState(checkbox, isSelected) {
  const row = checkbox.closest('tr');
  if (!row) return;
  row.classList.toggle('selected', isSelected);
}

function attachSelectionHandlers() {
  const rowCheckboxes = document.querySelectorAll('.row-checkbox');
  rowCheckboxes.forEach((checkbox) => {
    checkbox.addEventListener('change', (event) => {
      const candidateId = event.target.dataset.candidateId;
      if (!candidateId) return;

      if (event.target.checked) {
        selectedCandidateIds.add(candidateId);
      } else {
        selectedCandidateIds.delete(candidateId);
      }

      setSelectedRowState(event.target, event.target.checked);
      updateSelectionHeaderState();
      updateActionBarState();
    });
  });
}

function buildQuery() {
  const params = new URLSearchParams();
  params.set('page', String(page));
  params.set('limit', String(limit));
  params.set('sort_by', 'updated_at');
  params.set('sort_order', 'desc');
  params.set('status', 'approved_for_training');

  const documentType = document.getElementById('docTypeFilter').value.trim();
  const modelVersion = document.getElementById('modelVersionFilter').value.trim();

  if (documentType) params.set('document_type', documentType);
  if (modelVersion) params.set('compose_model_id', modelVersion);

  return params.toString();
}

function renderRows(items) {
  if (!items.length) {
    tableBody.innerHTML = '<tr><td colspan="9">No approved candidates found</td></tr>';
    updateSelectionHeaderState();
    updateActionBarState();
    return;
  }

  tableBody.innerHTML = items
    .map((item) => {
      const approvedAt = item.approved_at ? new Date(item.approved_at).toLocaleString() : '-';
      const shortId = item.id ? `${item.id.slice(0, 8)}...` : '-';
      const href = `/modeladmin/ui/candidates/${item.id}`;
      const isSelected = selectedCandidateIds.has(item.id);

      return `
        <tr class="${isSelected ? 'selected' : ''}">
          <td class="checkbox-col">
            <input type="checkbox" class="row-checkbox" data-candidate-id="${item.id}" ${isSelected ? 'checked' : ''} aria-label="Select ${shortId}" />
          </td>
          <td>${shortId}</td>
          <td>${item.status || '-'}</td>
          <td>${item.predicted_document_type || '-'}</td>
          <td>${item.classification_confidence ?? '-'}</td>
          <td>${item.operator_label || '-'}</td>
          <td>${item.compose_model_id || '-'}</td>
          <td>${approvedAt}</td>
          <td><a class="link" href="${href}">Open</a></td>
        </tr>
      `;
    })
    .join('');

  attachSelectionHandlers();
  updateSelectionHeaderState();
  updateActionBarState();
}

async function loadCandidates() {
  setError('');
  try {
    const response = await fetch(`/modeladmin/review-candidates?${buildQuery()}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to load approved candidates');
    }

    const data = await response.json();
    const items = data.items || [];
    pagination = data.pagination || { page: 1, total_pages: 1, total: 0 };

    renderRows(items);
    paginationInfo.textContent = `Total: ${pagination.total || 0} • Page ${pagination.page || 1} of ${Math.max(1, pagination.total_pages || 1)}`;

    document.getElementById('prevBtn').disabled = (pagination.page || 1) <= 1;
    document.getElementById('nextBtn').disabled = (pagination.page || 1) >= Math.max(1, pagination.total_pages || 1);
  } catch (error) {
    setError(error.message || 'Failed to load approved candidates');
    renderRows([]);
  }
}

selectAllCheckbox.addEventListener('change', (event) => {
  const rowCheckboxes = document.querySelectorAll('.row-checkbox');
  rowCheckboxes.forEach((checkbox) => {
    checkbox.checked = event.target.checked;
    const candidateId = checkbox.dataset.candidateId;
    if (!candidateId) return;

    if (event.target.checked) {
      selectedCandidateIds.add(candidateId);
    } else {
      selectedCandidateIds.delete(candidateId);
    }

    setSelectedRowState(checkbox, event.target.checked);
  });

  updateSelectionHeaderState();
  updateActionBarState();
});

document.getElementById('createDatasetBtn').addEventListener('click', async () => {
  const datasetName = document.getElementById('datasetNameInput').value.trim();
  const createButton = document.getElementById('createDatasetBtn');

  if (!datasetName) {
    setError('Dataset name is required');
    return;
  }

  if (selectedCandidateIds.size === 0) {
    setError('Select at least one candidate');
    return;
  }

  setError('');
  createButton.disabled = true;

  try {
    const response = await fetch('/modeladmin/training-datasets', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: datasetName,
        created_by: 'demo',
        candidate_ids: Array.from(selectedCandidateIds),
      }),
    });

    const responseBody = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(responseBody.detail || 'Failed to create dataset');
    }

    const datasetId = responseBody?.item?.id || responseBody?.id;
    if (!datasetId) {
      throw new Error('Dataset created but ID was not returned');
    }

    window.location.href = `/modeladmin/ui/datasets/${datasetId}`;
  } catch (error) {
    setError(error.message || 'Failed to create dataset');
  } finally {
    createButton.disabled = false;
  }
});

document.getElementById('clearSelectionBtn').addEventListener('click', () => {
  selectedCandidateIds = new Set();
  document.querySelectorAll('.row-checkbox').forEach((checkbox) => {
    checkbox.checked = false;
    setSelectedRowState(checkbox, false);
  });
  updateSelectionHeaderState();
  updateActionBarState();
});

document.getElementById('applyFiltersBtn').addEventListener('click', () => {
  page = 1;
  selectedCandidateIds = new Set();
  updateActionBarState();
  loadCandidates();
});

document.getElementById('clearFiltersBtn').addEventListener('click', () => {
  document.getElementById('docTypeFilter').value = '';
  document.getElementById('modelVersionFilter').value = '';
  page = 1;
  selectedCandidateIds = new Set();
  updateActionBarState();
  loadCandidates();
});

document.getElementById('prevBtn').addEventListener('click', () => {
  if (page > 1) {
    page -= 1;
    selectedCandidateIds = new Set();
    updateActionBarState();
    loadCandidates();
  }
});

document.getElementById('nextBtn').addEventListener('click', () => {
  if (page < Math.max(1, pagination.total_pages || 1)) {
    page += 1;
    selectedCandidateIds = new Set();
    updateActionBarState();
    loadCandidates();
  }
});

loadCandidates();
