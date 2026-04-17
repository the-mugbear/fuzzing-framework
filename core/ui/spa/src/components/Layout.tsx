import { Link, NavLink, Outlet } from 'react-router-dom';
import './Layout.css';

const navGroups = [
  {
    heading: 'Run',
    links: [
      { to: '/', label: 'Dashboard', description: 'Sessions & orchestration' },
      { to: '/targets', label: 'Targets', description: 'Start & stop test servers' },
      { to: '/one-off', label: 'One-Off Test', description: 'Fire single payloads' },
    ],
  },
  {
    heading: 'Build',
    links: [
      { to: '/protocol-studio', label: 'Protocol Studio', description: 'Build & validate plugins' },
      { to: '/plugin-debug', label: 'Plugin Debugger', description: 'Inspect blocks & states' },
      { to: '/packet-parser', label: 'Packet Parser', description: 'Decode binary packets' },
    ],
  },
  {
    heading: 'Analyze',
    links: [
      { to: '/mutation-workbench', label: 'Mutation Workbench', description: 'Craft & mutate packets' },
      { to: '/state-walker', label: 'State Walker', description: 'Validate state machines' },
      { to: '/correlation', label: 'Correlation', description: 'Execution digests' },
    ],
  },
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
            {navGroups.map((group) => (
              <div key={group.heading} className="nav-group">
                <span className="nav-group-heading">{group.heading}</span>
                {group.links.map((link) => (
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
              </div>
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
                  Documentation Hub
                </Link>
              </div>
              <p className="subtitle">
                Find protocol bugs faster. Define your protocol, launch a campaign, and investigate crashes — all from one workspace.
              </p>
            </div>
            <div className="masthead-meta">
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
