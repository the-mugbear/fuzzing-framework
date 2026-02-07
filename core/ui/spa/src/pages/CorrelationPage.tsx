import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
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
  total_tests: number;
  crashes: number;
  hangs: number;
  anomalies: number;
  transport: string;
  execution_mode: string;
  enabled_mutators: string[];
  fuzzing_mode?: string | null;
  state_coverage?: Record<string, number> | null;
  // Session configuration parameters
  mutation_mode?: string | null;
  structure_aware_weight?: number | null;
  rate_limit_per_second?: number | null;
  max_iterations?: number | null;
  timeout_per_test_ms?: number | null;
  session_reset_interval?: number | null;
  enable_termination_fuzzing?: boolean | null;
  target_state?: string | null;
  created_at?: string | null;
  started_at?: string | null;
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
  raw_response_b64?: string | null;
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

interface ParsedField {
  name: string;
  value: any;
  hex: string;
  offset: number;
  size: number;
  type: string;
}

interface PacketParseResponse {
  success: boolean;
  total_bytes: number;
  fields: ParsedField[];
  warnings?: string[];
  error?: string | null;
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
  const [replayLog, setReplayLog] = useState<string[]>([]);
  const [reportPending, setReportPending] = useState(false);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [historyLimit] = useState(500);
  const [selectedResults, setSelectedResults] = useState<string[]>([]);
  const [selectedStates, setSelectedStates] = useState<string[]>([]);
  const [selectedMutators, setSelectedMutators] = useState<string[]>([]);
  const [timelineRange, setTimelineRange] = useState({ startPct: 0, endPct: 100 });
  const [timelineInitialized, setTimelineInitialized] = useState(false);
  const [parsedPayload, setParsedPayload] = useState<PacketParseResponse | null>(null);
  const [parsedResponse, setParsedResponse] = useState<PacketParseResponse | null>(null);
  const [parseLoading, setParseLoading] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [showParams, setShowParams] = useState(false);
  const [payloadEncoding, setPayloadEncoding] = useState<'hex' | 'base64'>('hex');
  const [responseEncoding, setResponseEncoding] = useState<'hex' | 'base64'>('hex');

  // Load sessions on mount
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

  const selectedSession = useMemo(
    () => sessions.find((s) => s.id === selectedSessionId),
    [sessions, selectedSessionId]
  );

  // Fetch history function
  const fetchHistory = useCallback(
    (nextOffset: number = historyOffset) => {
      if (!selectedSessionId) {
        return;
      }
      setLoadingHistory(true);
      api<ExecutionHistoryResponse>(
        `/api/sessions/${selectedSessionId}/execution_history?limit=${historyLimit}&offset=${nextOffset}`
      )
        .then((data) => {
          setHistory(data);
          setHistoryOffset(nextOffset);
          setError(null);
        })
        .catch((err) => {
          setError(err.message);
          setHistory(null);
        })
        .finally(() => setLoadingHistory(false));
    },
    [selectedSessionId, historyLimit, historyOffset]
  );

  // Fetch history when session changes
  useEffect(() => {
    if (selectedSessionId) {
      setTimelineInitialized(false);
      setHistoryOffset(0);
      fetchHistory(0);
    }
  }, [selectedSessionId]);

  // Auto-refresh for running sessions
  useEffect(() => {
    if (!selectedSessionId || selectedSession?.status !== 'RUNNING') {
      return;
    }
    const id = window.setInterval(() => fetchHistory(historyOffset), 5000);
    return () => window.clearInterval(id);
  }, [selectedSessionId, selectedSession?.status, historyOffset, fetchHistory]);

  // Timeline calculations
  const timelineExecutions = useMemo(() => {
    if (!history?.executions) return [];
    return [...history.executions].sort(
      (a, b) => new Date(a.timestamp_sent).getTime() - new Date(b.timestamp_sent).getTime()
    );
  }, [history]);

  const timelineBounds = useMemo(() => {
    if (timelineExecutions.length === 0) return null;
    const start = new Date(timelineExecutions[0].timestamp_sent).getTime();
    const end = new Date(timelineExecutions[timelineExecutions.length - 1].timestamp_sent).getTime();
    return { start, end };
  }, [timelineExecutions]);

