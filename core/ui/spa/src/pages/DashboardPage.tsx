import React, { FormEvent, useEffect, useReducer, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import SessionDetailPanel from '../components/SessionDetailPanel';
import StatusBadge from '../components/StatusBadge';
import Toast, { ToastVariant } from '../components/Toast';
import Tooltip from '../components/Tooltip';
import { api } from '../services/api';
import './DashboardPage.css';

interface FuzzSession {
  id: string;
  protocol: string;
  target_host: string;
  target_port: number;
  status: string;
  execution_mode: string;
  total_tests: number;
  crashes: number;
  hangs: number;
  anomalies: number;
  // Coverage and targeting
  current_state?: string;
  state_coverage?: Record<string, number>;
  transition_coverage?: Record<string, number>;
  field_mutation_counts?: Record<string, number>;
  fuzzing_mode?: string;
  target_state?: string;
  // Orchestration fields
  connection_mode?: string;
  heartbeat_enabled?: boolean;
  heartbeat_failures?: number;
}

interface ProtocolField {
  name: string;
  type: string;
  mutable: boolean;
}

interface PluginDetails {
  state_model?: {
    states?: string[];
  };
}

interface CreateSessionForm {
  protocol: string;
  target_host: string;
  target_port: number;
  execution_mode: 'core' | 'agent';
  mutation_mode: string;
  structure_aware_weight: number;
  rate_limit_per_second: number | '';
  max_iterations: number | '';
  timeout_per_test_ms: number;
  // Mutator selection
  enabled_mutators: string[];
  show_mutator_controls: boolean;
  // Targeting options
  fuzzing_mode: string;
  target_state: string;
  show_field_controls: boolean;
  mutable_fields: string[];  // Field names that should be mutated
  // Session lifecycle options
  session_reset_interval: number | '';
  enable_termination_fuzzing: boolean;
}

type FormAction =
  | { type: 'set_field'; field: keyof CreateSessionForm; value: any }
  | { type: 'reset'; payload?: Partial<CreateSessionForm> };

// Mutator descriptions for tooltips
const MUTATOR_INFO: Record<string, { name: string; description: string; example: string }> = {
  bitflip: {
    name: 'Bit Flip',
    description: 'Flips random bits in the input',
    example: '0x41 (01000001) → 0x43 (01000011)',
  },
  byteflip: {
    name: 'Byte Flip',
    description: 'Replaces random bytes with random values',
    example: 'ABCD → AXCD (B→X)',
  },
  arithmetic: {
    name: 'Arithmetic',
    description: 'Adds or subtracts small integers from fields',
    example: '100 → 101, 99, 108, 92...',
  },
  interesting: {
    name: 'Interesting Values',
    description: 'Replaces with boundary values known to trigger bugs',
    example: '42 → 0, 255, 0x7FFFFFFF, -1',
  },
  havoc: {
    name: 'Havoc',
    description: 'Aggressive random mutations: insert, delete, shuffle bytes',
    example: 'ABCD → AXXBCD (insert) or AD (delete)',
  },
  splice: {
    name: 'Splice',
    description: 'Combines parts of two different test cases',
    example: 'ABC + XYZ → ABYZ or AXYZ',
  },
};

const ALL_MUTATORS = ['bitflip', 'byteflip', 'arithmetic', 'interesting', 'havoc', 'splice'];

const initialForm: CreateSessionForm = {
  protocol: '',
  target_host: 'target',
  target_port: 9999,
  execution_mode: 'core',
  mutation_mode: 'hybrid',
  structure_aware_weight: 70,
  rate_limit_per_second: '',
  max_iterations: '',
  timeout_per_test_ms: 5000,
  // Mutator selection
  enabled_mutators: [...ALL_MUTATORS],  // All enabled by default
  show_mutator_controls: false,
  // Targeting options
  fuzzing_mode: 'random',
  target_state: '',
  show_field_controls: false,
  mutable_fields: [],
  // Session lifecycle options
  session_reset_interval: '',
  enable_termination_fuzzing: false,
};

function formReducer(state: CreateSessionForm, action: FormAction): CreateSessionForm {
  switch (action.type) {
    case 'set_field':
      return { ...state, [action.field]: action.value };
    case 'reset':
      return { ...initialForm, ...(action.payload || {}) };
    default:
      return state;
  }
}

function DashboardPage() {
  const navigate = useNavigate();
  const [protocols, setProtocols] = useState<string[]>([]);
  const [sessions, setSessions] = useState<FuzzSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [toast, setToast] = useState<{ variant: ToastVariant; message: string } | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [form, dispatch] = useReducer(formReducer, initialForm);
  const [protocolFields, setProtocolFields] = useState<ProtocolField[]>([]);
  const [protocolStates, setProtocolStates] = useState<string[]>([]);
  const [expandedSession, setExpandedSession] = useState<string | null>(null);
  const refreshTimer = useRef<number>();

  const refreshSessions = () => {
    setLoading(true);
    api<FuzzSession[]>('/api/sessions')
      .then((data) => {
        setSessions(data);
        setLastUpdated(new Date().toLocaleTimeString());
      })
      .catch((err) => setToast({ variant: 'error', message: `Failed to load sessions: ${err.message}` }))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    api<string[]>('/api/plugins')
      .then((names) => {
        setProtocols(names);
      })
      .catch((err) => setToast({ variant: 'error', message: `Failed to load plugins: ${err.message}` }));
    refreshSessions();
    refreshTimer.current = window.setInterval(refreshSessions, 10000);
    return () => {
      if (refreshTimer.current) {
        window.clearInterval(refreshTimer.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!form.protocol && protocols.length) {
      dispatch({ type: 'set_field', field: 'protocol', value: protocols[0] });
    }
  }, [protocols, form.protocol]);

  useEffect(() => {
    if (!form.protocol) {
      setProtocolStates([]);
      return;
    }
    api<PluginDetails>(`/api/plugins/${form.protocol}`)
      .then((details) => {
        const states = details.state_model?.states ?? [];
        setProtocolStates(states);
        if (form.target_state && !states.includes(form.target_state)) {
          dispatch({ type: 'set_field', field: 'target_state', value: '' });
        }
      })
      .catch((err) => {
        setProtocolStates([]);
        setToast({ variant: 'error', message: `Failed to load plugin details: ${err.message}` });
      });
  }, [form.protocol]);

  const validateForm = () => {
    const issues: string[] = [];
    if (!form.protocol) issues.push('Protocol is required.');
    if (!form.target_host.trim()) issues.push('Target host is required.');
    if (!Number.isInteger(form.target_port) || form.target_port <= 0) issues.push('Target port must be a positive integer.');
    if (form.rate_limit_per_second !== '' && Number(form.rate_limit_per_second) <= 0)
      issues.push('Rate limit must be positive.');
    if (form.max_iterations !== '' && Number(form.max_iterations) <= 0)
      issues.push('Max iterations must be positive.');
    if (form.timeout_per_test_ms < 100) issues.push('Timeout must be at least 100ms.');
    // Validate mutators for random modes
    if (['hybrid', 'structure_aware', 'byte_level'].includes(form.mutation_mode) &&
        form.show_mutator_controls && form.enabled_mutators.length === 0) {
      issues.push('At least one mutator must be enabled.');
    }
    return issues;
  };

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    const issues = validateForm();
    if (issues.length) {
      setToast({ variant: 'error', message: issues.join(' ') });
      return;
    }
    try {
      const payload = {
        protocol: form.protocol,
        target_host: form.target_host,
        target_port: Number(form.target_port),
        execution_mode: form.execution_mode,
        mutation_mode: form.mutation_mode,
        structure_aware_weight: form.structure_aware_weight,
        timeout_per_test_ms: form.timeout_per_test_ms,
        // NEW: Targeting options
        fuzzing_mode: form.fuzzing_mode,
      } as Record<string, unknown>;

      if (form.rate_limit_per_second !== '') {
        payload.rate_limit_per_second = Number(form.rate_limit_per_second);
      }
      if (form.max_iterations !== '') {
        payload.max_iterations = Number(form.max_iterations);
      }
      if (form.target_state && form.target_state.trim() !== '') {
        payload.target_state = form.target_state.trim();
      }
      if (form.session_reset_interval !== '') {
        payload.session_reset_interval = Number(form.session_reset_interval);
      }
      if (form.enable_termination_fuzzing) {
        payload.enable_termination_fuzzing = true;
      }
      // Include custom mutator selection if user has customized it
      if (form.show_mutator_controls && form.enabled_mutators.length > 0 &&
          form.enabled_mutators.length < ALL_MUTATORS.length) {
        payload.enabled_mutators = form.enabled_mutators;
      }

      await api('/api/sessions', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      setToast({ variant: 'success', message: 'Session created.' });
      refreshSessions();
    } catch (err) {
      setToast({ variant: 'error', message: `Create failed: ${(err as Error).message}` });
    }
  };

  const handleStart = async (id: string) => {
    setActionInProgress(id);
    try {
      await api(`/api/sessions/${id}/start`, { method: 'POST' });
      setToast({ variant: 'success', message: 'Session started.' });
      refreshSessions();
    } catch (err) {
      setToast({ variant: 'error', message: `Start failed: ${(err as Error).message}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleStop = async (id: string) => {
    setActionInProgress(id);
    try {
      await api(`/api/sessions/${id}/stop`, { method: 'POST' });
      setToast({ variant: 'success', message: 'Session stopped.' });
      refreshSessions();
    } catch (err) {
      setToast({ variant: 'error', message: `Stop failed: ${(err as Error).message}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleDelete = async (id: string) => {
    if (!window.confirm('Are you sure you want to delete this session? This cannot be undone.')) {
      return;
    }

    setActionInProgress(id);
    try {
      await api(`/api/sessions/${id}`, { method: 'DELETE' });
      setToast({ variant: 'success', message: 'Session deleted.' });
      refreshSessions();
    } catch (err) {
      setToast({ variant: 'error', message: `Delete failed: ${(err as Error).message}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleOpenGraph = (id: string) => {
    navigate(`/state-graph?session=${encodeURIComponent(id)}`);
  };

  const runningSessions = sessions.filter((session) => session.status === 'RUNNING').length;
  const totalTests = sessions.reduce((acc, session) => acc + (session.total_tests || 0), 0);
  const totalCrashes = sessions.reduce((acc, session) => acc + (session.crashes || 0), 0);

  return (
    <div className="dashboard-grid">
      <section className="card">
        <div className="section-header">
          <div>
            <p className="eyebrow">Launch Campaign</p>
            <h2>Create Session</h2>
          </div>
          <div className="hint">Configure a target &amp; mutation strategy</div>
        </div>
        <form className="session-form" onSubmit={handleCreate}>
          <label>
            <span className="label-text">
              Protocol
              <Tooltip content="Select a protocol plugin that defines message structure and state machine for fuzzing." />
            </span>
            <select
              value={form.protocol}
              onChange={(e) => dispatch({ type: 'set_field', field: 'protocol', value: e.target.value })}
            >
              {protocols.length === 0 && <option>Loading...</option>}
              {protocols.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span className="label-text">
              Target Host
              <Tooltip content="Hostname or IP of the target. Use 'target' for Docker service name, or 'host.docker.internal' for host machine." />
            </span>
            <input
                value={form.target_host}
              onChange={(e) => dispatch({ type: 'set_field', field: 'target_host', value: e.target.value })}
            />
          </label>
          <label>
            <span className="label-text">
              Target Port
              <Tooltip content="TCP/UDP port the target listens on. Must match the protocol's expected port." />
            </span>
            <input
                type="number"
                value={form.target_port}
              onChange={(e) => dispatch({ type: 'set_field', field: 'target_port', value: Number(e.target.value) })}
            />
          </label>
          <label>
            <span className="label-text">
              Execution Mode
              <Tooltip content="Core: Execute tests locally. Agent: Distribute tests to remote workers near the target." />
            </span>
            <select
              value={form.execution_mode}
              onChange={(e) => dispatch({ type: 'set_field', field: 'execution_mode', value: e.target.value as 'core' | 'agent' })}
            >
              <option value="core">Core</option>
              <option value="agent">Agent</option>
            </select>
          </label>
          <label>
            <span className="label-text">
              Mutation Strategy
              <Tooltip content="Random modes mutate probabilistically. Enumeration modes systematically test boundary values for comprehensive coverage." />
            </span>
            <select
              value={form.mutation_mode}
              onChange={(e) => dispatch({ type: 'set_field', field: 'mutation_mode', value: e.target.value })}
            >
              <optgroup label="Random Mutations">
                <option value="hybrid">Hybrid (structure + byte-level)</option>
                <option value="structure_aware">Structure-Aware (field boundaries)</option>
                <option value="byte_level">Byte-Level (raw bytes)</option>
              </optgroup>
              <optgroup label="Systematic Enumeration">
                <option value="enumeration">Enumeration (one field at a time)</option>
                <option value="enumeration_pairwise">Pairwise (all field pairs)</option>
                <option value="enumeration_full">Full Permutation (all combinations)</option>
              </optgroup>
            </select>
          </label>
          {form.mutation_mode === 'hybrid' && (
            <label>
              <span className="label-text">
                Structure-Aware Weight ({form.structure_aware_weight}%)
                <Tooltip content="Percentage of mutations that use structure-aware logic vs byte-level. Higher = more field-aware mutations." />
              </span>
              <input
                type="range"
                min="0"
                max="100"
                value={form.structure_aware_weight}
                onChange={(e) =>
                  dispatch({ type: 'set_field', field: 'structure_aware_weight', value: Number(e.target.value) })
                }
              />
            </label>
          )}

          {/* Mutator Selection - only for random mutation modes */}
          {['hybrid', 'structure_aware', 'byte_level'].includes(form.mutation_mode) && (
            <>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.show_mutator_controls}
                  onChange={(e) => dispatch({ type: 'set_field', field: 'show_mutator_controls', value: e.target.checked })}
                />
                <span>
                  Customize Mutators
                  <Tooltip content="Select which mutation algorithms to use. By default all are enabled. Disabling some can focus the fuzzer on specific strategies." />
                </span>
              </label>

              {form.show_mutator_controls && (
                <div className="mutator-selection">
                  <div className="mutator-grid">
                    {ALL_MUTATORS.map((mutator) => {
                      const info = MUTATOR_INFO[mutator];
                      return (
                        <label key={mutator} className="mutator-item">
                          <input
                            type="checkbox"
                            checked={form.enabled_mutators.includes(mutator)}
                            onChange={(e) => {
                              const newMutators = e.target.checked
                                ? [...form.enabled_mutators, mutator]
                                : form.enabled_mutators.filter((m) => m !== mutator);
                              dispatch({ type: 'set_field', field: 'enabled_mutators', value: newMutators });
                            }}
                          />
                          <span className="mutator-name">{info.name}</span>
                          <Tooltip content={`${info.description}\n\nExample: ${info.example}`} />
                        </label>
                      );
                    })}
                  </div>
                  {form.enabled_mutators.length === 0 && (
                    <div className="warning-text">At least one mutator must be enabled</div>
                  )}
                </div>
              )}
            </>
          )}

          {/* Enumeration mode info */}
          {form.mutation_mode.startsWith('enumeration') && (
            <div className="info-box">
              <strong>Enumeration Mode:</strong> Systematically tests boundary values (0, 1, max-1, max) for each mutable field.
              {form.mutation_mode === 'enumeration' && ' Varies one field at a time.'}
              {form.mutation_mode === 'enumeration_pairwise' && ' Tests all pairs of field values.'}
              {form.mutation_mode === 'enumeration_full' && ' Tests ALL combinations (can be very large!).'}
              {' '}After enumeration completes, falls back to random mutation.
            </div>
          )}
          <label>
            <span className="label-text">
              Rate Limit (tests/sec)
              <Tooltip content="Throttle test execution to avoid overwhelming the target. Leave empty for maximum speed." />
            </span>
            <input
                type="number"
                min="1"
                placeholder="Unlimited"
                value={form.rate_limit_per_second}
                onChange={(e) =>
                dispatch({
                  type: 'set_field',
                  field: 'rate_limit_per_second',
                  value: e.target.value ? Number(e.target.value) : '',
                })
                }
              />
          </label>
          <label>
            <span className="label-text">
              Max Iterations
              <Tooltip content="Stop session after this many test cases. Leave empty to run indefinitely until manually stopped." />
            </span>
            <input
                type="number"
                min="1"
                placeholder="No limit"
                value={form.max_iterations}
                onChange={(e) =>
                dispatch({
                  type: 'set_field',
                  field: 'max_iterations',
                  value: e.target.value ? Number(e.target.value) : '',
                })
                }
              />
          </label>
          <label>
            <span className="label-text">
              Timeout per Test (ms)
              <Tooltip content="Maximum time to wait for target response. Increase for slow targets, decrease for faster feedback." />
            </span>
            <input
                type="number"
                min="100"
                value={form.timeout_per_test_ms}
              onChange={(e) => dispatch({ type: 'set_field', field: 'timeout_per_test_ms', value: Number(e.target.value) })}
            />
          </label>

          <label>
            <span className="label-text">
              Fuzzing Mode
              <Tooltip content="Random: Default exploration. Breadth-First: Visit all states evenly. Depth-First: Follow deep paths. Targeted: Focus on one state." />
            </span>
            <select
              value={form.fuzzing_mode}
              onChange={(e) => dispatch({ type: 'set_field', field: 'fuzzing_mode', value: e.target.value })}
            >
              <option value="random">Random (Default)</option>
              <option value="breadth_first">Breadth-First (Explore all states evenly)</option>
              <option value="depth_first">Depth-First (Follow deep paths)</option>
              <option value="targeted">Targeted (Focus on specific state)</option>
            </select>
          </label>

          {form.fuzzing_mode === 'targeted' && (
            <label>
              <span className="label-text">
                Target State
                <Tooltip content="The specific state to focus testing on. The fuzzer will navigate to this state and concentrate mutations there." />
              </span>
              <select
                value={form.target_state}
                onChange={(e) => dispatch({ type: 'set_field', field: 'target_state', value: e.target.value })}
                disabled={protocolStates.length === 0}
              >
                <option value="">
                  {protocolStates.length === 0 ? 'No states available' : 'Select a state'}
                </option>
                {protocolStates.map((state) => (
                  <option key={state} value={state}>
                    {state}
                  </option>
                ))}
              </select>
            </label>
          )}

          <label>
            <span className="label-text">
              Session Reset Interval
              <Tooltip content="Reset protocol state machine every N test cases. Helps test connection setup/teardown and prevents getting stuck in deep states." />
            </span>
            <input
              type="number"
              min="1"
              placeholder="No reset"
              value={form.session_reset_interval}
              onChange={(e) =>
                dispatch({
                  type: 'set_field',
                  field: 'session_reset_interval',
                  value: e.target.value ? Number(e.target.value) : '',
                })
              }
            />
          </label>

          <label className="checkbox-label">
            <input
              type="checkbox"
              checked={form.enable_termination_fuzzing}
              onChange={(e) => dispatch({ type: 'set_field', field: 'enable_termination_fuzzing', value: e.target.checked })}
            />
            <span className="label-text">
              Enable Termination Fuzzing
              <Tooltip content="Periodically inject termination/close state transitions to test connection cleanup, resource deallocation, and session teardown code." />
            </span>
          </label>

          <button type="submit">Create Session</button>
        </form>
        {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
      </section>
      <section className="card sessions-card">
        <div className="session-header">
          <div>
            <p className="eyebrow">Active Campaigns</p>
            <h2>Sessions</h2>
          </div>
          <div className="session-toolbar">
            <span className="hint">Last refreshed {lastUpdated || '-'}</span>
            <button onClick={refreshSessions} disabled={loading}>
              Refresh
            </button>
          </div>
        </div>
        <div className="session-stats">
          <div>
            <span>Running</span>
            <strong>{runningSessions}</strong>
          </div>
          <div>
            <span>Total Tests</span>
            <strong>{totalTests}</strong>
          </div>
          <div>
            <span>Crashes</span>
            <strong>{totalCrashes}</strong>
          </div>
        </div>
        {sessions.length === 0 ? (
          <p>No sessions yet.</p>
        ) : (
          <table className="session-table">
            <thead>
              <tr>
                <th></th>
                <th>ID</th>
                <th>Protocol</th>
                <th>Status</th>
                <th>Target</th>
                <th>Stats</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => {
                const hasCoverage = session.state_coverage && Object.keys(session.state_coverage).length > 0;
                const totalStates = hasCoverage && session.state_coverage ? Object.keys(session.state_coverage).length : 0;
                const visitedStates = hasCoverage && session.state_coverage
                  ? Object.values(session.state_coverage).filter(count => count > 0).length
                  : 0;
                const coveragePct = totalStates > 0 ? Math.round((visitedStates / totalStates) * 100) : 0;
                const isExpanded = expandedSession === session.id;

                return (
                  <React.Fragment key={session.id}>
                    <tr className={isExpanded ? 'expanded' : ''}>
                      <td>
                        <button
                          className="expand-btn"
                          onClick={() => setExpandedSession(isExpanded ? null : session.id)}
                          title={isExpanded ? 'Collapse' : 'Expand details'}
                        >
                          {isExpanded ? '▼' : '▶'}
                        </button>
                      </td>
                      <td>
                        <Link className="session-link" to={`/correlation?session=${encodeURIComponent(session.id)}`}>
                          {session.id.slice(0, 8)}...
                        </Link>
                      </td>
                      <td>{session.protocol}</td>
                      <td>
                        <StatusBadge value={session.status} />
                        {session.current_state && (
                          <div style={{ fontSize: '0.85em', color: 'var(--text-tertiary)', marginTop: '0.25rem' }}>
                            State: {session.current_state}
                          </div>
                        )}
                        <div className="health-indicators">
                          {session.connection_mode && session.connection_mode !== 'per_test' && (
                            <span className="health-badge conn" title={`Connection: ${session.connection_mode}`}>
                              ⚡
                            </span>
                          )}
                          {session.heartbeat_enabled && (
                            <span
                              className={`health-badge hb ${session.heartbeat_failures && session.heartbeat_failures > 0 ? 'warn' : ''}`}
                              title={`Heartbeat: ${session.heartbeat_failures || 0} failures`}
                            >
                              ❤️
                            </span>
                          )}
                        </div>
                      </td>
                      <td>
                        {session.target_host}:{session.target_port}
                        {session.target_state && (
                          <div style={{ fontSize: '0.85em', color: 'var(--text-tertiary)', marginTop: '0.25rem' }}>
                            Target: {session.target_state}
                          </div>
                        )}
                      </td>
                      <td>
                        <div>{session.total_tests} tests | {session.crashes} crashes</div>
                        {hasCoverage && (
                          <div style={{ fontSize: '0.85em', color: 'var(--text-accent)', marginTop: '0.25rem' }}>
                            Coverage: {visitedStates}/{totalStates} states ({coveragePct}%)
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="session-actions">
                          <button
                            onClick={() => handleStart(session.id)}
                            disabled={actionInProgress === session.id}
                          >
                            {actionInProgress === session.id ? 'Starting...' : 'Start'}
                          </button>
                          <button
                            onClick={() => handleStop(session.id)}
                            className="ghost"
                            disabled={actionInProgress === session.id}
                          >
                            {actionInProgress === session.id ? 'Stopping...' : 'Stop'}
                          </button>
                          <button
                            onClick={() => handleDelete(session.id)}
                            className="danger"
                            disabled={actionInProgress === session.id}
                            title="Delete session"
                          >
                            Delete
                          </button>
                          {hasCoverage && (
                            <button
                              type="button"
                              className="ghost"
                              title="View State Graph"
                              onClick={() => handleOpenGraph(session.id)}
                            >
                              State Graph
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="detail-row">
                        <td colSpan={7}>
                          <SessionDetailPanel
                            sessionId={session.id}
                            onClose={() => setExpandedSession(null)}
                          />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default DashboardPage;
