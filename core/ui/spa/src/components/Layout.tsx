import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import './Layout.css';

const navGroups = [
  {
    heading: 'Configure',
    links: [
      { to: '/targets', label: 'Targets', icon: '◎' },
      { to: '/protocol-studio', label: 'Protocol Studio', icon: '✎' },
      { to: '/plugin-debug', label: 'Plugin Debugger', icon: '⚙' },
    ],
  },
  {
    heading: 'Test',
    links: [
      { to: '/one-off', label: 'One-Off Test', icon: '▹' },
      { to: '/packet-parser', label: 'Packet Parser', icon: '⟐' },
      { to: '/mutation-workbench', label: 'Mutation Workbench', icon: '⟳' },
    ],
  },
  {
    heading: 'Analyze',
    links: [
      { to: '/correlation', label: 'Correlation', icon: '⊞' },
      { to: '/state-walker', label: 'State Walker', icon: '⇢' },
      { to: '/state-graph', label: 'State Graph', icon: '◈' },
      { to: '/system-logs', label: 'System Logs', icon: '⎙' },
    ],
  },
];

function Layout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);

  return (
    <>
      <a href="#main-content" className="skip-link">Skip to content</a>
      <div className="app-shell">
        {/* Top bar */}
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="hamburger"
              onClick={() => setSidebarOpen(!sidebarOpen)}
              aria-expanded={sidebarOpen}
              aria-controls="sidebar-nav"
              aria-label="Toggle navigation"
            >
              <span className="hamburger-line" />
              <span className="hamburger-line" />
              <span className="hamburger-line" />
            </button>
            <NavLink to="/" end className="topbar-brand">
              <span className="brand-icon">⬡</span>
              <span className="brand-text">Protocol Fuzzer</span>
            </NavLink>
          </div>
          <nav className="topbar-links">
            <NavLink to="/guides" className="topbar-link">Docs</NavLink>
          </nav>
        </header>

        <div className="shell-grid">
          {/* Sidebar */}
          <aside
            className={`sidebar ${sidebarOpen ? 'sidebar--open' : ''}`}
            id="sidebar-nav"
          >
            <nav aria-label="Primary navigation">
              <NavLink
                to="/"
                end
                className={({ isActive }) => `nav-link nav-link--home ${isActive ? 'active' : ''}`}
                onClick={() => setSidebarOpen(false)}
              >
                <span className="nav-icon">⌂</span>
                <span className="nav-label">Dashboard</span>
              </NavLink>

              {navGroups.map((group) => (
                <div key={group.heading} className="nav-group">
                  <span className="nav-group-heading">{group.heading}</span>
                  {group.links.map((link) => (
                    <NavLink
                      key={link.to}
                      to={link.to}
                      className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                      onClick={() => setSidebarOpen(false)}
                    >
                      <span className="nav-icon">{link.icon}</span>
                      <span className="nav-label">{link.label}</span>
                    </NavLink>
                  ))}
                </div>
              ))}

              <div className="nav-group">
                <span className="nav-group-heading">Learn</span>
                <NavLink
                  to="/guides"
                  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                  onClick={() => setSidebarOpen(false)}
                >
                  <span className="nav-icon">📖</span>
                  <span className="nav-label">Documentation</span>
                </NavLink>
              </div>
            </nav>
          </aside>

          {/* Overlay for mobile sidebar */}
          {sidebarOpen && (
            <div
              className="sidebar-overlay"
              onClick={() => setSidebarOpen(false)}
              aria-hidden="true"
            />
          )}

          {/* Main content */}
          <main id="main-content" className="content-region">
            <Outlet />
          </main>
        </div>
      </div>
    </>
  );
}

export default Layout;
