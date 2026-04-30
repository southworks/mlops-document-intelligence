import { useState } from 'react';
import { uploadAPI } from '../api/client';
import DocumentList from './DocumentList';
import './Upload.css';

function Upload() {
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({});
  const [refreshSignal, setRefreshSignal] = useState(0);

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
    setRefreshSignal((n) => n + 1);
  };

  const handleClearFiles = () => {
    setSelectedFiles([]);
    setUploadProgress({});
  };

  const handleRemoveFile = (fileId) => {
    setSelectedFiles((prev) => prev.filter((f) => f.id !== fileId));
  };

  const pendingUploads = selectedFiles.filter((f) => f.status === 'pending').length;

  return (
    <div className="upload-container">
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
                          ✅ Uploaded
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

        </section>

      <DocumentList refreshSignal={refreshSignal} />
    </div>
  );
}

export default Upload;
