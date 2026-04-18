import { useState } from 'react';
import PacketParserPage from './PacketParserPage';
import OneOffTestPage from './OneOffTestPage';
import MutationWorkbenchPage from './MutationWorkbenchPage';
import './PacketWorkshopPage.css';

type WorkshopTab = 'parse' | 'build' | 'mutate';

export default function PacketWorkshopPage() {
  const [tab, setTab] = useState<WorkshopTab>('parse');

  return (
    <div className="packet-workshop-page">
      <div className="workshop-header">
        <h1>Packet Workshop</h1>
        <p className="workshop-subtitle">
          Parse, build, mutate, and send protocol packets interactively.
        </p>
      </div>

      <div className="workshop-tabs">
        <button
          className={`workshop-tab ${tab === 'parse' ? 'active' : ''}`}
          onClick={() => setTab('parse')}
        >
          <span className="tab-icon">⟐</span>
          <span className="tab-label">Parse</span>
          <span className="tab-desc">Decode hex into fields</span>
        </button>
        <button
          className={`workshop-tab ${tab === 'build' ? 'active' : ''}`}
          onClick={() => setTab('build')}
        >
          <span className="tab-icon">▹</span>
          <span className="tab-label">Build & Send</span>
          <span className="tab-desc">Craft and send a packet</span>
        </button>
        <button
          className={`workshop-tab ${tab === 'mutate' ? 'active' : ''}`}
          onClick={() => setTab('mutate')}
        >
          <span className="tab-icon">⟳</span>
          <span className="tab-label">Mutate</span>
          <span className="tab-desc">Apply mutations with diff view</span>
        </button>
      </div>

      <div className="workshop-content">
        {tab === 'parse' && <PacketParserPage />}
        {tab === 'build' && <OneOffTestPage />}
        {tab === 'mutate' && <MutationWorkbenchPage />}
      </div>
    </div>
  );
}
