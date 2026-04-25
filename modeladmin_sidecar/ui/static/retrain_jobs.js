const errorBox = document.getElementById('errorBox');
const tableBody = document.getElementById('tableBody');

function setError(message) {
  if (!message) {
    errorBox.classList.add('hidden');
    errorBox.textContent = '';
    return;
  }
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

function formatDate(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function formatExtractors(extractors) {
  if (!Array.isArray(extractors) || !extractors.length) return '-';
  return extractors.join(', ');
}

function activeBadge(isActive) {
  return isActive ? '<span class="badge badge-succeeded">active</span>' : '<span class="badge">inactive</span>';
}

async function activateModel(modelId) {
  setError('');
  try {
    const response = await fetch(`/modeladmin/models/${encodeURIComponent(modelId)}/activate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to activate model');
    }

    await loadComposeModels();
  } catch (error) {
    setError(error.message || 'Failed to activate model');
  }
}

function renderRows(items) {
  if (!items.length) {
    tableBody.innerHTML = '<tr><td colspan="6">No compose models available in cache.</td></tr>';
    return;
  }

  tableBody.innerHTML = items.map((item) => {
    const button = item.is_active
      ? '<button type="button" disabled>Active</button>'
      : `<button type="button" data-model-id="${item.model_id}">Activate</button>`;

    return `
      <tr>
        <td>${item.model_id}</td>
        <td>${formatDate(item.adi_created_at)}</td>
        <td>${item.classifier_model_id || '-'}</td>
        <td>${formatExtractors(item.extractor_models)}</td>
        <td>${activeBadge(Boolean(item.is_active))}</td>
        <td>${button}</td>
      </tr>
    `;
  }).join('');

  tableBody.querySelectorAll('button[data-model-id]').forEach((button) => {
    button.addEventListener('click', () => activateModel(button.dataset.modelId));
  });
}

async function loadComposeModels() {
  setError('');
  try {
    const response = await fetch('/modeladmin/models/compose');
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to load compose models');
    }

    const data = await response.json();
    renderRows(data.items || []);
  } catch (error) {
    setError(error.message || 'Failed to load compose models');
  }
}

loadComposeModels();
