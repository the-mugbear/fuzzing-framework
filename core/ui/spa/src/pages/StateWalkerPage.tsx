import { useEffect, useState } from 'react';
import { api } from '../services/api';
import './StateWalkerPage.css';

interface TransitionInfo {
  from: string;
  to: string;
  message_type: string;
  expected_response?: string;
}

interface ExecutionRecord {
  execution_number: number;
  success: boolean;
  old_state: string;
  new_state: string;
  message_type: string;
  sent_hex: string;
  sent_bytes: number;
  sent_parsed?: Record<string, any>;
  response_hex?: string;
  response_bytes: number;
  response_parsed?: Record<string, any>;
  duration_ms: number;
  error?: string;
  timestamp: string;
}

interface WalkerState {
  session_id: string;
  current_state: string;
  valid_transitions: TransitionInfo[];
  state_history: string[];
  transition_history: string[];
  state_coverage: Record<string, number>;
  transition_coverage: Record<string, number>;
  execution_history: ExecutionRecord[];
}

interface ExecuteResponse {
  success: boolean;
  old_state: string;
  new_state: string;
  message_type: string;
  sent_hex: string;
  sent_bytes: number;
  sent_parsed?: Record<string, any>;
  response_hex?: string;
  response_bytes: number;
  response_parsed?: Record<string, any>;
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
  const [expandedExecutions, setExpandedExecutions] = useState<Set<number>>(new Set());

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

  const formatFieldValue = (fieldValue: any) => {
    let displayValue: React.ReactNode;
    let valueClass = '';
    let fieldType = 'unknown';

    // Handle the new structured format from backend
    if (typeof fieldValue === 'object' && fieldValue !== null) {
      fieldType = fieldValue.type || 'unknown';

      if (fieldType.startsWith('uint') || fieldType.startsWith('int')) {
        // Integer field: show decimal and hex
        const numValue = fieldValue.value || 0;
        displayValue = `${numValue} (0x${numValue.toString(16).toUpperCase()})`;
        valueClass = 'value-number';
      } else if (fieldType === 'string') {
        // String field: show decoded value and optionally hex
        const decoded = fieldValue.decoded || '';
        const hex = fieldValue.hex;
        if (hex) {
          displayValue = (
            <>
              <div className="string-decoded">"{decoded}"</div>
              <div className="string-hex">{hex}</div>
            </>
          );
        } else {
          displayValue = `"${decoded}"`;
        }
        valueClass = 'value-string';
      } else if (fieldType === 'bytes') {
        // Bytes field: show hex and optionally decoded text
        const hex = fieldValue.hex || '';
        const decoded = fieldValue.decoded;
        if (decoded) {
          displayValue = (
            <>
              <div className="bytes-decoded">"{decoded}"</div>
              <div className="bytes-hex">{hex}</div>
            </>
          );
        } else {
          displayValue = hex;
        }
        valueClass = 'value-hex';
      } else {
        // Fallback
        displayValue = JSON.stringify(fieldValue);
      }
    } else {
      // Fallback for simple values
      displayValue = String(fieldValue);
    }

    return { displayValue, valueClass, fieldType };
  };

