import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { uploadAPI } from '../api/client';
import './Upload.css';

// API URL - uses /api which is proxied by Nginx to the backend service
const API_URL = import.meta.env.VITE_API_URL || '/api';

function Upload() {
  const navigate = useNavigate();
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({});

  const handleFileSelect = (event) => {
    const files = Array.from(event.target.files);
    const newFiles = files.map((file) => ({
      file,
      id: Math.random().toString(36).substr(2, 9),
      status: 'pending',
      progress: 0,
    }));
    setSelectedFiles([...selectedFiles, ...newFiles]);
  };

  const handleUpload = async () => {
    setUploading(true);

    const pendingFiles = selectedFiles.filter((f) => f.status === 'pending');

    for (const fileItem of pendingFiles) {
      try {
        // Update status to uploading
        setSelectedFiles((prev) =>
          prev.map((f) => (f.id === fileItem.id ? { ...f, status: 'uploading' } : f))
        );

        // Upload file
        const uploadResponse = await uploadAPI.upload(fileItem.file, (progress) => {
          setUploadProgress((prev) => ({
            ...prev,
            [fileItem.id]: progress,
          }));
        });

        // Simple: Just save the IDs - file is now in storage
        setSelectedFiles((prev) =>
          prev.map((f) =>
            f.id === fileItem.id
              ? {
                  ...f,
                  status: 'success',
                  jobId: uploadResponse.job_id,        // ✅ Unique ID for document
                  blobName: uploadResponse.blob_name,  // ✅ File path in storage
                  filePath: uploadResponse.file_path,  // ✅ Full path reference
                }
              : f
          )
        );
      } catch (err) {
        // Update status to error
        setSelectedFiles((prev) =>
          prev.map((f) =>
            f.id === fileItem.id ? { ...f, status: 'error', error: err.message } : f
          )
        );
      }
    }

    setUploading(false);
  };

  const handleClearFiles = () => {
    setSelectedFiles([]);
    setUploadProgress({});
  };

  const handleRemoveFile = (fileId) => {
    setSelectedFiles((prev) => prev.filter((f) => f.id !== fileId));
  };

  const getDocumentTypeBadge = (type) => {
    switch (type) {
      case 'invoice':
        return { icon: '📄', label: 'Invoice', color: '#3498db' };
      case 'purchase-order':
        return { icon: '📋', label: 'Purchase Order', color: '#9b59b6' };
      case 'unknown':
        return { icon: '❓', label: 'Unknown', color: '#95a5a6' };
      default:
        return { icon: '📄', label: 'Document', color: '#7f8c8d' };
    }
  };

  const getConfidenceBadge = (confidence) => {
    if (!confidence) return null;
    const percentage = (confidence * 100).toFixed(0);
    const colorClass =
      confidence >= 0.8 ? 'confidence-high' : confidence >= 0.6 ? 'confidence-medium' : 'confidence-low';
    return { percentage, colorClass };
  };

  const successfulUploads = selectedFiles.filter((f) => f.status === 'success').length;
  const pendingUploads = selectedFiles.filter((f) => f.status === 'pending').length;

  return (
    <div className="upload-container">
      <div className="page-header">
        <h1>📤 Upload Documents</h1>
        <p className="page-description">
          Upload invoice, purchase order, or goods receipt documents (PDF or images).
          Files will be securely stored and you'll receive a unique ID for each document.
          Go to the Documents page to review document details and extracted fields.
        </p>
      </div>

      <div className="upload-status">
        <div className="status-card">
          <div className="status-icon">📄</div>
          <div className="status-info">
            <div className="status-value">{selectedFiles.length}</div>
            <div className="status-label">Selected Files</div>
          </div>
        </div>

        <div className="status-card">
          <div className="status-icon">⏳</div>
          <div className="status-info">
            <div className="status-value">{pendingUploads}</div>
            <div className="status-label">Pending Upload</div>
          </div>
        </div>

        <div className="status-card success">
          <div className="status-icon">✅</div>
          <div className="status-info">
            <div className="status-value">{successfulUploads}</div>
            <div className="status-label">Uploaded</div>
          </div>
        </div>
      </div>

      <section className="upload-section">
        <div className="upload-area">
          <input
            type="file"
            id="file-input"
            multiple
            accept=".pdf,.png,.jpg,.jpeg,.tiff"
            onChange={handleFileSelect}
            style={{ display: 'none' }}
          />
          <label htmlFor="file-input" className="upload-button">
            📁 Select Document Files
          </label>

          {selectedFiles.length > 0 && (
            <div className="upload-actions">
              <button
                onClick={handleUpload}
                disabled={uploading || pendingUploads === 0}
                className="btn-upload"
              >
                {uploading ? '⏳ Uploading...' : `⬆️ Upload ${pendingUploads} File${pendingUploads !== 1 ? 's' : ''}`}
              </button>
              <button onClick={handleClearFiles} className="btn-clear" disabled={uploading}>
                🗑️ Clear All
              </button>
            </div>
          )}
        </div>

        {selectedFiles.length > 0 && (
          <div className="file-list">
            <h3>Files ({selectedFiles.length})</h3>
            {selectedFiles.map((fileItem) => (
              <div key={fileItem.id} className={`file-item ${fileItem.status}`}>
                <div className="file-info">
                  <span className="file-name">{fileItem.file.name}</span>
                  <div className="file-actions">
                    <span className="file-status">
                      {fileItem.status === 'pending' && '⏳ Pending'}
                      {fileItem.status === 'uploading' && `⬆️ ${uploadProgress[fileItem.id] || 0}%`}
                      {fileItem.status === 'success' && (
                        <span className="classification-result">
                          ✅ Uploaded to storage
                          {fileItem.blobName && (
                            <button
                              onClick={() => navigate(`/documents/${encodeURIComponent(fileItem.blobName)}`)}
                              className="btn-view-document"
                              title="Categorize and validate this document"
                            >
                              Categorize →
                            </button>
                          )}
                        </span>
                      )}
                      {fileItem.status === 'error' && `❌ Failed: ${fileItem.error}`}
                    </span>
                    {fileItem.status === 'pending' && (
                      <button
                        onClick={() => handleRemoveFile(fileItem.id)}
                        className="btn-remove"
                        title="Remove file"
                      >
                        ✕
                      </button>
                    )}
                  </div>
                </div>
                {fileItem.status === 'uploading' && (
                  <div className="progress-bar">
                    <div
                      className="progress-fill"
                      style={{ width: `${uploadProgress[fileItem.id] || 0}%` }}
                    ></div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        {successfulUploads > 0 && (
          <div className="info-message">
            <strong>ℹ️ Next Steps:</strong> Your documents have been uploaded successfully!
            <br />
            Go to the <a href="/documents" style={{ color: '#3498db', textDecoration: 'underline' }}>Documents page</a> to:
            <ul style={{ marginTop: '0.5rem', marginBottom: '0', paddingLeft: '1.5rem' }}>
              <li>✅ Verify document type (Invoice/PO/GRN)</li>
              <li>✅ Review extracted fields</li>
              <li>✅ Open document details for validation</li>
            </ul>
          </div>
        )}
      </section>
    </div>
  );
}

export default Upload;
