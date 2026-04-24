import { useState } from 'react';
import { Document, Page, pdfjs } from 'react-pdf';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';
import '../styles/PDFViewer.css';

// Configure PDF.js worker - use unpkg CDN which works better with Vite
pdfjs.GlobalWorkerOptions.workerSrc = `https://unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

function PDFViewer({ pdfUrl, filename, onClose }) {
  const [numPages, setNumPages] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  function onDocumentLoadSuccess({ numPages }) {
    setNumPages(numPages);
    setLoading(false);
  }

  function onDocumentLoadError(error) {
    console.error('Error loading PDF:', error);
    setError('Failed to load PDF. Please try again.');
    setLoading(false);
  }

  function changePage(offset) {
    setPageNumber(prevPageNumber => prevPageNumber + offset);
  }

  function previousPage() {
    changePage(-1);
  }

  function nextPage() {
    changePage(1);
  }

  return (
    <div className="pdf-modal-overlay" onClick={onClose}>
      <div className="pdf-modal-content" onClick={e => e.stopPropagation()}>
        <div className="pdf-modal-header">
          <h3>{filename || 'Document Preview'}</h3>
          <button className="close-btn" onClick={onClose} title="Close">
            ✕
          </button>
        </div>

        <div className="pdf-viewer-container">
          {loading && (
            <div className="pdf-loading">
              <div className="spinner"></div>
              <p>Loading PDF...</p>
            </div>
          )}

          {error && (
            <div className="pdf-error">
              <p>{error}</p>
              <button onClick={onClose} className="btn-secondary">Close</button>
            </div>
          )}

          {!error && (
            <Document
              file={pdfUrl}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
              loading=""
            >
              <Page
                pageNumber={pageNumber}
                width={Math.min(window.innerWidth * 0.7, 800)}
                renderTextLayer={true}
                renderAnnotationLayer={true}
              />
            </Document>
          )}
        </div>

        {numPages && !error && (
          <div className="pdf-controls">
            <button
              onClick={previousPage}
              disabled={pageNumber <= 1}
              className="btn-nav"
            >
              ← Previous
            </button>
            <span className="page-info">
              Page {pageNumber} of {numPages}
            </span>
            <button
              onClick={nextPage}
              disabled={pageNumber >= numPages}
              className="btn-nav"
            >
              Next →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default PDFViewer;
