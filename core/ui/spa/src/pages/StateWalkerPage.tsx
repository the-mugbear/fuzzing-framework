import { useEffect, useState } from 'react';
import { api } from '../services/api';
import './StateWalkerPage.css';

interface TransitionInfo {
  from: string;
  to: string;
  message_type: string;
  expected_response?: string;
}

interface WalkerState {
  session_id: string;
  current_state: string;
  valid_transitions: TransitionInfo[];
  state_history: string[];
  transition_history: string[];
  state_coverage: Record<string, number>;
  transition_coverage: Record<string, number>;
}

interface ExecuteResponse {
  success: boolean;
  old_state: string;
  new_state: string;
  message_type: string;
  sent_hex: string;
  sent_bytes: number;
  response_hex?: string;
  response_bytes: number;
  duration_ms: number;
  error?: string;
  current_state: WalkerState;
}

function StateWalkerPage() {
  const [protocols, setProtocols] = useState<string[]>([]);
  const [selectedProtocol, setSelectedProtocol] = useState('');
  const [walkerState, setWalkerState] = useState<WalkerState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [lastExecution, setLastExecution] = useState<ExecuteResponse | null>(null);
  const [targetHost, setTargetHost] = useState('target');
  const [targetPort, setTargetPort] = useState(9999);

  // Load available protocols
  useEffect(() => {
    api<string[]>('/api/plugins')
      .then((names) => {
        setProtocols(names);
        if (names.length > 0) {
          setSelectedProtocol(names[0]);
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  const handleInitialize = async () => {
    if (!selectedProtocol) return;

    setLoading(true);
    setError(null);
    setWalkerState(null);
    setLastExecution(null);

    try {
      const state = await api<WalkerState>('/api/walker/init', {
        method: 'POST',
        body: JSON.stringify({ protocol: selectedProtocol }),
      });

      setWalkerState(state);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleExecuteTransition = async (transitionIndex: number) => {
    if (!walkerState) return;

    setExecuting(true);
    setError(null);

    try {
      const result = await api<ExecuteResponse>('/api/walker/execute', {
        method: 'POST',
        body: JSON.stringify({
          session_id: walkerState.session_id,
          transition_index: transitionIndex,
          target_host: targetHost,
          target_port: targetPort,
        }),
      });

      setLastExecution(result);
      setWalkerState(result.current_state);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setExecuting(false);
    }
  };

  const handleReset = async () => {
    if (!walkerState) return;

    setLoading(true);
    setError(null);
    setLastExecution(null);

    try {
      const state = await api<WalkerState>(`/api/walker/${walkerState.session_id}/reset`, {
        method: 'POST',
      });

      setWalkerState(state);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const getCoveragePercentage = (coverage: Record<string, number>, total: number): number => {
    const visited = Object.keys(coverage).length;
    return total > 0 ? Math.round((visited / total) * 100) : 0;
  };

  return (
    <div className="state-walker-page">
      <div className="walker-header card">
        <div>
          <p className="eyebrow">Interactive State Validation</p>
          <h2>State Machine Walker</h2>
          <p>
            Step through protocol state machines, validate transitions, and test stateful
            sequences before fuzzing.
          </p>
        </div>
      </div>

      {error && (
        <div className="error-banner card">
          <strong>Error:</strong> {error}
        </div>
      )}

      <div className="walker-controls card">
        <div className="control-row">
          <div className="control-group">
            <label htmlFor="protocol">Protocol</label>
            <select
              id="protocol"
              value={selectedProtocol}
              onChange={(e) => setSelectedProtocol(e.target.value)}
              disabled={loading || !!walkerState}
            >
              {protocols.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          <div className="control-group">
            <label htmlFor="target-host">Target Host</label>
            <input
              id="target-host"
              value={targetHost}
              onChange={(e) => setTargetHost(e.target.value)}
              disabled={executing}
            />
          </div>

          <div className="control-group">
            <label htmlFor="target-port">Target Port</label>
            <input
              id="target-port"
              type="number"
              value={targetPort}
              onChange={(e) => setTargetPort(Number(e.target.value))}
              disabled={executing}
            />
          </div>

          <div className="control-group button-group">
            <label>&nbsp;</label>
            <div className="button-row">
              {!walkerState ? (
                <button
                  type="button"
                  onClick={handleInitialize}
                  disabled={loading || !selectedProtocol}
                  className="init-btn"
                >
                  {loading ? 'Initializing...' : 'Initialize Walker'}
                </button>
              ) : (
                <button
                  type="button"
                  onClick={handleReset}
                  disabled={loading}
                  className="reset-btn"
                >
                  Reset to Initial State
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {walkerState && (
        <>
          <div className="walker-status card">
            <div className="status-header">
              <h3>Current State: <span className="state-name">{walkerState.current_state}</span></h3>
              <div className="coverage-badges">
                <div className="coverage-badge">
                  <span className="badge-label">State Coverage</span>
                  <span className="badge-value">
                    {getCoveragePercentage(
                      walkerState.state_coverage,
                      Object.keys(walkerState.state_coverage).length +
                      (walkerState.valid_transitions.length > 0 ? walkerState.valid_transitions.map(t => [t.from, t.to]).flat().filter((v, i, a) => a.indexOf(v) === i).length : 0)
                    )}%
                  </span>
                </div>
                <div className="coverage-badge">
                  <span className="badge-label">Transition Coverage</span>
                  <span className="badge-value">
                    {Object.keys(walkerState.transition_coverage).length} visited
                  </span>
                </div>
              </div>
            </div>

            {walkerState.state_history.length > 0 && (
              <div className="state-path">
                <label>State Path:</label>
                <div className="path-chain">
                  {walkerState.state_history.map((state, i) => (
                    <span key={i} className="path-item">
                      {state}
                      {i < walkerState.state_history.length - 1 && (
                        <span className="path-arrow">→</span>
                      )}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div className="walker-section card">
            <h3>Available Transitions ({walkerState.valid_transitions.length})</h3>
            {walkerState.valid_transitions.length === 0 ? (
              <p className="no-transitions">
                No transitions available from state "{walkerState.current_state}".
                This may be a terminal state.
              </p>
            ) : (
              <div className="transitions-list">
                {walkerState.valid_transitions.map((transition, index) => (
                  <div key={index} className="transition-card">
                    <div className="transition-info">
                      <div className="transition-flow">
                        <span className="from-state">{transition.from}</span>
                        <span className="arrow">→</span>
                        <span className="to-state">{transition.to}</span>
                      </div>
                      <div className="transition-details">
                        <span className="message-type">{transition.message_type}</span>
                        {transition.expected_response && (
                          <span className="expected-response">
                            Expects: {transition.expected_response}
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => handleExecuteTransition(index)}
                      disabled={executing}
                      className="execute-btn"
                    >
                      {executing ? 'Executing...' : 'Execute'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          {lastExecution && (
            <div className="walker-section card execution-result">
              <h3>Last Execution Result</h3>
              <div className="execution-summary">
                <div className={`execution-status ${lastExecution.success ? 'success' : 'failure'}`}>
                  {lastExecution.success ? '✓ Success' : '✗ Failed'}
                  {lastExecution.error && <span className="error-detail">: {lastExecution.error}</span>}
                </div>
                <div className="execution-transition">
                  <span className="old-state">{lastExecution.old_state}</span>
                  <span className="arrow">→</span>
                  <span className="new-state">{lastExecution.new_state}</span>
                  <span className="message-type">via {lastExecution.message_type}</span>
                </div>
              </div>

              <div className="execution-details">
                <div className="detail-group">
                  <label>Sent ({lastExecution.sent_bytes} bytes)</label>
                  <pre className="hex-display">{lastExecution.sent_hex}</pre>
                </div>
                {lastExecution.response_hex && (
                  <div className="detail-group">
                    <label>Received ({lastExecution.response_bytes} bytes)</label>
                    <pre className="hex-display">{lastExecution.response_hex}</pre>
                  </div>
                )}
                <div className="detail-meta">
                  <span>Duration: {lastExecution.duration_ms.toFixed(2)} ms</span>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {loading && (
        <div className="loading-overlay">
          <p>Loading...</p>
        </div>
      )}
    </div>
  );
}

export default StateWalkerPage;
