import { FormEvent, useEffect, useReducer, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import StatusBadge from '../components/StatusBadge';
import Toast, { ToastVariant } from '../components/Toast';
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
}

type FormAction =
  | { type: 'set_field'; field: keyof CreateSessionForm; value: any }
  | { type: 'reset'; payload?: Partial<CreateSessionForm> };

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
  const [protocols, setProtocols] = useState<string[]>([]);
  const [sessions, setSessions] = useState<FuzzSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [toast, setToast] = useState<{ variant: ToastVariant; message: string } | null>(null);
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [form, dispatch] = useReducer(formReducer, initialForm);
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
      } as Record<string, unknown>;

      if (form.rate_limit_per_second !== '') {
        payload.rate_limit_per_second = Number(form.rate_limit_per_second);
      }
      if (form.max_iterations !== '') {
        payload.max_iterations = Number(form.max_iterations);
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
            Protocol
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
            Target Host
              <input
                value={form.target_host}
              onChange={(e) => dispatch({ type: 'set_field', field: 'target_host', value: e.target.value })}
            />
          </label>
          <label>
            Target Port
              <input
                type="number"
                value={form.target_port}
              onChange={(e) => dispatch({ type: 'set_field', field: 'target_port', value: Number(e.target.value) })}
            />
          </label>
          <label>
            Execution Mode
            <select
              value={form.execution_mode}
              onChange={(e) => dispatch({ type: 'set_field', field: 'execution_mode', value: e.target.value as 'core' | 'agent' })}
            >
              <option value="core">Core</option>
              <option value="agent">Agent</option>
            </select>
          </label>
          <label>
            Mutation Strategy
            <select
              value={form.mutation_mode}
              onChange={(e) => dispatch({ type: 'set_field', field: 'mutation_mode', value: e.target.value })}
            >
              <option value="hybrid">Hybrid</option>
              <option value="structure_aware">Structure-Aware</option>
              <option value="byte_level">Byte-Level</option>
            </select>
          </label>
          {form.mutation_mode === 'hybrid' && (
            <label>
              Structure-Aware Weight ({form.structure_aware_weight}%)
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
          <label>
            Rate Limit (tests/sec)
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
            Max Iterations
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
            Timeout per Test (ms)
              <input
                type="number"
                min="100"
                value={form.timeout_per_test_ms}
              onChange={(e) => dispatch({ type: 'set_field', field: 'timeout_per_test_ms', value: Number(e.target.value) })}
            />
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
            <span className="hint">Last refreshed {lastUpdated || '—'}</span>
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
                <th>ID</th>
                <th>Protocol</th>
                <th>Status</th>
                <th>Target</th>
                <th>Stats</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sessions.map((session) => (
                <tr key={session.id}>
                  <td>
                    <Link className="session-link" to={`/correlation?session=${encodeURIComponent(session.id)}`}>
                      {session.id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td>{session.protocol}</td>
                  <td>
                    <StatusBadge value={session.status} />
                  </td>
                  <td>
                    {session.target_host}:{session.target_port}
                  </td>
                  <td>
                    {session.total_tests} tests · {session.crashes} crashes
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
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default DashboardPage;
