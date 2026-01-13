import { Link, NavLink, Outlet } from 'react-router-dom';
import './Layout.css';

const links = [
  { to: '/', label: 'Dashboard', description: 'Sessions & orchestration' },
  { to: '/plugin-debug', label: 'Plugin Debugger', description: 'Inspect blocks & states' },
  { to: '/packet-parser', label: 'Packet Parser', description: 'Decode binary packets' },
  { to: '/mutation-workbench', label: 'Mutation Workbench', description: 'Craft & mutate packets' },
  { to: '/state-walker', label: 'State Walker', description: 'Validate state machines' },
  { to: '/protocol-studio', label: 'Protocol Studio', description: 'Build & validate plugins' },
  { to: '/one-off', label: 'One-Off Test', description: 'Fire single payloads' },
  { to: '/correlation', label: 'Correlation', description: 'Execution digests' },
];

function Layout() {
  return (
    <div className="app-shell">
      <div className="shell-grid">
        <aside className="sidebar">
          <div className="sidebar-toggle-row">
            <span className="sidebar-title">Navigate</span>
          </div>
          <nav className="sidebar-nav" aria-label="Primary">
            {links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.to === '/'}
                className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
              >
                <span className="label">{link.label}</span>
                <span className="description">{link.description}</span>
              </NavLink>
            ))}
          </nav>
        </aside>
        <div className="content-region">
          <header className="masthead">
            <div className="masthead-copy">
              <p className="eyebrow">Structure-aware fuzzing stack</p>
              <div className="masthead-title-row">
                <h1>Protocol Fuzzer Console</h1>
                <Link className="docs-link" to="/guides">
                  Documentation Hub ↗
                </Link>
              </div>
              <p className="subtitle">
                Launch campaigns, inspect protocol grammar, and replay interesting executions from a single workspace.
              </p>
            </div>
            <div className="masthead-meta">
              <div>
                <span>Targets</span>
                <strong>Simple TCP · Feature Showcase</strong>
              </div>
            </div>
          </header>
          <main className="app-content">
            <Outlet />
          </main>
        </div>
      </div>
    </div>
  );
}

export default Layout;