  const selectedWindow = useMemo(() => {
    if (!timelineBounds) return null;
    const span = Math.max(1, timelineBounds.end - timelineBounds.start);
    const start = timelineBounds.start + (span * timelineRange.startPct) / 100;
    const end = timelineBounds.start + (span * timelineRange.endPct) / 100;
    return { start: Math.min(start, end), end: Math.max(start, end) };
  }, [timelineBounds, timelineRange]);

  useEffect(() => {
    if (!timelineInitialized && timelineBounds) {
      setTimelineRange({ startPct: 0, endPct: 100 });
      setTimelineInitialized(true);
    }
  }, [timelineBounds, timelineInitialized]);

  // Filtered executions
  const filteredExecutions = useMemo(() => {
    if (!history?.executions) return [];
    if (!selectedWindow) return history.executions;
    return history.executions.filter((execution) => {
      const ts = new Date(execution.timestamp_sent).getTime();
      if (ts < selectedWindow.start || ts > selectedWindow.end) return false;
      if (selectedResults.length > 0 && !selectedResults.includes(execution.result)) return false;
      if (selectedStates.length > 0) {
        if (!execution.state_at_send || !selectedStates.includes(execution.state_at_send)) return false;
      }
      if (selectedMutators.length > 0) {
        const applied = execution.mutators_applied || [];
        if (!applied.some((mutator) => selectedMutators.includes(mutator))) return false;
      }
      return true;
    });
  }, [history, selectedWindow, selectedResults, selectedStates, selectedMutators]);

  // Filter options: states from session coverage, others from current page
  const filterOptions = useMemo(() => {
    const resultSet = new Set<string>();
    const mutatorSet = new Set<string>();
    history?.executions.forEach((execution) => {
      if (execution.result) resultSet.add(execution.result);
      (execution.mutators_applied || []).forEach((m) => mutatorSet.add(m));
    });
    // Use session's state_coverage for complete state list (not just current page)
    const states = selectedSession?.state_coverage
      ? Object.keys(selectedSession.state_coverage).sort()
      : [];
    return {
      results: Array.from(resultSet).sort(),
      states,
      mutators: Array.from(mutatorSet).sort(),
    };
  }, [history, selectedSession?.state_coverage]);

  // Parse selected execution's payload/response
  useEffect(() => {
    if (!selectedExecution || !selectedSession?.protocol) {
      setParsedPayload(null);
      setParsedResponse(null);
      setParseError(null);
      setParseLoading(false);
      return;
    }
    let active = true;
    const run = async () => {
      setParseLoading(true);
      setParseError(null);
      try {
        const payloadParse = await api<PacketParseResponse>(
          `/api/plugins/${selectedSession.protocol}/parse`,
          {
            method: 'POST',
            body: JSON.stringify({
              packet: selectedExecution.raw_payload_b64,
              format: 'base64',
              allow_partial: true,
            }),
          }
        );
        if (!active) return;
        setParsedPayload(payloadParse);
        if (selectedExecution.raw_response_b64) {
          const responseParse = await api<PacketParseResponse>(
            `/api/plugins/${selectedSession.protocol}/parse`,
            {
              method: 'POST',
              body: JSON.stringify({
                packet: selectedExecution.raw_response_b64,
                format: 'base64',
                model: 'response',
                allow_partial: true,
              }),
            }
          );
          if (!active) return;
          setParsedResponse(responseParse);
        }
      } catch (err) {
        if (active) setParseError((err as Error).message);
      } finally {
        if (active) setParseLoading(false);
      }
    };
    run();
    return () => {
      active = false;
    };
  }, [selectedExecution, selectedSession?.protocol]);

  // Helpers
  const formatTimestamp = (value: number) => new Date(value).toLocaleString();
  const formatResultLabel = (label: string) =>
    label.replace(/_/g, ' ').replace(/\b\w/g, (m) => m.toUpperCase());

  const base64ToHex = (value: string | null | undefined, fallback?: string) => {
    if (!value) return fallback || '';
    try {
      const binary = atob(value);
      let hex = '';
      for (let i = 0; i < binary.length; i += 1) {
        hex += binary.charCodeAt(i).toString(16).padStart(2, '0');
      }
      return hex;
    } catch {
      return fallback || '';
    }
  };

