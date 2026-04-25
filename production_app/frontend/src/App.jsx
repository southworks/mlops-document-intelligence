import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import DocumentList from './pages/DocumentList';
import DocumentDetail from './pages/DocumentDetail';
import Upload from './pages/Upload';
import './App.css'

const basename = '/';

function App() {
  return (
    <Router basename={basename}>
      <div className="app">
        <nav className="navbar">
          <div className="nav-container">
            <Link to="/" className="nav-brand">
              📄 Document Processing Platform
            </Link>
            <div className="nav-links">
              <Link to="/" className="nav-link">
                Uploads
              </Link>
              <Link to="/documents" className="nav-link">
                Documents
              </Link>
            </div>
          </div>
        </nav>

        <main className="main-content">
          <Routes>
            <Route path="/" element={<Upload />} />
            <Route path="/documents" element={<DocumentList />} />
            <Route path="/documents/:blobName" element={<DocumentDetail />} />
            <Route path="/upload" element={<Upload />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App
