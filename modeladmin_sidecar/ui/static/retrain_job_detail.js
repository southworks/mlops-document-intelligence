const segments = window.location.pathname.split('/').filter(Boolean);
const jobId = segments[segments.length - 1];

const errorBox = document.getElementById('errorBox');
const successBox = document.getElementById('successBox');

let currentJob = null;

function setError(message) {
  if (!message) {
    errorBox.classList.add('hidden');
    errorBox.textContent = '';
    return;
  }
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
}

function setSuccess(message) {
  if (!message) {
    successBox.classList.add('hidden');
    successBox.textContent = '';
    return;
  }
  successBox.textContent = message;
  successBox.classList.remove('hidden');
}

function setText(id, value) {
  document.getElementById(id).textContent = value ?? '-';
}

function formatDate(value) {
  if (!value) return '-';
  return new Date(value).toLocaleString();
}

function renderJob(job) {
  currentJob = job;
  document.getElementById('jobTitle').textContent = `Training Job ${job.id}`;
  setText('jobStatus', job.status);
  setText('jobId', job.id);
  setText('adiModelId', job.adi_model_id);
  setText('adiOperationId', job.adi_operation_id);
  setText('errorMessage', job.error_message);
  setText('submittedAt', formatDate(job.submitted_at));
  setText('updatedAt', formatDate(job.updated_at));

  const datasetLink = document.getElementById('datasetLink');
  datasetLink.textContent = job.training_dataset_id || '-';
  datasetLink.href = `/modeladmin/ui/datasets/${job.training_dataset_id}`;
}

function renderActiveModel(activeModel) {
  setText('activeModelId', activeModel?.active_model_id);
  setText('activeSourceJobId', activeModel?.source_retrain_job_id);
  setText('activatedAt', formatDate(activeModel?.activated_at));
}

async function loadRetrainJob() {
  const response = await fetch(`/modeladmin/retrain-jobs/${jobId}`);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'Failed to load retrain job');
  }
  const data = await response.json();
  renderJob(data);
}

async function loadActiveModel() {
  const response = await fetch('/modeladmin/models/active');
  if (response.status === 404) {
    renderActiveModel(null);
    return;
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || 'Failed to load active model');
  }
  const data = await response.json();
  renderActiveModel(data.item || null);
}

async function loadPage() {
  setError('');
  setSuccess('');
  try {
    await loadRetrainJob();
    await loadActiveModel();
  } catch (error) {
    setError(error.message || 'Failed to load retrain job detail');
  }
}

loadPage();
