import { useEffect, useState } from 'react';
import { api } from '../services/api';
import Tooltip from './Tooltip';
import './SessionDetailPanel.css';

interface SessionDetailPanelProps {
  sessionId: string;
  onClose: () => void;
}

interface ContextSnapshot {
  session_id: string;
  values: Record<string, unknown>;
  bootstrap_complete: boolean;
  key_count: number;
}

interface StageInfo {
  name: string;
  role: string;
  status: string;
  attempts: number;
  last_error: string | null;
}

interface StageList {
  session_id: string;
  stages: StageInfo[];
  bootstrap_complete: boolean;
}

interface ConnectionInfo {
  connection_id: string;
  connected: boolean;
  healthy: boolean;
  bytes_sent: number;
  bytes_received: number;
  send_count: number;
  recv_count: number;
  reconnect_count: number;
  created_at: string | null;
  last_send: string | null;
  last_recv: string | null;
}

interface ConnectionStatus {
  session_id: string;
  connection_mode: string;
  active_connections: ConnectionInfo[];
}

interface HeartbeatStatus {
  session_id: string;
  enabled: boolean;
  status: string | null;
  interval_ms: number | null;
  total_sent: number;
  failures: number;
  last_sent: string | null;
  last_ack: string | null;
}

interface ReplayResult {
  original_sequence: number;
  status: string;
  response_preview: string | null;
  error: string | null;
  duration_ms: number;
  matched_original: boolean;
}

