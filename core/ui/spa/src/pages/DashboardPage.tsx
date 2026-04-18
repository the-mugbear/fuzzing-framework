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
  target_host: '',
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
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set());
  const [showCreateForm, setShowCreateForm] = useState(false);
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

    // Auto-fill target host/port from running Target Manager targets
    const tmBase = import.meta.env.VITE_TARGET_MANAGER_URL ?? 'http://localhost:8001';
    fetch(`${tmBase}/api/targets`)
      .then((r) => (r.ok ? r.json() : []))
      .then((targets: Array<{ script: string; port: number; compatible_plugins: string[] }>) => {
        const match = targets.find((t) => t.compatible_plugins.includes(form.protocol));
        if (match) {
          dispatch({ type: 'set_field', field: 'target_host', value: 'target-manager' });
          dispatch({ type: 'set_field', field: 'target_port', value: match.port });
        }
      })
      .catch(() => { /* Target Manager not available — ignore */ });
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
      setSelectedSessions(prev => { const next = new Set(prev); next.delete(id); return next; });
      refreshSessions();
    } catch (err) {
      setToast({ variant: 'error', message: `Delete failed: ${(err as Error).message}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const handleBulkDelete = async () => {
    const ids = Array.from(selectedSessions);
    if (ids.length === 0) return;
    const runningSelected = sessions.filter(s => ids.includes(s.id) && s.status === 'RUNNING').length;
    const msg = runningSelected > 0
      ? `Delete ${ids.length} session(s)? ${runningSelected} running session(s) will be stopped first. This cannot be undone.`
      : `Delete ${ids.length} session(s)? This cannot be undone.`;
    if (!window.confirm(msg)) return;

    setActionInProgress('bulk');
    try {
      const result = await api<{ deleted: string[]; failed: string[] }>('/api/sessions/bulk-delete', {
        method: 'POST',
        body: JSON.stringify({ session_ids: ids }),
      });
      setSelectedSessions(new Set());
      const count = result.deleted.length;
      const failCount = result.failed.length;
      if (failCount > 0) {
        setToast({ variant: 'error', message: `Deleted ${count}, failed ${failCount}.` });
      } else {
        setToast({ variant: 'success', message: `Deleted ${count} session(s).` });
      }
      refreshSessions();
    } catch (err) {
      setToast({ variant: 'error', message: `Bulk delete failed: ${(err as Error).message}` });
    } finally {
      setActionInProgress(null);
    }
  };

  const toggleSessionSelection = (id: string) => {
    setSelectedSessions(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedSessions.size === sessions.length) {
      setSelectedSessions(new Set());
    } else {
      setSelectedSessions(new Set(sessions.map(s => s.id)));
    }
  };

  const handleOpenGraph = (id: string) => {
    navigate(`/state-graph?session=${encodeURIComponent(id)}`);
  };

  const runningSessions = sessions.filter((session) => session.status === 'RUNNING').length;
  const totalTests = sessions.reduce((acc, session) => acc + (session.total_tests || 0), 0);
  const totalCrashes = sessions.reduce((acc, session) => acc + (session.crashes || 0), 0);
  const totalHangs = sessions.reduce((acc, session) => acc + (session.hangs || 0), 0);

  return (
    <div className="dashboard-page" id="main-content">
      {/* ── Page Header ── */}
      <div className="page-header">
        <h1>Dashboard</h1>
        <div className="page-header-actions">
          <span className="hint">Updated {lastUpdated || '—'}</span>
          <button onClick={refreshSessions} disabled={loading} className="btn-ghost">
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* ── Stats Bar ── */}
      <div className="stats-bar">
        <div className="stat-card">
          <span className="stat-label">Sessions</span>
          <span className="stat-value accent">{sessions.length}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Running</span>
          <span className="stat-value">{runningSessions}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Total Tests</span>
          <span className="stat-value">{totalTests.toLocaleString()}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Crashes</span>
          <span className={`stat-value${totalCrashes > 0 ? ' error' : ''}`}>{totalCrashes}</span>
        </div>
        <div className="stat-card">
          <span className="stat-label">Hangs</span>
          <span className="stat-value">{totalHangs}</span>
        </div>
      </div>

      {/* ── Sessions Section (primary) ── */}
      <section className="sessions-section">
        <div className="sessions-header">
          <h2>Fuzzing Sessions</h2>
          <div className="sessions-toolbar">
            {selectedSessions.size > 0 && (
              <button
                className="btn-danger"
                onClick={handleBulkDelete}
                disabled={actionInProgress === 'bulk'}
              >
                {actionInProgress === 'bulk' ? 'Deleting…' : `Delete ${selectedSessions.size} selected`}
              </button>
            )}
            <button className="btn-primary" onClick={() => setShowCreateForm(v => !v)}>
              + New Session
            </button>
          </div>
        </div>
        {sessions.length === 0 ? (
          <div className="empty-state">
            <h3>No fuzzing sessions yet</h3>
            <p>
              Create a session to start testing your protocol implementation.
              The fuzzer will send mutated packets and report crashes, hangs, and anomalies.
            </p>
            <div className="empty-state-actions">
              <button className="btn-primary" onClick={() => setShowCreateForm(true)}>
                Create First Session
              </button>
              <Link className="ghost-link" to="/guides">
                Read the docs
              </Link>
            </div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="session-table">
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={sessions.length > 0 && selectedSessions.size === sessions.length}
                      onChange={toggleSelectAll}
                      aria-label="Select all sessions"
                    />
                  </th>
                  <th></th>
                  <th>ID</th>
                  <th>Protocol</th>
                  <th>Status</th>
                  <th>Target</th>
                  <th>Results</th>
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
                          <input
                            type="checkbox"
                            checked={selectedSessions.has(session.id)}
                            onChange={() => toggleSessionSelection(session.id)}
                            aria-label={`Select session ${session.id.slice(0, 8)}`}
                          />
                        </td>
                        <td>
                          <button
                            className="expand-btn"
                            onClick={() => setExpandedSession(isExpanded ? null : session.id)}
                            aria-expanded={isExpanded}
                            aria-label={isExpanded ? 'Collapse details' : 'Expand details'}
                          >
                            {isExpanded ? '▼' : '▶'}
                          </button>
                        </td>
                        <td>
                          <Link className="session-link" to={`/correlation?session=${encodeURIComponent(session.id)}`}>
                            {session.id.slice(0, 8)}
                          </Link>
                        </td>
                        <td>{session.protocol}</td>
                        <td>
                          <StatusBadge value={session.status} />
                          {session.current_state && (
                            <div style={{ fontSize: '0.8em', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                              {session.current_state}
                            </div>
                          )}
                          <div className="health-indicators">
                            {session.connection_mode && session.connection_mode !== 'per_test' && (
                              <span className="health-badge conn" title={`Connection: ${session.connection_mode}`}>⚡</span>
                            )}
                            {session.heartbeat_enabled && (
                              <span
                                className={`health-badge hb ${session.heartbeat_failures && session.heartbeat_failures > 0 ? 'warn' : ''}`}
                                title={`Heartbeat: ${session.heartbeat_failures || 0} failures`}
                              >❤️</span>
                            )}
                          </div>
                        </td>
                        <td>
                          {session.target_host}:{session.target_port}
                          {session.target_state && (
                            <div style={{ fontSize: '0.8em', color: 'var(--text-tertiary)', marginTop: '2px' }}>
                              → {session.target_state}
                            </div>
                          )}
                        </td>
                        <td>
                          <div>{session.total_tests.toLocaleString()} tests</div>
                          <div style={{ fontSize: '0.8em', marginTop: '2px' }}>
                            <span style={{ color: session.crashes > 0 ? 'var(--color-error)' : 'var(--text-tertiary)' }}>
                              {session.crashes} crash{session.crashes !== 1 ? 'es' : ''}
                            </span>
                            {session.hangs > 0 && (
                              <span style={{ color: 'var(--color-warning-text)', marginLeft: '8px' }}>
                                {session.hangs} hang{session.hangs !== 1 ? 's' : ''}
                              </span>
                            )}
                          </div>
                          {hasCoverage && (
                            <div style={{ fontSize: '0.8em', color: 'var(--accent-color)', marginTop: '2px' }}>
                              {visitedStates}/{totalStates} states ({coveragePct}%)
                            </div>
                          )}
                        </td>
                        <td>
                          <div className="session-actions">
                            {session.status === 'RUNNING' ? (
                              <button
                                onClick={() => handleStop(session.id)}
                                className="btn-ghost"
                                disabled={actionInProgress === session.id}
                              >
                                {actionInProgress === session.id ? '…' : 'Stop'}
                              </button>
                            ) : (
                              <button
                                onClick={() => handleStart(session.id)}
                                disabled={actionInProgress === session.id}
                              >
                                {actionInProgress === session.id ? '…' : 'Start'}
                              </button>
                            )}
                            <button
                              onClick={() => handleDelete(session.id)}
                              className="btn-danger"
                              disabled={actionInProgress === session.id}
                              title="Delete session"
                            >
                              Del
                            </button>
                            {hasCoverage && (
                              <button
                                type="button"
                                className="btn-ghost"
                                title="View State Graph"
                                onClick={() => handleOpenGraph(session.id)}
                              >
                                Graph
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                      {isExpanded && (
                        <tr className="detail-row">
                          <td colSpan={8}>
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
          </div>
        )}
      </section>

      {/* ── Create Session (collapsible) ── */}
      <section className="create-section">
        <div
          className="create-header"
          onClick={() => setShowCreateForm(v => !v)}
          role="button"
          tabIndex={0}
          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setShowCreateForm(v => !v); } }}
          aria-expanded={showCreateForm}
        >
          <h2>New Fuzzing Session</h2>
          <span className="toggle-indicator">{showCreateForm ? '▾ Collapse' : '▸ Expand'}</span>
        </div>
        {showCreateForm && (
          <form className="session-form" onSubmit={handleCreate}>
            {/* — Essential fields — */}
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
                {protocols.length === 0 && <option>Loading…</option>}
                {protocols.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
              {fieldErrors.protocol && <span className="field-error" role="alert">{fieldErrors.protocol}</span>}
            </label>
            <label className={fieldErrors.target_host ? 'has-error' : ''}>
              <span className="label-text">
                Target Host
                <Tooltip content="Where is the target running? Use 'target-manager' for Docker, 'localhost' for local, or an IP address." />
              </span>
              <input
                value={form.target_host}
                onChange={(e) => handleFieldChange('target_host', e.target.value)}
                onBlur={() => validateField('target_host', form.target_host)}
                placeholder="e.g. localhost or target-manager"
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
                Execution Mode
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
                    Mutation Strategy
                    <Tooltip content="How aggressively to change packets. Hybrid mixes smart field-aware mutations with random byte changes." />
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
                      <Tooltip content="How much of the mutation should respect field boundaries vs randomly change bytes." />
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
                    <Tooltip content="How long to wait for the target to respond before marking a test as a timeout." />
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
                      <Tooltip content="The specific protocol state to concentrate testing on." />
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
                        <option key={state} value={state}>{state}</option>
                      ))}
                    </select>
                  </label>
                )}

                <label>
                  <span className="label-text">
                    State Reset Interval
                    <Tooltip content="Reset the protocol state machine every N tests. Useful to test setup/teardown and avoid getting stuck." />
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

            <button type="submit" className="btn-primary">Create Session</button>
          </form>
        )}
      </section>

      {toast && <Toast message={toast.message} variant={toast.variant} onClose={() => setToast(null)} />}
    </div>
  );
}

export default DashboardPage;
