let page = 1;
const limit = 20;
let pagination = { page: 1, total_pages: 1, total: 0 };

const tableBody = document.getElementById('tableBody');
const errorBox = document.getElementById('errorBox');
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

function statusBadgeHtml(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function renderRows(items) {
  if (!items.length) {
    tableBody.innerHTML = '<tr><td colspan="7">No datasets found</td></tr>';
    return;
  }

  tableBody.innerHTML = items
    .map((item) => {
      const createdAt = item.created_at ? new Date(item.created_at).toLocaleString() : '-';
      const shortId = item.id ? `${item.id.slice(0, 8)}\u2026` : '-';
      const href = `/modeladmin/ui/datasets/${item.id}`;

      return `
        <tr>
          <td>${item.name || '-'}</td>
          <td title="${item.id}">${shortId}</td>
          <td>${statusBadgeHtml(item.status || 'unknown')}</td>
          <td>${item.created_by || '-'}</td>
          <td>${createdAt}</td>
          <td>${item.membership_count ?? '-'}</td>
          <td><a class="link" href="${href}">Open</a></td>
        </tr>
      `;
    })
    .join('');
}

async function loadDatasets() {
  setError('');
  try {
    const params = new URLSearchParams({ page: String(page), limit: String(limit) });
    const response = await fetch(`/modeladmin/training-datasets?${params}`);
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || 'Failed to load datasets');
    }

    const data = await response.json();
    const items = data.items || [];
    pagination = data.pagination || { page: 1, total_pages: 1, total: 0 };

    renderRows(items);
    paginationInfo.textContent = `Total: ${pagination.total || 0} \u2022 Page ${pagination.page || 1} of ${Math.max(1, pagination.total_pages || 1)}`;

    document.getElementById('prevBtn').disabled = (pagination.page || 1) <= 1;
    document.getElementById('nextBtn').disabled =
      (pagination.page || 1) >= Math.max(1, pagination.total_pages || 1);
  } catch (error) {
    setError(error.message || 'Failed to load datasets');
    renderRows([]);
  }
}

document.getElementById('prevBtn').addEventListener('click', () => {
  if (page > 1) {
    page -= 1;
    loadDatasets();
  }
});

document.getElementById('nextBtn').addEventListener('click', () => {
  if (page < Math.max(1, pagination.total_pages || 1)) {
    page += 1;
    loadDatasets();
  }
});

loadDatasets();