interface ReplayResponse {
  session_id: string;
  replayed_count: number;
  skipped_count: number;
  results: ReplayResult[];
  context_after: Record<string, unknown>;
  warnings: string[];
  duration_ms: number;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTime(isoString: string | null): string {
  if (!isoString) return '-';
  try {
    return new Date(isoString).toLocaleTimeString();
  } catch {
    return isoString;
  }
}

function SessionDetailPanel({ sessionId, onClose }: SessionDetailPanelProps) {
  const [activeTab, setActiveTab] = useState<'context' | 'stages' | 'connection' | 'heartbeat' | 'replay'>('context');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Data states
  const [context, setContext] = useState<ContextSnapshot | null>(null);
  const [stages, setStages] = useState<StageList | null>(null);
  const [connection, setConnection] = useState<ConnectionStatus | null>(null);
  const [heartbeat, setHeartbeat] = useState<HeartbeatStatus | null>(null);

  // Context value visibility (masked by default)
  const [revealedKeys, setRevealedKeys] = useState<Set<string>>(new Set());

  // Replay form state
  const [replayMode, setReplayMode] = useState<'fresh' | 'stored' | 'skip'>('stored');
  const [replaySequence, setReplaySequence] = useState<number>(10);
  const [replayDelay, setReplayDelay] = useState<number>(0);
  const [replayResult, setReplayResult] = useState<ReplayResponse | null>(null);
  const [replaying, setReplaying] = useState(false);

  // New context value form
  const [newContextKey, setNewContextKey] = useState('');
  const [newContextValue, setNewContextValue] = useState('');

  const loadTabData = async (tab: typeof activeTab) => {
    setLoading(true);
    setError(null);
    try {
      switch (tab) {
        case 'context':
          const ctxData = await api<ContextSnapshot>(`/api/sessions/${sessionId}/context`);
          setContext(ctxData);
          break;
        case 'stages':
          const stgData = await api<StageList>(`/api/sessions/${sessionId}/stages`);
          setStages(stgData);
          break;
        case 'connection':
          const connData = await api<ConnectionStatus>(`/api/sessions/${sessionId}/connection`);
          setConnection(connData);
          break;
        case 'heartbeat':
          const hbData = await api<HeartbeatStatus>(`/api/sessions/${sessionId}/heartbeat`);
          setHeartbeat(hbData);
          break;
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTabData(activeTab);
  }, [activeTab, sessionId]);

  const handleSetContextValue = async () => {
    if (!newContextKey.trim()) return;
    try {
      let value: unknown = newContextValue;
      // Try to parse as number
      if (/^-?\d+(\.\d+)?$/.test(newContextValue)) {
        value = parseFloat(newContextValue);
      }
      await api(`/api/sessions/${sessionId}/context`, {
        method: 'POST',
        body: JSON.stringify({ key: newContextKey, value }),
      });
      setNewContextKey('');
      setNewContextValue('');
      loadTabData('context');
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleDeleteContextValue = async (key: string) => {
    try {
      await api(`/api/sessions/${sessionId}/context/${encodeURIComponent(key)}`, {
        method: 'DELETE',
      });
      loadTabData('context');
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleReconnect = async (rebootstrap: boolean) => {
    try {
      await api(`/api/sessions/${sessionId}/connection/reconnect?rebootstrap=${rebootstrap}`, {
        method: 'POST',
      });
      loadTabData('connection');
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleResetHeartbeat = async () => {
    try {
      await api(`/api/sessions/${sessionId}/heartbeat/reset`, {
        method: 'POST',
      });
      loadTabData('heartbeat');
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleRerunStage = async (stageName: string) => {
    try {
      await api(`/api/sessions/${sessionId}/stages/${encodeURIComponent(stageName)}/rerun`, {
        method: 'POST',
      });
      loadTabData('stages');
      loadTabData('context'); // Refresh context after rerun
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleReplay = async () => {
    setReplaying(true);
    setError(null);
    try {
      const result = await api<ReplayResponse>(`/api/sessions/${sessionId}/replay`, {
        method: 'POST',
        body: JSON.stringify({
          target_sequence: replaySequence,
          mode: replayMode,
          delay_ms: replayDelay,
          stop_on_error: false,
        }),
      });
      setReplayResult(result);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setReplaying(false);
    }
  };

  const toggleReveal = (key: string) => {
    setRevealedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const formatContextValue = (key: string, value: unknown): string => {
    if (!revealedKeys.has(key)) {
      return '••••••••';
    }
    if (typeof value === 'object') {
      return JSON.stringify(value);
    }
    return String(value);
  };

  const getStatusColor = (status: string): string => {
    switch (status.toLowerCase()) {
      case 'healthy':
      case 'completed':
      case 'active':
      case 'success':
        return 'var(--success)';
      case 'warning':
        return 'var(--warning)';
      case 'failed':
      case 'error':
      case 'timeout':
        return 'var(--error)';
      default:
        return 'var(--text-secondary)';
    }
  };

  return (
    <div className="session-detail-panel">
      <div className="panel-header">
        <h3>Session Details</h3>
        <span className="session-id">{sessionId.slice(0, 8)}...</span>
        <button className="close-btn" onClick={onClose} aria-label="Close session details panel">×</button>
      </div>

      <div className="panel-tabs">
        {(['context', 'stages', 'connection', 'heartbeat', 'replay'] as const).map((tab) => (
          <button
            key={tab}
            className={activeTab === tab ? 'tab active' : 'tab'}
            onClick={() => setActiveTab(tab)}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>

      {error && <div className="panel-error">{error}</div>}

      <div className="panel-content">
        {loading && <div className="loading">Loading...</div>}

        {/* Context Tab */}
        {activeTab === 'context' && context && !loading && (
          <div className="context-section">
            <div className="section-header">
              <span className={`status-badge ${context.bootstrap_complete ? 'complete' : 'pending'}`}>
                Bootstrap: {context.bootstrap_complete ? 'Complete' : 'Pending'}
              </span>
              <span className="key-count">{context.key_count} keys</span>
            </div>

            {Object.keys(context.values).length === 0 ? (
              <p className="empty-state">No context values set.</p>
            ) : (
              <table className="context-table">
                <thead>
                  <tr>
                    <th>Key</th>
                    <th>Value</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(context.values).map(([key, value]) => (
                    <tr key={key}>
                      <td className="key-cell">{key}</td>
                      <td className="value-cell">
                        <code>{formatContextValue(key, value)}</code>
                      </td>
                      <td className="actions-cell">
                        <button
                          className="icon-btn"
                          onClick={() => toggleReveal(key)}
                          title={revealedKeys.has(key) ? 'Hide value' : 'Reveal value'}
                          aria-label={revealedKeys.has(key) ? `Hide value for ${key}` : `Reveal value for ${key}`}
                        >
                          {revealedKeys.has(key) ? '🙈' : '👁'}
                        </button>
                        <button
                          className="icon-btn danger"
                          onClick={() => handleDeleteContextValue(key)}
                          title="Delete value"
                          aria-label={`Delete context value ${key}`}
                        >
                          🗑
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className="add-context-form">
              <input
                type="text"
                placeholder="Key"
                value={newContextKey}
                onChange={(e) => setNewContextKey(e.target.value)}
              />
              <input
                type="text"
                placeholder="Value (or 0x... for hex bytes)"
                value={newContextValue}
                onChange={(e) => setNewContextValue(e.target.value)}
              />
              <button onClick={handleSetContextValue}>Add</button>
            </div>
          </div>
        )}

        {/* Stages Tab */}
        {activeTab === 'stages' && stages && !loading && (
          <div className="stages-section">
            <div className="section-header">
              <span className={`status-badge ${stages.bootstrap_complete ? 'complete' : 'pending'}`}>
                Bootstrap: {stages.bootstrap_complete ? 'Complete' : 'Pending'}
              </span>
            </div>

            <table className="stages-table">
              <thead>
                <tr>
                  <th>Stage</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {stages.stages.map((stage) => (
                  <tr key={stage.name}>
                    <td>{stage.name}</td>
                    <td>
                      <span className={`role-badge ${stage.role}`}>{stage.role}</span>
                    </td>
                    <td>
                      <span style={{ color: getStatusColor(stage.status) }}>{stage.status}</span>
                      {stage.last_error && (
                        <div className="error-hint" title={stage.last_error}>
                          ⚠️ Error
                        </div>
                      )}
                    </td>
                    <td>{stage.attempts}</td>
                    <td>
                      {stage.role === 'bootstrap' && (
                        <button
                          className="small-btn"
                          onClick={() => handleRerunStage(stage.name)}
                        >
                          Re-run
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Connection Tab */}
        {activeTab === 'connection' && connection && !loading && (
          <div className="connection-section">
            <div className="section-header">
              <span className="mode-badge">Mode: {connection.connection_mode}</span>
              <span className="conn-count">{connection.active_connections.length} active</span>
            </div>

            <div className="action-buttons">
              <button onClick={() => handleReconnect(false)}>
                Reconnect
                <Tooltip content="Close and re-open the connection without re-running bootstrap." />
              </button>
              <button onClick={() => handleReconnect(true)}>
                Reconnect + Rebootstrap
                <Tooltip content="Close connection, clear context, and re-run all bootstrap stages." />
              </button>
            </div>

            {connection.active_connections.length === 0 ? (
              <p className="empty-state">No active connections.</p>
            ) : (
              <div className="connections-list">
                {connection.active_connections.map((conn) => (
                  <div key={conn.connection_id} className="connection-card">
                    <div className="conn-header">
                      <span className={`health-indicator ${conn.healthy ? 'healthy' : 'unhealthy'}`}>
                        {conn.healthy ? '●' : '○'}
                      </span>
                      <span className="conn-id">{conn.connection_id.slice(-12)}</span>
                    </div>
                    <div className="conn-stats">
                      <div>
                        <span className="stat-label">Sent</span>
                        <span className="stat-value">{formatBytes(conn.bytes_sent)}</span>
                        <span className="stat-count">({conn.send_count} msgs)</span>
                      </div>
                      <div>
                        <span className="stat-label">Received</span>
                        <span className="stat-value">{formatBytes(conn.bytes_received)}</span>
                        <span className="stat-count">({conn.recv_count} msgs)</span>
                      </div>
                      <div>
                        <span className="stat-label">Reconnects</span>
                        <span className="stat-value">{conn.reconnect_count}</span>
                      </div>
                    </div>
                    <div className="conn-times">
                      <span>Last send: {formatTime(conn.last_send)}</span>
                      <span>Last recv: {formatTime(conn.last_recv)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Heartbeat Tab */}
        {activeTab === 'heartbeat' && heartbeat && !loading && (
          <div className="heartbeat-section">
            <div className="section-header">
              <span className={`status-badge ${heartbeat.enabled ? 'enabled' : 'disabled'}`}>
                {heartbeat.enabled ? 'Enabled' : 'Disabled'}
              </span>
              {heartbeat.status && (
                <span style={{ color: getStatusColor(heartbeat.status) }}>
                  {heartbeat.status}
                </span>
              )}
            </div>

            {!heartbeat.enabled ? (
              <p className="empty-state">Heartbeat is not configured for this protocol.</p>
            ) : (
              <>
                <div className="heartbeat-stats">
                  <div className="stat-card">
                    <span className="stat-label">Interval</span>
                    <span className="stat-value">{heartbeat.interval_ms ?? '-'} ms</span>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Total Sent</span>
                    <span className="stat-value">{heartbeat.total_sent}</span>
                  </div>
                  <div className="stat-card">
                    <span className="stat-label">Failures</span>
                    <span className={`stat-value ${heartbeat.failures > 0 ? 'error' : ''}`}>
                      {heartbeat.failures}
                    </span>
                  </div>
                </div>

                <div className="heartbeat-times">
                  <div>Last sent: {formatTime(heartbeat.last_sent)}</div>
                  <div>Last ack: {formatTime(heartbeat.last_ack)}</div>
                </div>

                {heartbeat.failures > 0 && (
                  <button className="reset-btn" onClick={handleResetHeartbeat}>
                    Reset Failure Count
                  </button>
                )}
              </>
            )}
          </div>
        )}

        {/* Replay Tab */}
        {activeTab === 'replay' && !loading && (
          <div className="replay-section">
            <div className="replay-form">
              <div className="form-row">
                <label>
                  <span>Mode</span>
                  <Tooltip content="Fresh: Re-run bootstrap. Stored: Use exact historical bytes. Skip: No bootstrap." />
                  <select
                    value={replayMode}
                    onChange={(e) => setReplayMode(e.target.value as typeof replayMode)}
                  >
                    <option value="stored">Stored (exact bytes)</option>
                    <option value="fresh">Fresh (re-bootstrap)</option>
                    <option value="skip">Skip (no bootstrap)</option>
                  </select>
                </label>
                <label>
                  <span>Replay up to sequence</span>
                  <input
                    type="number"
                    min="1"
                    value={replaySequence}
                    onChange={(e) => setReplaySequence(parseInt(e.target.value) || 1)}
                  />
                </label>
                <label>
                  <span>Delay (ms)</span>
                  <input
                    type="number"
                    min="0"
                    value={replayDelay}
                    onChange={(e) => setReplayDelay(parseInt(e.target.value) || 0)}
                  />
                </label>
              </div>
              <button
                className="replay-btn"
                onClick={handleReplay}
                disabled={replaying}
              >
                {replaying ? 'Replaying...' : 'Start Replay'}
              </button>
            </div>

            {replayResult && (
              <div className="replay-results">
                <div className="results-summary">
                  <span>Replayed: {replayResult.replayed_count}</span>
                  <span>Skipped: {replayResult.skipped_count}</span>
                  <span>Duration: {replayResult.duration_ms.toFixed(1)} ms</span>
                </div>

                {replayResult.warnings.length > 0 && (
                  <div className="warnings">
                    {replayResult.warnings.map((w, i) => (
                      <div key={i} className="warning">⚠️ {w}</div>
                    ))}
                  </div>
                )}

                <table className="results-table">
                  <thead>
                    <tr>
                      <th>Seq</th>
                      <th>Status</th>
                      <th>Match</th>
                      <th>Duration</th>
                      <th>Preview</th>
                    </tr>
                  </thead>
                  <tbody>
                    {replayResult.results.map((r) => (
                      <tr key={r.original_sequence}>
                        <td>{r.original_sequence}</td>
                        <td style={{ color: getStatusColor(r.status) }}>{r.status}</td>
                        <td>{r.matched_original ? '✓' : '✗'}</td>
                        <td>{r.duration_ms.toFixed(1)} ms</td>
                        <td className="preview-cell">
                          {r.response_preview ? (
                            <code>{r.response_preview.slice(0, 32)}...</code>
                          ) : (
                            r.error || '-'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default SessionDetailPanel;
