import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import './DocumentDetail.css';
import { API_BASE_URL } from '../api/client';

function DocumentDetail() {
  const { blobName } = useParams();
  const navigate = useNavigate();
  const [document, setDocument] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    loadDocument();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blobName]);

  const loadDocument = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/documents/${encodeURIComponent(decodeURIComponent(blobName))}`);
      if (!response.ok) throw new Error('Failed to fetch document');
      const data = await response.json();
      setDocument(data);
      setError(null);
    } catch (err) {
      setError('Failed to load document: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const flattenFields = (value, prefix = '') => {
    if (value === null || value === undefined) return [];

    if (Array.isArray(value)) {
      return value.flatMap((entry, index) => flattenFields(entry, `${prefix}[${index}]`));
    }

    if (typeof value === 'object') {
      if (Object.prototype.hasOwnProperty.call(value, 'value')) {
        return [
          {
            field: prefix,
            value: value.value,
            confidence: value.confidence,
            hasLowConfidence: Boolean(value.has_low_confidence),
          },
        ];
      }

      return Object.entries(value).flatMap(([key, nestedValue]) => {
        const nestedPrefix = prefix ? `${prefix}.${key}` : key;
        return flattenFields(nestedValue, nestedPrefix);
      });
    }

    return [
      {
        field: prefix,
        value,
        confidence: null,
        hasLowConfidence: false,
      },
    ];
  };

  const formatDisplayValue = (value) => {
    if (value === null || value === undefined || value === '') {
      return 'N/A';
    }
    if (typeof value === 'object') {
      return JSON.stringify(value);
    }
    return String(value);
  };

  const formatDocType = (docType) => {
    if (!docType) return 'Document';
    return docType
      .replace(/-/g, ' ')
      .replace(/\b\w/g, (char) => char.toUpperCase());
  };

  if (loading) {
    return (
      <div className="loading-container">
        <div className="spinner"></div>
        <p>Loading document...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="error-container">
        <p className="error-message">{error}</p>
        <button onClick={() => navigate('/')} className="btn-back">
          ← Back to List
        </button>
      </div>
    );
  }

  if (!document) {
    return null;
  }

  const rows = flattenFields(document.fields || {});

  return (
    <div className="document-detail-container">
      <div className="detail-header">
        <button onClick={() => navigate('/')} className="btn-back">
          ← Back
        </button>
        <h1>📄 {formatDocType(document.document_type)} Details</h1>
        {document.classification_confidence > 0 && (
          <div className="classification-badge">
            Classified as {formatDocType(document.document_type)} ({Math.round(document.classification_confidence)}% confidence)
          </div>
        )}
      </div>

      {document.has_low_confidence && (
        <div className="alert-warning">
          ⚠️ This document has fields flagged for review. Please review carefully.
        </div>
      )}

      <div className="detail-sections">
        <section className="detail-section">
          <h2>📋 Extracted Fields</h2>
          <div className="line-items-table">
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Confidence</th>
                  <th>Review</th>
                </tr>
              </thead>
              <tbody>
                {rows.length > 0 ? (
                  rows.map((row, idx) => (
                    <tr key={`${row.field}-${idx}`}>
                      <td>{row.field}</td>
                      <td>{formatDisplayValue(row.value)}</td>
                      <td>{row.confidence !== null && row.confidence !== undefined ? `${Math.round(row.confidence)}%` : 'N/A'}</td>
                      <td>{row.hasLowConfidence ? 'Review Needed' : 'OK'}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={4}>No fields extracted.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="detail-footer">
        <p className="blob-info">
          <strong>Blob Name:</strong> {document.blob_name}
        </p>
        {document.job_id && (
          <p className="blob-info">
            <strong>Job ID:</strong> {document.job_id}
          </p>
        )}
      </div>
    </div>
  );
}

export default DocumentDetail;
