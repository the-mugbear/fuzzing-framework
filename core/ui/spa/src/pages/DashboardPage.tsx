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
  execution_mode: 'core' | 'probe';
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

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});

  const validateField = (field: string, value: any) => {
    let error = '';
    switch (field) {
      case 'protocol':
        if (!value) error = 'Required';
        break;
      case 'target_host':
        if (!String(value).trim()) error = 'Required';
        break;
      case 'target_port':
        if (!Number.isInteger(value) || value <= 0) error = 'Must be a positive integer';
        break;
      case 'rate_limit_per_second':
        if (value !== '' && Number(value) <= 0) error = 'Must be positive';
        break;
      case 'max_iterations':
        if (value !== '' && Number(value) <= 0) error = 'Must be positive';
        break;
      case 'timeout_per_test_ms':
        if (Number(value) < 100) error = 'Minimum 100ms';
        break;
    }
    setFieldErrors(prev => {
      const next = { ...prev };
      if (error) next[field] = error; else delete next[field];
      return next;
    });
    return error;
  };

  const handleFieldChange = (field: keyof CreateSessionForm, value: any) => {
    dispatch({ type: 'set_field', field, value });
    validateField(field, value);
  };

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
    const fields = ['protocol', 'target_host', 'target_port', 'rate_limit_per_second', 'max_iterations', 'timeout_per_test_ms'] as const;
    const errors: string[] = [];
    for (const field of fields) {
      const err = validateField(field, form[field]);
      if (err) errors.push(`${field}: ${err}`);
    }
    if (['hybrid', 'structure_aware', 'byte_level'].includes(form.mutation_mode) &&
        form.show_mutator_controls && form.enabled_mutators.length === 0) {
      errors.push('At least one mutator must be enabled.');
    }
    return errors;
  };

  const handleCreate = async (event: FormEvent) => {
    event.preventDefault();
    const issues = validateForm();
    if (issues.length) {
      setToast({ variant: 'error', message: 'Please fix the highlighted fields before creating a session.' });
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
          <div className="hint">Set a target and start fuzzing. Defaults work well for getting started.</div>
        </div>
        <form className="session-form" onSubmit={handleCreate}>
          {/* — Essential fields (always visible) — */}
          <label className={fieldErrors.protocol ? 'has-error' : ''}>
            <span className="label-text">
              Protocol
              <Tooltip content="Choose which protocol plugin to use. This determines the message format and how the fuzzer talks to your target." />
            </span>
            <select
              value={form.protocol}
              onChange={(e) => handleFieldChange('protocol', e.target.value)}
              onBlur={() => validateField('protocol', form.protocol)}
              aria-invalid={!!fieldErrors.protocol}
            >
              {protocols.length === 0 && <option>Loading...</option>}
              {protocols.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
            {fieldErrors.protocol && <span className="field-error" role="alert">{fieldErrors.protocol}</span>}
          </label>
          <label className={fieldErrors.target_host ? 'has-error' : ''}>
            <span className="label-text">
              Target Host
              <Tooltip content="Where is the target running? Use 'target' for Docker, 'localhost' for local, or an IP address." />
            </span>
            <input
                value={form.target_host}
              onChange={(e) => handleFieldChange('target_host', e.target.value)}
              onBlur={() => validateField('target_host', form.target_host)}
              aria-invalid={!!fieldErrors.target_host}
            />
            {fieldErrors.target_host && <span className="field-error" role="alert">{fieldErrors.target_host}</span>}
          </label>
          <label className={fieldErrors.target_port ? 'has-error' : ''}>
            <span className="label-text">
              Target Port
              <Tooltip content="The port your target listens on. Default is 9999 for the sample target." />
            </span>
            <input
                type="number"
                value={form.target_port}
              onChange={(e) => handleFieldChange('target_port', Number(e.target.value))}
              onBlur={() => validateField('target_port', form.target_port)}
              aria-invalid={!!fieldErrors.target_port}
            />
            {fieldErrors.target_port && <span className="field-error" role="alert">{fieldErrors.target_port}</span>}
          </label>
          <label>
            <span className="label-text">
              Where to Run
              <Tooltip content="Local runner executes tests on this machine. Remote probe runs tests on a worker closer to the target." />
            </span>
            <select
              value={form.execution_mode}
              onChange={(e) => handleFieldChange('execution_mode', e.target.value as 'core' | 'probe')}
            >
              <option value="core">Local runner (recommended)</option>
              <option value="probe">Remote probe</option>
            </select>
          </label>
          <label>
            <span className="label-text">
              Max Tests
              <Tooltip content="Stop the session after this many tests. Leave empty to keep running until you stop it manually." />
            </span>
            <input
                type="number"
                min="1"
                placeholder="Run until stopped"
                value={form.max_iterations}
                onChange={(e) =>
                handleFieldChange('max_iterations', e.target.value ? Number(e.target.value) : '')
                }
                onBlur={() => validateField('max_iterations', form.max_iterations)}
                aria-invalid={!!fieldErrors.max_iterations}
                className={fieldErrors.max_iterations ? 'has-error' : ''}
              />
            {fieldErrors.max_iterations && <span className="field-error" role="alert">{fieldErrors.max_iterations}</span>}
          </label>

          {/* — Advanced section (toggle) — */}
          <div className="advanced-toggle" role="group">
            <button
              type="button"
              className="toggle-btn"
              onClick={() => setShowAdvanced(!showAdvanced)}
              aria-expanded={showAdvanced}
            >
              {showAdvanced ? '▾ Hide' : '▸ Show'} Advanced Options
            </button>
          </div>

          {showAdvanced && (
            <div className="advanced-section">
              <label>
                <span className="label-text">
                  Test Input Strategy
                  <Tooltip content="How aggressively to change packets. Hybrid mixes smart field-aware mutations with random byte changes. Start with Hybrid unless you know what you need." />
                </span>
                <select
                  value={form.mutation_mode}
                  onChange={(e) => handleFieldChange('mutation_mode', e.target.value)}
                >
                  <optgroup label="Random Mutations">
                    <option value="hybrid">Hybrid — smart + random (recommended)</option>
                    <option value="structure_aware">Field-aware — respects message structure</option>
                    <option value="byte_level">Raw bytes — fully random</option>
                  </optgroup>
                  <optgroup label="Systematic Testing">
                    <option value="enumeration">Boundary values — one field at a time</option>
                    <option value="enumeration_pairwise">Pairwise — all field pairs</option>
                    <option value="enumeration_full">Full permutation — all combinations</option>
                  </optgroup>
                </select>
              </label>
              {form.mutation_mode === 'hybrid' && (
                <label>
                  <span className="label-text">
                    Field-Aware vs Random ({form.structure_aware_weight}% / {100 - form.structure_aware_weight}%)
                    <Tooltip content="How much of the mutation should respect field boundaries vs randomly change bytes. Higher = more precise, lower = more chaotic." />
                  </span>
                  <input
                    type="range"
                    min="0"
                    max="100"
                    value={form.structure_aware_weight}
                    onChange={(e) =>
                      handleFieldChange('structure_aware_weight', Number(e.target.value))
                    }
                  />
                </label>
              )}

              {/* Mutator Selection */}
              {['hybrid', 'structure_aware', 'byte_level'].includes(form.mutation_mode) && (
                <>
                  <label className="checkbox-label">
                    <input
                      type="checkbox"
                      checked={form.show_mutator_controls}
                      onChange={(e) => handleFieldChange('show_mutator_controls', e.target.checked)}
                    />
                    <span>
                      Pick specific mutation algorithms
                      <Tooltip content="By default all algorithms are used. Enable this to select exactly which ones to apply." />
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
                                  handleFieldChange('enabled_mutators', newMutators);
                                }}
                              />
                              <span className="mutator-name">{info.name}</span>
                              <Tooltip content={`${info.description}\n\nExample: ${info.example}`} />
                            </label>
                          );
                        })}
                      </div>
                      {form.enabled_mutators.length === 0 && (
                        <div className="warning-text">At least one algorithm must be enabled</div>
                      )}
                    </div>
                  )}
                </>
              )}

              {/* Mode-specific info boxes */}
              {form.mutation_mode === 'hybrid' && (
                <div className="info-box">
                  <strong>Hybrid:</strong> Combines field-aware ({form.structure_aware_weight}%) with random byte ({100 - form.structure_aware_weight}%) mutations. Best for general exploration.
                </div>
              )}
              {form.mutation_mode === 'structure_aware' && (
                <div className="info-box">
                  <strong>Field-Aware:</strong> Mutations respect message field boundaries and only change mutable fields. Good for testing specific protocol logic.
                </div>
              )}
              {form.mutation_mode.startsWith('enumeration') && (
                <div className="info-box">
                  <strong>Systematic:</strong> Tests boundary values (0, 1, max-1, max) for each field.
                  {form.mutation_mode === 'enumeration' && ' One field at a time — fast and focused.'}
                  {form.mutation_mode === 'enumeration_pairwise' && ' All field pairs — good coverage without explosion.'}
                  {form.mutation_mode === 'enumeration_full' && ' All combinations — thorough but can be very large!'}
                  {' '}Switches to random mutation after all boundary values are tested.
                </div>
              )}

              <label className={fieldErrors.rate_limit_per_second ? 'has-error' : ''}>
                <span className="label-text">
                  Speed Limit (tests/sec)
                  <Tooltip content="Slow down testing to avoid overwhelming the target. Leave empty for maximum speed." />
                </span>
                <input
                    type="number"
                    min="1"
                    placeholder="Full speed"
                    value={form.rate_limit_per_second}
                    onChange={(e) =>
                    handleFieldChange('rate_limit_per_second', e.target.value ? Number(e.target.value) : '')
                    }
                    onBlur={() => validateField('rate_limit_per_second', form.rate_limit_per_second)}
                  />
                {fieldErrors.rate_limit_per_second && <span className="field-error" role="alert">{fieldErrors.rate_limit_per_second}</span>}
              </label>
              <label className={fieldErrors.timeout_per_test_ms ? 'has-error' : ''}>
                <span className="label-text">
                  Response Timeout (ms)
                  <Tooltip content="How long to wait for the target to respond before marking a test as a timeout. Increase for slow targets." />
                </span>
                <input
                    type="number"
                    min="100"
                    value={form.timeout_per_test_ms}
                  onChange={(e) => handleFieldChange('timeout_per_test_ms', Number(e.target.value))}
                  onBlur={() => validateField('timeout_per_test_ms', form.timeout_per_test_ms)}
                  aria-invalid={!!fieldErrors.timeout_per_test_ms}
                />
                {fieldErrors.timeout_per_test_ms && <span className="field-error" role="alert">{fieldErrors.timeout_per_test_ms}</span>}
              </label>

              <label>
                <span className="label-text">
                  Exploration Goal
                  <Tooltip content="Random: explore broadly. Breadth-first: visit all protocol states evenly. Depth-first: follow paths deeply. Targeted: focus on one state." />
                </span>
                <select
                  value={form.fuzzing_mode}
                  onChange={(e) => handleFieldChange('fuzzing_mode', e.target.value)}
                >
                  <option value="random">Broad exploration (recommended)</option>
                  <option value="breadth_first">Even coverage — visit all states equally</option>
                  <option value="depth_first">Deep paths — follow transitions deeply</option>
                  <option value="targeted">Focus on one state</option>
                </select>
              </label>

              {form.fuzzing_mode === 'targeted' && (
                <label>
                  <span className="label-text">
                    Target State
                    <Tooltip content="The specific protocol state to concentrate testing on. The fuzzer will navigate there and focus mutations." />
                  </span>
                  <select
                    value={form.target_state}
                    onChange={(e) => handleFieldChange('target_state', e.target.value)}
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
                  State Reset Interval
                  <Tooltip content="Reset the protocol state machine every N tests. Useful to repeatedly test setup/teardown and avoid getting stuck." />
                </span>
                <input
                  type="number"
                  min="1"
                  placeholder="No reset"
                  value={form.session_reset_interval}
                  onChange={(e) =>
                    handleFieldChange('session_reset_interval', e.target.value ? Number(e.target.value) : '')
                  }
                />
              </label>

              <label className="checkbox-label">
                <input
                  type="checkbox"
                  checked={form.enable_termination_fuzzing}
                  onChange={(e) => handleFieldChange('enable_termination_fuzzing', e.target.checked)}
                />
                <span className="label-text">
                  Test teardown paths
                  <Tooltip content="Periodically trigger close/disconnect transitions to test how the target handles session cleanup." />
                </span>
              </label>
            </div>
          )}

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
          <div className="empty-state-cta">
            <h3>No sessions yet</h3>
            <p>Create your first fuzzing session above to start finding bugs, or try the sample target to see the framework in action.</p>
            <div className="empty-state-actions">
              <button onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
                Create First Session
              </button>
              <Link className="ghost-link" to="/guides">
                Read the Getting Started Guide
              </Link>
            </div>
          </div>
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
                          aria-expanded={isExpanded}
                          aria-label={isExpanded ? 'Collapse session details' : 'Expand session details'}
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
