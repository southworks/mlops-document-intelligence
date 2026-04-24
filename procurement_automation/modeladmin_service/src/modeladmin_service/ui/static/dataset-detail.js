const errorBox = document.getElementById('errorBox');
const successBox = document.getElementById('successBox');
const membershipTableBody = document.getElementById('membershipTableBody');

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

function getDatasetIdFromUrl() {
  const pathSegments = window.location.pathname.split('/');
  return pathSegments[pathSegments.length - 1];
}

async function loadDataset() {
  const datasetId = getDatasetIdFromUrl();

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to load dataset');
    }

    const data = await response.json();
    const item = data.item || {};
    const membership = data.membership || [];

    // Populate dataset info
    document.getElementById('datasetTitle').textContent = item.name || 'Training Dataset';
    document.getElementById('datasetStatus').textContent = item.status || 'unknown';
    document.getElementById('datasetId').textContent = item.id || '-';
    document.getElementById('datasetName').textContent = item.name || '-';
    document.getElementById('infoStatus').textContent = item.status || '-';
    document.getElementById('createdBy').textContent = item.created_by || '-';
    document.getElementById('membershipCount').textContent = item.membership_count || 0;

    if (item.created_at) {
      const createdDate = new Date(item.created_at);
      document.getElementById('createdAt').textContent = createdDate.toLocaleString();
    } else {
      document.getElementById('createdAt').textContent = '-';
    }

    // Populate membership table
    if (membership.length === 0) {
      membershipTableBody.innerHTML = '<tr><td colspan="2">No candidates in dataset</td></tr>';
    } else {
      membershipTableBody.innerHTML = membership
        .map((member) => {
          return `
            <tr>
              <td>${member.candidate_id}</td>
              <td>${member.compose_model_id || '-'}</td>
            </tr>
          `;
        })
        .join('');
    }

    // Update UI state based on status
    const stageBtn = document.getElementById('stageBtn');
    const markReadyBtn = document.getElementById('markReadyBtn');
    
    if (item.status === 'draft') {
      stageBtn.disabled = false;
      markReadyBtn.disabled = true;
      document.getElementById('readyDescription').textContent = 'First, stage this dataset before marking it ready.';
    } else if (item.status === 'staged') {
      stageBtn.disabled = true;
      markReadyBtn.disabled = false;
      document.getElementById('stageDescription').textContent = 'This dataset is already staged.';
    } else {
      stageBtn.disabled = true;
      markReadyBtn.disabled = true;
      document.getElementById('stageDescription').textContent = 'This dataset is no longer in draft or staged status.';
      document.getElementById('readyDescription').textContent = 'This dataset is no longer in draft status and cannot be modified.';
    }
  } catch (error) {
    setError(error.message || 'Failed to load dataset');
  }
}

document.getElementById('markReadyBtn').addEventListener('click', async () => {
  const datasetId = getDatasetIdFromUrl();
  const minItemsPerClass = parseInt(document.getElementById('minItemsInput').value, 10);

  if (isNaN(minItemsPerClass) || minItemsPerClass < 1) {
    setError('Minimum items per class must be a number >= 1');
    return;
  }

  const btn = document.getElementById('markReadyBtn');
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'Marking ready...';

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}/mark-ready`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        min_items_per_class: minItemsPerClass,
      }),
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to mark dataset ready');
    }

    const data = await response.json();
    if (data.success) {
      setSuccess('Dataset marked as ready for training');
      await loadDataset(); // Reload to update status
    } else {
      throw new Error('Unexpected response format');
    }
  } catch (error) {
    setError(error.message || 'Failed to mark dataset ready');
    btn.disabled = false;
    btn.textContent = originalText;
  }
});

document.getElementById('stageBtn').addEventListener('click', async () => {
  const datasetId = getDatasetIdFromUrl();
  const btn = document.getElementById('stageBtn');
  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'Staging...';

  try {
    const response = await fetch(`/modeladmin/training-datasets/${datasetId}/stage`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to stage dataset');
    }

    const data = await response.json();
    if (data.success) {
      setSuccess('Dataset staged successfully');
      await loadDataset(); // Reload to update status
    } else {
      throw new Error('Unexpected response format');
    }
  } catch (error) {
    setError(error.message || 'Failed to stage dataset');
    btn.disabled = false;
    btn.textContent = originalText;
  }
});

loadDataset();
