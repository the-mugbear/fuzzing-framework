import { FormEvent, useEffect, useMemo, useState } from 'react';
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

  const selectedSession = useMemo(() => sessions.find((s) => s.id === selectedSessionId), [sessions, selectedSessionId]);

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
            Refresh
          </button>
        </div>
      </div>

      {selectedSession && (
        <div className="session-summary">
          <div>
            <span>Protocol</span>
            <strong>{selectedSession.protocol}</strong>
          </div>
          <div>
            <span>Target</span>
            <strong>
              {selectedSession.target_host}:{selectedSession.target_port}
            </strong>
          </div>
          <div>
            <span>Status</span>
            <StatusBadge value={selectedSession.status} />
          </div>
        </div>
      )}

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