  const renderCombinedParsedFields = (
    sentParsed: Record<string, any> | undefined,
    responseParsed: Record<string, any> | undefined
  ) => {
    // Collect all unique field names from both sent and response
    const sentFields = sentParsed ? Object.keys(sentParsed) : [];
    const responseFields = responseParsed ? Object.keys(responseParsed) : [];
    const allFields = Array.from(new Set([...sentFields, ...responseFields]));

    if (allFields.length === 0) {
      return null;
    }

    return (
      <div className="parsed-fields-combined">
        <h4>Message Comparison</h4>
        <table className="fields-table-combined">
          <thead>
            <tr>
              <th>Field</th>
              <th>Sent</th>
              <th>Received</th>
            </tr>
          </thead>
          <tbody>
            {allFields.map((fieldName) => {
              const sentValue = sentParsed?.[fieldName];
              const responseValue = responseParsed?.[fieldName];

              const sentFormatted = sentValue ? formatFieldValue(sentValue) : null;
              const responseFormatted = responseValue ? formatFieldValue(responseValue) : null;

              return (
                <tr key={fieldName}>
                  <td className="field-name">{fieldName}</td>
                  <td
                    className={`field-value ${sentFormatted?.valueClass || ''}`}
                    title={sentFormatted?.fieldType || ''}
                  >
                    {sentValue ? <code>{sentFormatted?.displayValue}</code> : <span className="no-value">-</span>}
                  </td>
                  <td
                    className={`field-value ${responseFormatted?.valueClass || ''}`}
                    title={responseFormatted?.fieldType || ''}
                  >
                    {responseValue ? <code>{responseFormatted?.displayValue}</code> : <span className="no-value">-</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    );
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

            <div className="state-path">
              <label>State Path:</label>
              <div className="path-chain">
                {walkerState.state_history.length > 0 ? (
                  walkerState.state_history.map((state, i) => (
                    <span key={i} className="path-item">
                      {state}
                      {i < walkerState.state_history.length - 1 && (
                        <span className="path-arrow">&gt;</span>
                      )}
                    </span>
                  ))
                ) : (
                  <span className="path-item current">{walkerState.current_state}</span>
                )}
              </div>
            </div>
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
                        <span className="arrow">&gt;</span>
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

          {walkerState && walkerState.execution_history && walkerState.execution_history.length > 0 && (
            <div className="walker-section card">
              <div className="execution-history-header">
                <h3>Execution History ({walkerState.execution_history.length})</h3>
                <p>Review the complete conversation to verify stateful protocol behavior</p>
              </div>
              <div className="execution-history-list">
                {[...walkerState.execution_history].reverse().map((execution) => {
                  const isExpanded = expandedExecutions.has(execution.execution_number);
                  return (
                    <div key={execution.execution_number} className="execution-record">
                      <div
                        className="execution-record-header"
                        onClick={() => {
                          const newExpanded = new Set(expandedExecutions);
                          if (isExpanded) {
                            newExpanded.delete(execution.execution_number);
                          } else {
                            newExpanded.add(execution.execution_number);
                          }
                          setExpandedExecutions(newExpanded);
                        }}
                      >
                        <div className="execution-record-title">
                          <span className="execution-number">#{execution.execution_number}</span>
                          <span className={`execution-status ${execution.success ? 'success' : 'failure'}`}>
                            {execution.success ? 'OK' : 'FAIL'}
                          </span>
                          <div className="execution-transition">
                            <span className="old-state">{execution.old_state}</span>
                            <span className="arrow">&gt;</span>
                            <span className="new-state">{execution.new_state}</span>
                            <span className="message-type">{execution.message_type}</span>
                          </div>
                        </div>
                        <span className="expand-icon">{isExpanded ? 'v' : '>'}</span>
                      </div>

                      {isExpanded && (
                        <div className="execution-record-body">
                          {execution.error && (
                            <div className="execution-error">Error: {execution.error}</div>
                          )}

                          <div className="execution-details">
                            <div className="hex-displays">
                              <div className="detail-group">
                                <label>Sent ({execution.sent_bytes} bytes)</label>
                                <pre className="hex-display">{execution.sent_hex}</pre>
                              </div>
                              {execution.response_hex && (
                                <div className="detail-group">
                                  <label>Received ({execution.response_bytes} bytes)</label>
                                  <pre className="hex-display">{execution.response_hex}</pre>
                                </div>
                              )}
                            </div>

                            {renderCombinedParsedFields(execution.sent_parsed, execution.response_parsed)}

                            <div className="detail-meta">
                              <span>Duration: {execution.duration_ms.toFixed(2)} ms</span>
                              <span>Time: {new Date(execution.timestamp).toLocaleTimeString()}</span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
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
