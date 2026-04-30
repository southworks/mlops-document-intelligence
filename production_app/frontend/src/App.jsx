import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
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
            </div>
          </div>
        </nav>

        <main className="main-content">
          <Routes>
            <Route path="/" element={<Upload />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App
