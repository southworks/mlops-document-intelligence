import axios from 'axios';

const normalizeApiBaseUrl = (value) => {
  const rawValue = typeof value === 'string' ? value.trim() : '';
  if (!rawValue) {
    return '/api';
  }

  const withoutTrailingSlash = rawValue.replace(/\/+$/, '');

  if (withoutTrailingSlash.startsWith('/')) {
    return withoutTrailingSlash;
  }

  try {
    const parsed = new URL(withoutTrailingSlash);
    const sameOrigin = typeof window !== 'undefined' && parsed.origin === window.location.origin;
    const hasNoPath = !parsed.pathname || parsed.pathname === '/';

    if (sameOrigin && hasNoPath) {
      return '/api';
    }

    return withoutTrailingSlash;
  } catch {
    return '/api';
  }
};

export const API_BASE_URL = normalizeApiBaseUrl(import.meta.env.VITE_API_URL);

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Upload endpoint
export const uploadAPI = {
  // Upload invoice file
  upload: async (file, onProgress) => {
    const formData = new FormData();
    formData.append('file', file);

    const response = await apiClient.post('/upload/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      onUploadProgress: (progressEvent) => {
        if (onProgress && progressEvent.total) {
          const percentCompleted = Math.round((progressEvent.loaded * 100) / progressEvent.total);
          onProgress(percentCompleted);
        }
      },
    });
    return response.data;  // Return data directly
  },
};

// Document endpoints
export const documentsAPI = {
  // List documents by type
  list: (type) => apiClient.get('/documents', { params: { type } }),

  // Get document details
  get: (blobName) => apiClient.get(`/documents/${blobName}`),

  // Generate SAS URL for document
  generateSasUrl: (blobName) => apiClient.post('/documents/generate-sas-url', { blob_names: [blobName] }),

  // Process new uploads
  processNew: () => apiClient.post('/documents/process-new'),
};

export default apiClient;


