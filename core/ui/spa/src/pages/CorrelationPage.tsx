import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import StatusBadge from '../components/StatusBadge';
import Modal from '../components/Modal';
import { api } from '../services/api';
import './CorrelationPage.css';

interface FuzzSessionSummary {
  id: string;
  protocol: string;
  target_host: string;
  target_port: number;
  status: string;
  timeout_per_test_ms: number;
  rate_limit_per_second?: number | null;
  transport: string;
  execution_mode: string;
  enabled_mutators: string[];
  fuzzing_mode?: string | null;
}

interface TestCaseExecutionRecord {
  test_case_id: string;
  sequence_number: number;
  timestamp_sent: string;
  timestamp_response?: string | null;
  duration_ms: number;
  message_type?: string;
  state_at_send?: string;
  result: string;
  payload_preview: string;
  response_preview?: string | null;
  raw_payload_b64: string;
  mutation_strategy?: string | null;
  mutators_applied?: string[];
}

interface ExecutionHistoryResponse {
  session_id: string;
  total_count: number;
  returned_count: number;
  executions: TestCaseExecutionRecord[];
}

interface ReplayResponse {
  replayed_count: number;
  results: TestCaseExecutionRecord[];
}

interface SessionStatsResponse {
  session_id: string;
  status: string;
  total_tests: number;
  crashes: number;
  hangs: number;
  anomalies: number;
  findings_count: number;
  runtime_seconds: number;
  state_coverage?: StateCoverageStats;
}

interface StateCoverageStats {
  current_state?: string;
  state_coverage?: Record<string, number>;
  transition_coverage?: Record<string, number>;
  states_visited?: number;
  states_total?: number;
  state_coverage_pct?: number;
  transitions_taken?: number;
  transitions_total?: number;
  transition_coverage_pct?: number;
  total_transitions_executed?: number;
}

