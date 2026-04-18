import { useState } from 'react';
import StateWalkerPage from './StateWalkerPage';
import StateGraphPage from './StateGraphPage';
import './StateExplorerPage.css';

type ExplorerTab = 'graph' | 'walker';

export default function StateExplorerPage() {
  const [tab, setTab] = useState<ExplorerTab>('graph');

  return (
    <div className="state-explorer-page">
      <div className="explorer-header">
        <h1>State Explorer</h1>
        <p className="explorer-subtitle">
          Visualize protocol state coverage and manually walk state transitions.
        </p>
      </div>

      <div className="explorer-tabs">
        <button
          className={`explorer-tab ${tab === 'graph' ? 'active' : ''}`}
          onClick={() => setTab('graph')}
        >
          <span className="tab-icon">◈</span>
          <span className="tab-text">
            <span className="tab-label">Coverage Graph</span>
            <span className="tab-desc">Live state coverage from a running session</span>
          </span>
        </button>
        <button
          className={`explorer-tab ${tab === 'walker' ? 'active' : ''}`}
          onClick={() => setTab('walker')}
        >
          <span className="tab-icon">⇢</span>
          <span className="tab-text">
            <span className="tab-label">State Walker</span>
            <span className="tab-desc">Manually execute transitions against a target</span>
          </span>
        </button>
      </div>

      <div className="explorer-content">
        {tab === 'graph' && <StateGraphPage />}
        {tab === 'walker' && <StateWalkerPage />}
      </div>
    </div>
  );
}
