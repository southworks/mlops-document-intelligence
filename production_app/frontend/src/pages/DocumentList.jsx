import { Fragment, useState, useEffect } from 'react';
import './DocumentList.css';
import { API_BASE_URL } from '../api/client';

function DocumentList() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [expandedRows, setExpandedRows] = useState(new Set());
  const [rowDetailStates, setRowDetailStates] = useState({});

  useEffect(() => {
    loadDocuments();
    loadStats();
    return () => {
      Object.values(rowDetailStates).forEach((state) => {
        if (state.abortController) state.abortController.abort();
      });
    };
  }, []);

  const loadDocuments = async () => {
    try {
      setLoading(true);
      const response = await fetch(`${API_BASE_URL}/documents?type=all&page=1&limit=100`);
      if (!response.ok) throw new Error('Failed to fetch documents');
      const data = await response.json();
      setDocuments(data);
      setError(null);
    } catch (err) {
      setError('Failed to load documents: ' + err.message);
    } finally {
      setLoading(false);
    }
  };

  const loadStats = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/documents/stats`);
      if (!response.ok) throw new Error('Failed to fetch stats');
      const data = await response.json();
      setStats(data);
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  };

  const asPercent = (value) => {
    if (value === null || value === undefined) return 0;
    const num = Number(value);
    if (Number.isNaN(num)) return 0;
    return num <= 1 ? Math.round(num * 100) : Math.round(num);
  };

  const getDocumentTypeLabel = (docType) => {
    if (docType === 'invoice') return 'Invoice';
    if (docType === 'purchase-order') return 'Purchase Order';
    if (docType === 'goods-receipt-note') return 'Goods Receipt Note';
    return 'Unknown';
  };

  const getProcessingState = (doc) => {
    if (doc.processing_state) return doc.processing_state;
    const status = (doc.status || '').toLowerCase();

    if (status === 'uploading') return 'Uploading';
    if (status === 'uploaded' || status === 'queued' || status === 'pending') return 'Uploaded/Queued';
    if (status === 'processing') return 'Processing';
    if (status === 'failed') return 'Failed';

    if (doc.pending_processing) return 'Pending Processing';
    if (doc.document_type === 'unknown') return 'Unknown (Final)';
    return 'Processed';
  };

  const getStateClass = (state) => {
    if (state === 'Pending Processing') return 'pending';
    if (state === 'Unknown (Final)') return 'unknown-final';
    if (state === 'Processing') return 'processing';
    if (state === 'Failed') return 'failed';
    if (state === 'Uploading' || state === 'Uploaded/Queued') return 'queued';
    return 'processed';
  };

  const getDocumentKey = (doc) => doc.blob_name || doc.raw_data?.blob_path || doc.job_id || JSON.stringify(doc);

  const toggleExpanded = (docKey) => {
    const isCurrentlyExpanded = expandedRows.has(docKey);

    if (isCurrentlyExpanded) {
      onRowCollapse(docKey);
    } else {
      onRowExpand(docKey);
    }

    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(docKey)) next.delete(docKey);
      else next.add(docKey);
      return next;
    });
  };

  const onRowExpand = async (blobName) => {
    const detailState = rowDetailStates[blobName];

    if (detailState?.state === 'loaded') return;
    if (detailState?.state === 'loading') return;

    const controller = new AbortController();
    setRowDetailStates((prev) => ({
      ...prev,
      [blobName]: { state: 'loading', data: null, error: null, abortController: controller, timestamp: Date.now() },
    }));

    try {
      const response = await fetch(`${API_BASE_URL}/documents/${encodeURIComponent(blobName)}`, {
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`Failed to load document detail: ${response.status}`);
      }

      const data = await response.json();

      setRowDetailStates((prev) => ({
        ...prev,
        [blobName]: { state: 'loaded', data, error: null, timestamp: Date.now() },
      }));
    } catch (err) {
      if (err.name !== 'AbortError') {
        setRowDetailStates((prev) => ({
          ...prev,
          [blobName]: { state: 'error', data: null, error: err.message, timestamp: Date.now() },
        }));
      }
    }
  };

  const onRowCollapse = (blobName) => {
    const detailState = rowDetailStates[blobName];
    if (detailState?.abortController?.signal?.pending) {
      detailState.abortController.abort();
    }
  };

  const formatDetailValue = (value) => {
    if (value === null || value === undefined || value === '') return 'N/A';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };

  const collectFieldRows = (docOrDetail, prefix = '') => {
    const fields = docOrDetail?.fields || {};

    function walk(value, currentPrefix = '') {
      if (value === null || value === undefined) return [];
      if (Array.isArray(value)) {
        return value.flatMap((entry, index) => walk(entry, `${currentPrefix}[${index}]`));
      }
      if (typeof value === 'object') {
        if (Object.prototype.hasOwnProperty.call(value, 'value')) {
          return [
            {
              field: currentPrefix,
              value: formatDetailValue(value.value),
              confidence: value.confidence !== undefined ? asPercent(value.confidence) : null,
              has_low_confidence: Boolean(value.has_low_confidence),
            },
          ];
        }
        return Object.entries(value).flatMap(([key, nestedValue]) => {
          const nestedPrefix = currentPrefix ? `${currentPrefix}.${key}` : key;
          return walk(nestedValue, nestedPrefix);
        });
      }

      return [
        {
          field: currentPrefix,
          value: formatDetailValue(value),
          confidence: null,
          has_low_confidence: false,
        },
      ];
    }

    return walk(fields, prefix);
  };

  return (
    <div className="document-list-container">
      <div className="document-header">
        <h1>Documents</h1>

        {stats && (
          <div className="stats-summary">
            <div className="stat-card">
              <div className="stat-value">{stats.by_type?.invoice?.total || 0}</div>
              <div className="stat-label">Invoices</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.by_type?.['purchase-order']?.total || 0}</div>
              <div className="stat-label">Purchase Orders</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.by_type?.['goods-receipt-note']?.total || 0}</div>
              <div className="stat-label">GRNs</div>
            </div>
            <div className="stat-card">
              <div className="stat-value">{stats.by_type?.unknown?.total || 0}</div>
              <div className="stat-label">Unknown</div>
            </div>
          </div>
        )}
      </div>

      {loading && <div className="loading">Loading documents...</div>}

      {error && <div className="error-message">{error}</div>}

      {!loading && !error && documents.length === 0 && (
        <div className="empty-state">
          <p>No documents found.</p>
        </div>
      )}

      {!loading && !error && documents.length > 0 && (
        <div className="documents-table-wrapper">
          <table className="documents-table">
            <thead>
              <tr>
                <th></th>
                <th>State</th>
                <th>Type</th>
                <th>Blob</th>
                <th>Classification Confidence</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {documents.map((doc) => {
                const docKey = getDocumentKey(doc);
                const isExpanded = expandedRows.has(docKey);
                const state = getProcessingState(doc);
                const confidence = asPercent(doc.classification_confidence);

                return (
                  <Fragment key={docKey}>
                    <tr key={docKey} className="master-row">
                      <td>
                        <button
                          type="button"
                          className="expand-btn"
                          onClick={() => toggleExpanded(docKey)}
                          aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
                        >
                          {isExpanded ? '−' : '+'}
                        </button>
                      </td>
                      <td>
                        <span className={`state-badge ${getStateClass(state)}`}>{state}</span>
                      </td>
                      <td>{getDocumentTypeLabel(doc.document_type)}</td>
                      <td className="strong-cell">{doc.blob_name || 'N/A'}</td>
                      <td>{confidence > 0 ? `${confidence}%` : 'N/A'}</td>
                      <td>
                        {doc.has_low_confidence ? (
                          <span className="review-badge">Review Needed</span>
                        ) : (
                          <span className="review-ok">No</span>
                        )}
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="detail-row-container">
                        <td colSpan={6}>
                          <div className="detail-grid-wrap">
                            {(() => {
                              const detailState = rowDetailStates[docKey];

                              if (detailState?.state === 'loading') {
                                return (
                                  <div className="detail-loading">
                                    <p>Loading details...</p>
                                  </div>
                                );
                              }

                              if (detailState?.state === 'error') {
                                return (
                                  <div className="detail-error">
                                    <p>Error loading details: {detailState.error}</p>
                                    <button type="button" className="retry-btn" onClick={() => onRowExpand(docKey)}>
                                      Retry
                                    </button>
                                  </div>
                                );
                              }

                              const detailData = detailState?.state === 'loaded' ? detailState.data : doc;
                              const details = collectFieldRows(detailData);

                              return (
                                <table className="detail-grid">
                                  <thead>
                                    <tr>
                                      <th>Field</th>
                                      <th>Value</th>
                                      <th>Confidence</th>
                                      <th>Review</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {details.map((detail, index) => (
                                      <tr key={`${docKey}-field-${index}`}>
                                        <td className="field-name">{detail.field}</td>
                                        <td>{detail.value}</td>
                                        <td>{detail.confidence !== null ? `${detail.confidence}%` : 'N/A'}</td>
                                        <td>{detail.has_low_confidence ? 'Review Needed' : 'OK'}</td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              );
                            })()}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default DocumentList;