function CorrelationPage() {
  const location = useLocation();
  const [sessions, setSessions] = useState<FuzzSessionSummary[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [history, setHistory] = useState<ExecutionHistoryResponse | null>(null);
  const [selectedExecution, setSelectedExecution] = useState<TestCaseExecutionRecord | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeQuery, setTimeQuery] = useState('');
  const [sequenceQuery, setSequenceQuery] = useState('');
  const [rangeStart, setRangeStart] = useState('');
  const [rangeEnd, setRangeEnd] = useState('');
  const [rangeDelay, setRangeDelay] = useState(250);
  const [timeSuggestions, setTimeSuggestions] = useState<string[]>([]);
  const [replayLog, setReplayLog] = useState<string[]>([]);
  const [sequenceRangeStart, setSequenceRangeStart] = useState('');
  const [sequenceRangeEnd, setSequenceRangeEnd] = useState('');
  const [stats, setStats] = useState<SessionStatsResponse | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [coverage, setCoverage] = useState<StateCoverageStats | null>(null);
  const [coverageError, setCoverageError] = useState<string | null>(null);
  const [reportPending, setReportPending] = useState(false);

  const fetchCoverage = useCallback(() => {
    if (!selectedSessionId) {
      setCoverage(null);
      return;
    }
    api<StateCoverageStats>(`/api/sessions/${selectedSessionId}/state_coverage`)
      .then((data) => {
        setCoverage(data);
        setCoverageError(null);
      })
      .catch((err) => {
        const msg = (err as Error).message;
        if (msg.toLowerCase().includes('stateful')) {
          setCoverage(null);
          setCoverageError(null);
        } else {
          setCoverage(null);
          setCoverageError(msg);
        }
      });
  }, [selectedSessionId]);

  useEffect(() => {
    api<FuzzSessionSummary[]>('/api/sessions')
      .then((data) => {
        setSessions(data);
        if (!selectedSessionId) {
          const params = new URLSearchParams(location.search);
          const requested = params.get('session');
          if (requested && data.some((session) => session.id === requested)) {
            setSelectedSessionId(requested);
          } else if (data.length) {
            setSelectedSessionId(data[0].id);
          }
        }
      })
      .catch((err) => setError(err.message));
  }, [location.search, selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId) {
      setStats(null);
      return;
    }
    api<SessionStatsResponse>(`/api/sessions/${selectedSessionId}/stats`)
      .then((data) => {
        setStats(data);
        setStatsError(null);
      })
      .catch((err) => {
        setStats(null);
        setStatsError((err as Error).message);
      });
  }, [selectedSessionId]);

  useEffect(() => {
    fetchCoverage();
  }, [fetchCoverage]);

  const selectedSession = useMemo(() => sessions.find((s) => s.id === selectedSessionId), [sessions, selectedSessionId]);

  const mutationInsights = useMemo(() => {
    if (!history || history.executions.length === 0) {
      return null;
    }
    const verdicts: Record<string, number> = {};
    const mutatorMap = new Map<string, { total: number; crashes: number; hangs: number; states: Set<string> }>();
    const recentStates = new Set<string>();

    history.executions.forEach((execution) => {
      verdicts[execution.result] = (verdicts[execution.result] || 0) + 1;
      if (execution.state_at_send) {
        recentStates.add(execution.state_at_send);
      }
      const applied = execution.mutators_applied && execution.mutators_applied.length > 0 ? execution.mutators_applied : ['untracked'];
      applied.forEach((mutatorName) => {
        const existing = mutatorMap.get(mutatorName) || {
          total: 0,
          crashes: 0,
          hangs: 0,
          states: new Set<string>(),
        };
        existing.total += 1;
        if (execution.result === 'crash') {
          existing.crashes += 1;
        }
        if (execution.result === 'hang') {
          existing.hangs += 1;
        }
        if (execution.state_at_send) {
          existing.states.add(execution.state_at_send);
        }
        mutatorMap.set(mutatorName, existing);
      });
    });

    const mutatorRows = Array.from(mutatorMap.entries())
      .map(([name, entry]) => ({
        name,
        total: entry.total,
        crashes: entry.crashes,
        hangs: entry.hangs,
        states: entry.states.size,
      }))
      .sort((a, b) => {
        if (b.crashes !== a.crashes) return b.crashes - a.crashes;
        if (b.total !== a.total) return b.total - a.total;
        return a.name.localeCompare(b.name);
      })
      .slice(0, 4);

    return {
      verdicts,
      mutators: mutatorRows,
      recentStates: recentStates.size,
    };
  }, [history]);

  const stateCoverageEntries = useMemo(() => {
    if (!coverage?.state_coverage) {
      return [];
    }
    return Object.entries(coverage.state_coverage).sort((a, b) => {
      if (b[1] !== a[1]) return b[1] - a[1];
      return a[0].localeCompare(b[0]);
    });
  }, [coverage]);

  const transitionEntries = useMemo(() => {
    if (!coverage?.transition_coverage) {
      return [];
    }
    return Object.entries(coverage.transition_coverage)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6);
  }, [coverage]);

  const formatRuntime = (seconds: number) => {
    if (!seconds) return '—';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = Math.floor(seconds % 60);
    if (hrs > 0) {
      return `${hrs}h ${mins}m`;
    }
    if (mins > 0) {
      return `${mins}m ${secs}s`;
    }
    return `${secs}s`;
  };

  const formatResultLabel = (label: string) =>
    label
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (match) => match.toUpperCase());

  useEffect(() => {
    if (!selectedSessionId) {
      return;
    }
    fetchHistory();
  }, [selectedSessionId]);

  useEffect(() => {
    if (!selectedSessionId || selectedSession?.status !== 'RUNNING') {
      return;
    }
    const id = window.setInterval(fetchHistory, 5000);
    return () => window.clearInterval(id);
  }, [selectedSessionId, selectedSession?.status]);

  const fetchHistory = () => {
    if (!selectedSessionId) {
      return;
    }
    setLoadingHistory(true);
    api<ExecutionHistoryResponse>(`/api/sessions/${selectedSessionId}/execution_history?limit=50`)
      .then((data) => {
        setHistory(data);
        if (data.executions.length) {
          const timestamps = data.executions
            .slice(0, 5)
            .map((execution) => execution.timestamp_sent);
          setTimeSuggestions(timestamps);
          if (!timeQuery) {
            setTimeQuery(timestamps[0]?.slice(0, 19) ?? '');
          }
          setRangeStart(timestamps[timestamps.length - 1]?.slice(0, 19) ?? '');
          setRangeEnd(timestamps[0]?.slice(0, 19) ?? '');
        } else {
          setTimeSuggestions([]);
        }
        setError(null);
        fetchCoverage();
      })
      .catch((err) => {
        setError(err.message);
        setHistory(null);
      })
      .finally(() => setLoadingHistory(false));
  };

  const handleSequenceRangeReplay = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedSessionId) {
      return;
    }
    const start = Number(sequenceRangeStart);
    const end = Number(sequenceRangeEnd);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start <= 0 || end <= 0 || end < start) {
      setReplayLog((prev) => ['Invalid sequence range', ...prev]);
      return;
    }
    const sequenceNumbers = Array.from({ length: end - start + 1 }, (_, idx) => start + idx);
    try {
      await api<ReplayResponse>(`/api/sessions/${selectedSessionId}/execution/replay`, {
        method: 'POST',
        body: JSON.stringify({ sequence_numbers: sequenceNumbers, delay_ms: Math.max(rangeDelay, 0) }),
      });
      setReplayLog((prev) => [`Replaying sequences ${sequenceNumbers.join(', ')}`, ...prev]);
    } catch (err) {
      setReplayLog((prev) => [`Sequence range replay failed: ${(err as Error).message}`, ...prev]);
    }
  };

  const handleTimelineSelect = (execution: TestCaseExecutionRecord) => {
    setSelectedExecution(execution);
  };

  const handleSequenceSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!sequenceQuery || !selectedSessionId) {
      return;
    }
    try {
      const execution = await api<TestCaseExecutionRecord>(
        `/api/sessions/${selectedSessionId}/execution/${sequenceQuery}`,
      );
      setSelectedExecution(execution);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleTimeSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!timeQuery || !selectedSessionId) {
      return;
    }
    try {
      const iso = new Date(timeQuery).toISOString();
      const execution = await api<TestCaseExecutionRecord>(
        `/api/sessions/${selectedSessionId}/execution/at_time?timestamp=${encodeURIComponent(iso)}`,
      );
      setSelectedExecution(execution);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleReplaySingle = async () => {
    if (!selectedSessionId || !selectedExecution) {
      return;
    }
    try {
      const response = await api<ReplayResponse>(`/api/sessions/${selectedSessionId}/execution/replay`, {
        method: 'POST',
        body: JSON.stringify({ sequence_numbers: [selectedExecution.sequence_number], delay_ms: 0 }),
      });
      setReplayLog((prev) => [
        `Replayed sequence ${selectedExecution.sequence_number} (${response.replayed_count} results)`,
        ...prev,
      ]);
    } catch (err) {
      setReplayLog((prev) => [`Replay failed: ${(err as Error).message}`, ...prev]);
    }
  };

  const handleDownloadReport = async () => {
    if (!selectedSessionId) {
      return;
    }
    setReportPending(true);
    try {
      const [statsPayload, historyPayload, coveragePayload] = await Promise.all([
        api<SessionStatsResponse>(`/api/sessions/${selectedSessionId}/stats`),
        api<ExecutionHistoryResponse>(`/api/sessions/${selectedSessionId}/execution_history?limit=500`),
        api<StateCoverageStats>(`/api/sessions/${selectedSessionId}/state_coverage`).catch(() => null),
      ]);
      const report = {
        generated_at: new Date().toISOString(),
        session: selectedSession,
        stats: statsPayload,
        coverage: coveragePayload,
        executions: historyPayload.executions,
      };
      const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `session-${selectedSessionId.slice(0, 8)}-report.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setReplayLog((prev) => [`Exported session report (${historyPayload.executions.length} executions)`, ...prev]);
    } catch (err) {
      setReplayLog((prev) => [`Report export failed: ${(err as Error).message}`, ...prev]);
    } finally {
      setReportPending(false);
    }
  };

  const handleRangeReplay = async (event: FormEvent) => {
    event.preventDefault();
    if (!rangeStart || !rangeEnd || !selectedSessionId) {
      return;
    }
    const startIso = new Date(rangeStart).toISOString();
    const endIso = new Date(rangeEnd).toISOString();
    try {
      const data = await api<ExecutionHistoryResponse>(
        `/api/sessions/${selectedSessionId}/execution_history?limit=500&since=${encodeURIComponent(startIso)}&until=${encodeURIComponent(endIso)}`,
      );
      const seqs = data.executions.map((execution) => execution.sequence_number);
      if (!seqs.length) {
        setReplayLog((prev) => ['No executions in selected window.', ...prev]);
        return;
      }
      await api<ReplayResponse>(`/api/sessions/${selectedSessionId}/execution/replay`, {
        method: 'POST',
        body: JSON.stringify({ sequence_numbers: seqs, delay_ms: Math.max(rangeDelay, 0) }),
      });
      setReplayLog((prev) => [`Replaying sequences ${seqs.join(', ')}`, ...prev]);
    } catch (err) {
      setReplayLog((prev) => [`Range replay failed: ${(err as Error).message}`, ...prev]);
    }
  };

  return (
    <div className="card correlation-card">
      <div className="correlation-header">
        <div>
          <p className="eyebrow">Correlation & Replay</p>
          <h2>Execution History</h2>
          <p>Locate interesting test cases by time or sequence, inspect payloads, and replay them against the target.</p>
        </div>
        <div className="session-picker">
          <select value={selectedSessionId} onChange={(e) => setSelectedSessionId(e.target.value)}>
            {sessions.map((session) => (
              <option key={session.id} value={session.id}>
                {session.protocol} · {session.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <button type="button" onClick={fetchHistory} disabled={loadingHistory}>
            {loadingHistory ? 'Loading…' : 'Refresh'}
          </button>
          <button type="button" className="ghost" onClick={handleDownloadReport} disabled={reportPending}>
            {reportPending ? 'Building…' : 'Export Report'}
          </button>
        </div>
      </div>

      {selectedSession && (
        <div className="session-config-card">
          <div className="config-section">
            <h3>Target Configuration</h3>
            <div className="config-row">
              <div className="config-item">
                <span>Protocol</span>
                <strong>{selectedSession.protocol}</strong>
              </div>
              <div className="config-item">
                <span>Target</span>
                <strong>{selectedSession.target_host}:{selectedSession.target_port}</strong>
              </div>
              <div className="config-item">
                <span>Transport</span>
                <strong>{selectedSession.transport.toUpperCase()}</strong>
              </div>
              <div className="config-item">
                <span>Status</span>
                <StatusBadge value={selectedSession.status} />
              </div>
            </div>
          </div>

          <div className="config-section">
            <h3>Fuzzing Configuration</h3>
            <div className="config-row">
              <div className="config-item">
                <span>Execution Mode</span>
                <strong>{selectedSession.execution_mode}</strong>
              </div>
              <div className="config-item">
                <span>Timeout</span>
                <strong>{selectedSession.timeout_per_test_ms} ms</strong>
              </div>
              {selectedSession.rate_limit_per_second && (
                <div className="config-item">
                  <span>Rate Limit</span>
                  <strong>{selectedSession.rate_limit_per_second}/sec</strong>
                </div>
              )}
              {selectedSession.fuzzing_mode && (
                <div className="config-item">
                  <span>Fuzzing Mode</span>
                  <strong>{selectedSession.fuzzing_mode}</strong>
                </div>
              )}
            </div>
            <div className="config-item config-item-full">
              <span>Enabled Mutators</span>
              <div className="mutator-tags">
                {selectedSession.enabled_mutators.map((mutator) => (
                  <span key={mutator} className="mutator-tag">{mutator}</span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}

      {statsError && <p className="error insights-error">{statsError}</p>}

      {stats && (
        <div className="session-kpis">
          <div>
            <span>Total Tests</span>
            <strong>{stats.total_tests.toLocaleString()}</strong>
          </div>
          <div>
            <span>Crashes</span>
            <strong>{stats.crashes.toLocaleString()}</strong>
          </div>
          <div>
            <span>Hangs</span>
            <strong>{stats.hangs.toLocaleString()}</strong>
          </div>
          <div>
            <span>Anomalies</span>
            <strong>{stats.anomalies.toLocaleString()}</strong>
          </div>
          <div>
            <span>Findings</span>
            <strong>{stats.findings_count.toLocaleString()}</strong>
          </div>
          <div>
            <span>Runtime</span>
            <strong>{formatRuntime(stats.runtime_seconds)}</strong>
          </div>
        </div>
      )}

      {(coverage || mutationInsights) && (
        <div className="insights-grid">
          {coverage && (
            <section className="insight-card">
              <header>
                <p className="eyebrow">State Coverage</p>
                <h3>State machine progress</h3>
                {coverage.current_state && <p>Current state: {coverage.current_state}</p>}
              </header>
              <div className="coverage-stats">
                <div>
                  <span>States</span>
                  <strong>
                    {coverage.states_visited ?? 0}/{coverage.states_total ?? 0}
                  </strong>
                  <small>{Math.round(coverage.state_coverage_pct || 0)}% covered</small>
                </div>
                <div>
                  <span>Transitions</span>
                  <strong>
                    {coverage.transitions_taken ?? 0}/{coverage.transitions_total ?? 0}
                  </strong>
                  <small>{Math.round(coverage.transition_coverage_pct || 0)}% exercised</small>
                </div>
                <div>
                  <span>Total Transitions</span>
                  <strong>{coverage.total_transitions_executed ?? 0}</strong>
                  <small>Across current session</small>
                </div>
              </div>
              {stateCoverageEntries.length > 0 && (
                <div>
                  <p className="state-list-title">States hit (last snapshot)</p>
                  <ul className="state-coverage-list">
                    {stateCoverageEntries.map(([state, count]) => (
                      <li key={state} className={count === 0 ? 'muted' : ''}>
                        <span>{state}</span>
                        <strong>{count}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {transitionEntries.length > 0 && (
                <div className="transition-coverage">
                  <p className="state-list-title">Top transitions</p>
                  <ul>
                    {transitionEntries.map(([transition, count]) => (
                      <li key={transition}>
                        <span>{transition}</span>
                        <strong>{count}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {mutationInsights && (
            <section className="insight-card">
              <header>
                <p className="eyebrow">Mutation Insights</p>
                <h3>Recent efficacy</h3>
                <p>Last {history?.returned_count ?? 0} executions touched {mutationInsights.recentStates} states.</p>
              </header>
              <div className="verdict-grid">
                {Object.entries(mutationInsights.verdicts).map(([result, count]) => (
                  <div key={result}>
                    <span>{formatResultLabel(result)}</span>
                    <strong>{count}</strong>
                  </div>
                ))}
              </div>
              {mutationInsights.mutators.length > 0 && (
                <div>
                  <p className="state-list-title">Top mutators</p>
                  <ul className="mutator-insight-list">
                    {mutationInsights.mutators.map((mutator) => (
                      <li key={mutator.name}>
                        <div>
                          <strong>{mutator.name}</strong>
                          <small>{mutator.total} executions</small>
                        </div>
                        <div className="mutator-meta">
                          <span>Crashes {mutator.crashes}</span>
                          <span>Hangs {mutator.hangs}</span>
                          <span>States {mutator.states}</span>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}
        </div>
      )}

      {coverageError && <p className="error insights-error">{coverageError}</p>}

      <div className="search-grid">
        <form onSubmit={handleSequenceSearch}>
          <label>
            Sequence #
            <input value={sequenceQuery} onChange={(e) => setSequenceQuery(e.target.value)} placeholder="e.g., 847" />
          </label>
          <button type="submit">Find Test Case</button>
        </form>
        <form onSubmit={handleTimeSearch}>
          <label>
            Timestamp
            <input
              type="datetime-local"
              value={timeQuery}
              onChange={(e) => setTimeQuery(e.target.value)}
              list="time-suggestions"
            />
            <datalist id="time-suggestions">
              {timeSuggestions.map((suggestion) => (
                <option key={suggestion} value={suggestion.slice(0, 19)}>
                  {new Date(suggestion).toLocaleString()}
                </option>
              ))}
            </datalist>
          </label>
          <button type="submit">Find at Time</button>
        </form>
        <form onSubmit={handleRangeReplay} className="range-form">
          <label>
            Time Range Start
            <input type="datetime-local" value={rangeStart} onChange={(e) => setRangeStart(e.target.value)} />
          </label>
          <label>
            Time Range End
            <input type="datetime-local" value={rangeEnd} onChange={(e) => setRangeEnd(e.target.value)} />
          </label>
          <label>
            Delay (ms)
            <input
              type="number"
              min={0}
              value={rangeDelay}
              onChange={(e) => setRangeDelay(Number(e.target.value))}
            />
          </label>
          <button type="submit">Replay Time Range</button>
        </form>
        <form onSubmit={handleSequenceRangeReplay}>
          <label>
            Sequence Start
            <input
              type="number"
              min={1}
              value={sequenceRangeStart}
              onChange={(e) => setSequenceRangeStart(e.target.value)}
            />
          </label>
          <label>
            Sequence End
            <input
              type="number"
              min={1}
              value={sequenceRangeEnd}
              onChange={(e) => setSequenceRangeEnd(e.target.value)}
            />
          </label>
          <button type="submit">Replay Sequence Range</button>
        </form>
      </div>

      {error && <p className="error">{error}</p>}

      {history && (
        <div className="history-table-wrapper">
          <div className="history-meta">
            Showing {history.returned_count} / {history.total_count} executions · Click a row for payload + response
          </div>
          <table className="history-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Sent</th>
                <th>Message</th>
                <th>State</th>
                <th>Mutators</th>
                <th>Result</th>
                <th>Duration</th>
              </tr>
            </thead>
            <tbody>
              {history.executions.map((execution) => (
                <tr key={execution.test_case_id} onClick={() => handleTimelineSelect(execution)}>
                  <td>{execution.sequence_number}</td>
                  <td>{new Date(execution.timestamp_sent).toLocaleString()}</td>
                  <td>{execution.message_type || '—'}</td>
                  <td>{execution.state_at_send || '—'}</td>
                  <td>
                    {execution.mutators_applied && execution.mutators_applied.length > 0
                      ? execution.mutators_applied.slice(0, 3).join(', ')
                      : '—'}
                  </td>
                  <td>
                    <StatusBadge value={execution.result} />
                  </td>
                  <td>{execution.duration_ms.toFixed(1)} ms</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <Modal
        open={Boolean(selectedExecution)}
        onClose={() => setSelectedExecution(null)}
        title={selectedExecution ? `Sequence ${selectedExecution.sequence_number}` : ''}
      >
        {selectedExecution && (
          <>
            <div className="detail-header">
              <div>
                <p>
                  {new Date(selectedExecution.timestamp_sent).toLocaleString()} · State{' '}
                  {selectedExecution.state_at_send || 'N/A'}
                </p>
                <StatusBadge value={selectedExecution.result} />
              </div>
              <button type="button" onClick={handleReplaySingle}>
                Replay
              </button>
            </div>
            <div className="detail-body">
              <div>
                <span>Mutation Strategy</span>
                <p className="mutator-inline">{selectedExecution.mutation_strategy || '—'}</p>
              </div>
              <div>
                <span>Mutators</span>
                <p className="mutator-inline">
                  {selectedExecution.mutators_applied && selectedExecution.mutators_applied.length > 0
                    ? selectedExecution.mutators_applied.join(', ')
                    : '—'}
                </p>
              </div>
              <div>
                <span>Payload Preview</span>
                <pre>{selectedExecution.payload_preview}</pre>
              </div>
              <div>
                <span>Response Preview</span>
                <pre>{selectedExecution.response_preview || '—'}</pre>
              </div>
              <div>
                <span>Base64 Payload</span>
                <textarea readOnly value={selectedExecution.raw_payload_b64} />
              </div>
            </div>
          </>
        )}
      </Modal>

      {replayLog.length > 0 && (
        <div className="replay-log">
          <p className="eyebrow">Replay Log</p>
          <ul>
            {replayLog.map((entry, idx) => (
              <li key={idx}>{entry}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default CorrelationPage;