  const toggleFilterValue = (value: string, current: string[], setter: (next: string[]) => void) => {
    if (current.includes(value)) {
      setter(current.filter((v) => v !== value));
    } else {
      setter([...current, value]);
    }
  };

  // Pagination
  const canPageNewer = historyOffset > 0;
  const canPageOlder = history
    ? historyOffset + history.executions.length < history.total_count || history.executions.length === historyLimit
    : false;
  const sequenceRange = useMemo(() => {
    if (!history || history.executions.length === 0) return null;
    const sequences = history.executions.map((e) => e.sequence_number);
    return { min: Math.min(...sequences), max: Math.max(...sequences) };
  }, [history]);

  // Handlers
  const handleTimelineSelect = (execution: TestCaseExecutionRecord) => {
    setSelectedExecution(execution);
    setReplayLog((prev) => [
      `Selected sequence ${execution.sequence_number} (${new Date(execution.timestamp_sent).toLocaleString()})`,
      ...prev,
    ]);
  };

  const handleTimelineStartChange = (value: number) => {
    setTimelineRange((prev) => ({ startPct: Math.min(value, prev.endPct), endPct: prev.endPct }));
  };

  const handleTimelineEndChange = (value: number) => {
    setTimelineRange((prev) => ({ startPct: prev.startPct, endPct: Math.max(value, prev.startPct) }));
  };

  const resetTimeline = () => setTimelineRange({ startPct: 0, endPct: 100 });

  const handleSequenceSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!sequenceQuery || !selectedSessionId) return;
    try {
      const execution = await api<TestCaseExecutionRecord>(
        `/api/sessions/${selectedSessionId}/execution/${sequenceQuery}`
      );
      setSelectedExecution(execution);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleTimeSearch = async (event: FormEvent) => {
    event.preventDefault();
    if (!timeQuery || !selectedSessionId) return;
    try {
      const iso = new Date(timeQuery).toISOString();
      const execution = await api<TestCaseExecutionRecord>(
        `/api/sessions/${selectedSessionId}/execution/at_time?timestamp=${encodeURIComponent(iso)}`
      );
      setSelectedExecution(execution);
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const handleReplaySingle = async () => {
    if (!selectedSessionId || !selectedExecution) return;
    try {
      const response = await api<ReplayResponse>(
        `/api/sessions/${selectedSessionId}/execution/replay`,
        {
          method: 'POST',
          body: JSON.stringify({ sequence_numbers: [selectedExecution.sequence_number], delay_ms: 0 }),
        }
      );
      setReplayLog((prev) => [
        `Replayed sequence ${selectedExecution.sequence_number} (${response.replayed_count} results)`,
        ...prev,
      ]);
    } catch (err) {
      setReplayLog((prev) => [`Replay failed: ${(err as Error).message}`, ...prev]);
    }
  };

  const handleDownloadReport = async () => {
    if (!selectedSessionId) return;
    setReportPending(true);
    try {
      const historyPayload = await api<ExecutionHistoryResponse>(
        `/api/sessions/${selectedSessionId}/execution_history?limit=1000`
      );
      const report = {
        generated_at: new Date().toISOString(),
        session: selectedSession,
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
      setReplayLog((prev) => [`Exported report (${historyPayload.executions.length} executions)`, ...prev]);
    } catch (err) {
      setReplayLog((prev) => [`Report export failed: ${(err as Error).message}`, ...prev]);
    } finally {
      setReportPending(false);
    }
  };

  const renderParsedFields = (parsed: PacketParseResponse | null, emptyLabel: string) => {
    if (parseLoading) return <div className="parsed-empty">Parsing fields...</div>;
    if (parseError) return <div className="parsed-empty">Parse failed: {parseError}</div>;
    if (!parsed) return <div className="parsed-empty">{emptyLabel}</div>;
    if (!parsed.success) return <div className="parsed-empty">Parse failed: {parsed.error || 'Unable to parse.'}</div>;
    if (parsed.fields.length === 0) return <div className="parsed-empty">No fields returned.</div>;
    return (
      <>
        {parsed.warnings && parsed.warnings.length > 0 && (
          <div className="parsed-warning">{parsed.warnings.join(' ')}</div>
        )}
        <table className="parsed-table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Type</th>
              <th>Offset</th>
              <th>Size</th>
              <th>Value</th>
            </tr>
          </thead>
          <tbody>
            {parsed.fields.map((field) => (
              <tr key={`${field.name}-${field.offset}`}>
                <td>{field.name}</td>
                <td>{field.type}</td>
                <td>{field.offset}</td>
                <td>{field.size}</td>
                <td><code>{field.hex}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </>
    );
  };

  const hasActiveFilters = selectedResults.length > 0 || selectedStates.length > 0 || selectedMutators.length > 0;

  return (
    <div className="card correlation-card">
      {/* Header */}
      <div className="correlation-header">
        <div>
          <p className="eyebrow">Correlation & Replay</p>
          <h2>Execution History</h2>
          <p>Find test cases by time or sequence, inspect payloads, and replay them.</p>
        </div>
        <div className="session-picker">
          <select value={selectedSessionId} onChange={(e) => setSelectedSessionId(e.target.value)}>
            {sessions.map((session) => (
              <option key={session.id} value={session.id}>
                {session.protocol} | {session.id.slice(0, 8)}
              </option>
            ))}
          </select>
          <button type="button" onClick={() => fetchHistory(historyOffset)} disabled={loadingHistory}>
            {loadingHistory ? 'Loading...' : 'Refresh'}
          </button>
          <button type="button" className="ghost" onClick={handleDownloadReport} disabled={reportPending}>
            {reportPending ? 'Building...' : 'Export'}
          </button>
        </div>
      </div>

      {/* Quick Stats */}
      {selectedSession && (
        <div className="session-kpis">
          <div>
            <span>Status</span>
            <StatusBadge value={selectedSession.status} />
          </div>
          <div>
            <span>Total Tests</span>
            <strong>{selectedSession.total_tests.toLocaleString()}</strong>
          </div>
          <div>
            <span>Crashes</span>
            <strong>{selectedSession.crashes.toLocaleString()}</strong>
          </div>
          <div>
            <span>Hangs</span>
            <strong>{selectedSession.hangs.toLocaleString()}</strong>
          </div>
          <div>
            <span>Anomalies</span>
            <strong>{selectedSession.anomalies.toLocaleString()}</strong>
          </div>
          <div className="kpi-link">
            <span>Coverage</span>
            <Link to={`/state-graph?session=${selectedSessionId}`}>View State Graph →</Link>
          </div>
        </div>
      )}

      {/* Session Parameters - Collapsible */}
      {selectedSession && (
        <div className="session-params-section">
          <button
            className="params-toggle"
            onClick={() => setShowParams(!showParams)}
            aria-expanded={showParams}
          >
            {showParams ? '▼' : '▶'} Session Configuration
          </button>
          {showParams && (
            <div className="session-params-grid">
              <div className="param-group">
                <h4>Target</h4>
                <div className="param-row">
                  <span>Protocol:</span>
                  <code>{selectedSession.protocol}</code>
                </div>
                <div className="param-row">
                  <span>Host:</span>
                  <code>{selectedSession.target_host}:{selectedSession.target_port}</code>
                </div>
                <div className="param-row">
                  <span>Transport:</span>
                  <code>{selectedSession.transport}</code>
                </div>
              </div>

              <div className="param-group">
                <h4>Mutation</h4>
                <div className="param-row">
                  <span>Mode:</span>
                  <code>{selectedSession.mutation_mode || 'hybrid'}</code>
                </div>
                {selectedSession.mutation_mode === 'hybrid' && (
                  <div className="param-row">
                    <span>Structure Weight:</span>
                    <code>{selectedSession.structure_aware_weight ?? 70}%</code>
                  </div>
                )}
                <div className="param-row">
                  <span>Mutators:</span>
                  <code>{selectedSession.enabled_mutators?.length
                    ? selectedSession.enabled_mutators.join(', ')
                    : 'all'}</code>
                </div>
              </div>

              <div className="param-group">
                <h4>Execution</h4>
                <div className="param-row">
                  <span>Mode:</span>
                  <code>{selectedSession.execution_mode}</code>
                </div>
                <div className="param-row">
                  <span>Rate Limit:</span>
                  <code>{selectedSession.rate_limit_per_second ?? 'unlimited'}/sec</code>
                </div>
                <div className="param-row">
                  <span>Timeout:</span>
                  <code>{selectedSession.timeout_per_test_ms ?? 5000}ms</code>
                </div>
                <div className="param-row">
                  <span>Max Iterations:</span>
                  <code>{selectedSession.max_iterations ?? 'unlimited'}</code>
                </div>
              </div>

              <div className="param-group">
                <h4>Strategy</h4>
                <div className="param-row">
                  <span>Fuzzing Mode:</span>
                  <code>{selectedSession.fuzzing_mode || 'random'}</code>
                </div>
                {selectedSession.target_state && (
                  <div className="param-row">
                    <span>Target State:</span>
                    <code>{selectedSession.target_state}</code>
                  </div>
                )}
                {selectedSession.session_reset_interval && (
                  <div className="param-row">
                    <span>Reset Interval:</span>
                    <code>{selectedSession.session_reset_interval}</code>
                  </div>
                )}
              </div>

              <div className="param-group">
                <h4>Timestamps</h4>
                <div className="param-row">
                  <span>Created:</span>
                  <code>{selectedSession.created_at
                    ? new Date(selectedSession.created_at).toLocaleString()
                    : 'N/A'}</code>
                </div>
                <div className="param-row">
                  <span>Started:</span>
                  <code>{selectedSession.started_at
                    ? new Date(selectedSession.started_at).toLocaleString()
                    : 'Not started'}</code>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {error && <p className="error">{error}</p>}

      {/* Search Section */}
      <div className="search-grid">
        <form onSubmit={handleSequenceSearch} className="search-card search-form">
          <label>
            Sequence #
            <input
              value={sequenceQuery}
              onChange={(e) => setSequenceQuery(e.target.value)}
              placeholder="e.g., 847"
            />
          </label>
          <button type="submit">Find</button>
        </form>
        <form onSubmit={handleTimeSearch} className="search-card search-form">
          <label>
            Timestamp
            <input
              type="datetime-local"
              value={timeQuery}
              onChange={(e) => setTimeQuery(e.target.value)}
            />
          </label>
          <button type="submit">Find</button>
        </form>
      </div>

      {/* Filters */}
      {history && history.executions.length > 0 && (
        <div className="search-card filter-card">
          <div className="filter-header">
            <div>
              <p className="eyebrow">Filters</p>
              <span className="filter-count">{filteredExecutions.length} of {history.returned_count} shown</span>
            </div>
            {hasActiveFilters && (
              <button
                type="button"
                className="ghost clear-filters"
                onClick={() => {
                  setSelectedResults([]);
                  setSelectedStates([]);
                  setSelectedMutators([]);
                }}
              >
                Clear
              </button>
            )}
          </div>
          <div className="filter-grid">
            <div className="filter-group">
              <span>Results</span>
              <div className="filter-tags">
                {filterOptions.results.length === 0 && <span className="filter-empty">—</span>}
                {filterOptions.results.map((result) => (
                  <button
                    key={result}
                    type="button"
                    className={`filter-tag ${selectedResults.includes(result) ? 'active' : ''}`}
                    onClick={() => toggleFilterValue(result, selectedResults, setSelectedResults)}
                  >
                    {formatResultLabel(result)}
                  </button>
                ))}
              </div>
            </div>
            {filterOptions.states.length > 0 && (
              <div className="filter-group">
                <span>States</span>
                <div className="filter-tags">
                  {filterOptions.states.map((state) => (
                    <button
                      key={state}
                      type="button"
                      className={`filter-tag ${selectedStates.includes(state) ? 'active' : ''}`}
                      onClick={() => toggleFilterValue(state, selectedStates, setSelectedStates)}
                    >
                      {state}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {filterOptions.mutators.length > 0 && (
              <div className="filter-group">
                <span>Mutators</span>
                <div className="filter-tags">
                  {filterOptions.mutators.map((mutator) => (
                    <button
                      key={mutator}
                      type="button"
                      className={`filter-tag ${selectedMutators.includes(mutator) ? 'active' : ''}`}
                      onClick={() => toggleFilterValue(mutator, selectedMutators, setSelectedMutators)}
                    >
                      {mutator}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Empty State */}
      {history && history.total_count === 0 && (
        <div className="empty-state">
          <h3>No executions recorded</h3>
          <p>
            {selectedSession?.status === 'IDLE'
              ? 'Start the session to begin recording executions.'
              : selectedSession?.status === 'RUNNING'
              ? 'Executions will appear here as tests complete. Check back soon.'
              : 'No test cases have been executed for this session.'}
          </p>
          {selectedSession?.status === 'RUNNING' && (
            <button type="button" onClick={() => fetchHistory(0)}>
              Refresh Now
            </button>
          )}
        </div>
      )}

      {/* Timeline and Table */}
      {history && history.executions.length > 0 && (
        <>
          {timelineBounds && (
            <div className="timeline-card">
              <div className="timeline-header">
                <div>
                  <p className="eyebrow">Timeline</p>
                  <p className="timeline-range-text">
                    {formatTimestamp(selectedWindow?.start || timelineBounds.start)} —{' '}
                    {formatTimestamp(selectedWindow?.end || timelineBounds.end)}
                  </p>
                </div>
                <button type="button" className="ghost" onClick={resetTimeline}>
                  Reset
                </button>
              </div>
              <div className="timeline-track">
                <div
                  className="timeline-range"
                  style={{
                    left: `${timelineRange.startPct}%`,
                    width: `${timelineRange.endPct - timelineRange.startPct}%`,
                  }}
                />
                {/* Sample evenly across timeline to show max 200 dots */}
                {(() => {
                  const maxDots = 200;
                  const step = Math.max(1, Math.floor(timelineExecutions.length / maxDots));
                  const sampled = timelineExecutions.filter((_, i) => i % step === 0).slice(0, maxDots);
                  return sampled;
                })().map((execution) => {
                  const ts = new Date(execution.timestamp_sent).getTime();
                  const pct =
                    timelineBounds.end === timelineBounds.start
                      ? 0
                      : ((ts - timelineBounds.start) / (timelineBounds.end - timelineBounds.start)) * 100;
                  const isFiltered = filteredExecutions.some(
                    (e) => e.test_case_id === execution.test_case_id
                  );
                  return (
                    <button
                      key={execution.test_case_id}
                      type="button"
                      className={`timeline-dot ${execution.result !== 'pass' ? 'timeline-dot-notable' : ''} ${!isFiltered ? 'timeline-dot-filtered' : ''}`}
                      style={{ left: `${pct}%` }}
                      title={`#${execution.sequence_number} | ${execution.result} | ${new Date(execution.timestamp_sent).toLocaleTimeString()}`}
                      onClick={() => handleTimelineSelect(execution)}
                    />
                  );
                })}
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={timelineRange.startPct}
                  onChange={(e) => handleTimelineStartChange(Number(e.target.value))}
                  className="timeline-handle timeline-start"
                />
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={timelineRange.endPct}
                  onChange={(e) => handleTimelineEndChange(Number(e.target.value))}
                  className="timeline-handle timeline-end"
                />
              </div>
            </div>
          )}

          <div className="history-table-wrapper">
            <div className="history-pagination">
              <button
                type="button"
                className="ghost"
                onClick={() => fetchHistory(Math.max(0, historyOffset - (history?.returned_count || historyLimit)))}
                disabled={!canPageNewer || loadingHistory}
              >
                ← Newer
              </button>
              <span className="history-window">
                {sequenceRange && `#${sequenceRange.min}–${sequenceRange.max}`}
                {' · '}
                {historyOffset + 1}–{historyOffset + (history?.returned_count || 0)} of {history?.total_count || 0}
              </span>
              <button
                type="button"
                className="ghost"
                onClick={() => fetchHistory(historyOffset + (history?.returned_count || historyLimit))}
                disabled={!canPageOlder || loadingHistory}
              >
                Older →
              </button>
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
                {filteredExecutions.map((execution) => (
                  <tr key={execution.test_case_id} onClick={() => handleTimelineSelect(execution)}>
                    <td>{execution.sequence_number}</td>
                    <td>{new Date(execution.timestamp_sent).toLocaleTimeString()}</td>
                    <td>{execution.message_type || '—'}</td>
                    <td>{execution.state_at_send || '—'}</td>
                    <td>
                      {execution.mutators_applied && execution.mutators_applied.length > 0
                        ? execution.mutators_applied.slice(0, 2).join(', ')
                        : '—'}
                    </td>
                    <td><StatusBadge value={execution.result} /></td>
                    <td>{execution.duration_ms.toFixed(1)}ms</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filteredExecutions.length === 0 && history.executions.length > 0 && (
              <div className="history-empty">No executions match the current filters.</div>
            )}
          </div>
        </>
      )}

      {/* Execution Detail Modal */}
      <Modal
        open={Boolean(selectedExecution)}
        onClose={() => setSelectedExecution(null)}
        title={
          selectedExecution
            ? `#${selectedExecution.sequence_number} · ${new Date(selectedExecution.timestamp_sent).toLocaleString()}`
            : ''
        }
        className="modal-wide"
      >
        {selectedExecution && (
          <>
            <div className="detail-header">
              <div className="detail-header-info">
                <div>
                  <span className="detail-label">State</span>
                  <strong>{selectedExecution.state_at_send || 'N/A'}</strong>
                </div>
                <div>
                  <span className="detail-label">Result</span>
                  <StatusBadge value={selectedExecution.result} />
                </div>
                <div>
                  <span className="detail-label">Duration</span>
                  <strong>{selectedExecution.duration_ms.toFixed(1)} ms</strong>
                </div>
                <div>
                  <span className="detail-label">Mutators</span>
                  <strong>
                    {selectedExecution.mutators_applied?.join(', ') || selectedExecution.mutation_strategy || '—'}
                  </strong>
                </div>
              </div>
              <button type="button" onClick={handleReplaySingle}>
                Replay
              </button>
            </div>
            <div className="detail-body">
              <div className="detail-span-full">
                <div className="detail-row-header">
                  <span>Payload ({selectedExecution.payload_preview.length / 2} bytes)</span>
                  <div className="encoding-toggle">
                    <button
                      type="button"
                      className={payloadEncoding === 'hex' ? 'active' : ''}
                      onClick={() => setPayloadEncoding('hex')}
                    >
                      Hex
                    </button>
                    <button
                      type="button"
                      className={payloadEncoding === 'base64' ? 'active' : ''}
                      onClick={() => setPayloadEncoding('base64')}
                    >
                      Base64
                    </button>
                  </div>
                </div>
                <textarea
                  readOnly
                  value={
                    payloadEncoding === 'hex'
                      ? base64ToHex(selectedExecution.raw_payload_b64, selectedExecution.payload_preview)
                      : selectedExecution.raw_payload_b64
                  }
                />
              </div>
              <div className="detail-span-full">
                <div className="detail-row-header">
                  <span>Response</span>
                  <div className="encoding-toggle">
                    <button
                      type="button"
                      className={responseEncoding === 'hex' ? 'active' : ''}
                      onClick={() => setResponseEncoding('hex')}
                    >
                      Hex
                    </button>
                    <button
                      type="button"
                      className={responseEncoding === 'base64' ? 'active' : ''}
                      onClick={() => setResponseEncoding('base64')}
                    >
                      Base64
                    </button>
                  </div>
                </div>
                <textarea
                  readOnly
                  value={
                    responseEncoding === 'hex'
                      ? base64ToHex(selectedExecution.raw_response_b64, selectedExecution.response_preview || '—')
                      : selectedExecution.raw_response_b64 || '—'
                  }
                />
              </div>
              <div className="parsed-grid detail-span-full">
                <div className="parsed-section">
                  <span>Parsed Payload</span>
                  {renderParsedFields(parsedPayload, 'Select an execution to parse.')}
                </div>
                <div className="parsed-section">
                  <span>Parsed Response</span>
                  {renderParsedFields(parsedResponse, 'No response available.')}
                </div>
              </div>
            </div>
          </>
        )}
      </Modal>

      {/* Replay Log */}
      {replayLog.length > 0 && (
        <div className="replay-log">
          <p className="eyebrow">Activity Log</p>
          <ul>
            {replayLog.slice(0, 10).map((entry, idx) => (
              <li key={idx}>{entry}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default CorrelationPage;
