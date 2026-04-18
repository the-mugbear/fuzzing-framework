import { useEffect, useState, useCallback } from 'react';
import { api, API_BASE } from '../services/api';
import './FindingsPage.css';

interface CrashReport {
  id: string;
  session_id: string;
  protocol: string;
  severity: string;
  result_type: string;
  signal?: string;
  error_message?: string;
  timestamp?: string;
  stack_trace?: string;
  target_host?: string;
  target_port?: number;
  test_case_index?: number;
  execution_time_ms?: number;
}

interface Finding {
  finding_id: string;
  session_id: string;
  timestamp: string;
}

interface FindingDetail {
  report: CrashReport;
  reproducer_size: number;
  reproducer_sha256: string;
  reproducer_hex?: string;
}

interface Session {
  id: string;
  protocol: string;
  status: string;
  crashes: number;
  target_host: string;
  target_port: number;
}

export default function FindingsPage() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedSession, setSelectedSession] = useState<string>('');
  const [selectedFinding, setSelectedFinding] = useState<FindingDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [replayResult, setReplayResult] = useState<any>(null);
  const [replaying, setReplaying] = useState(false);

  const loadFindings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = selectedSession ? `?session_id=${selectedSession}` : '';
      const data = await api<{ findings: Finding[]; count: number }>(`/api/corpus/findings${params}`);
      setFindings(data.findings || []);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [selectedSession]);

  useEffect(() => {
    api<Session[]>('/api/sessions').then(setSessions).catch(() => {});
    loadFindings();
  }, [loadFindings]);

  const loadFindingDetail = async (findingId: string) => {
    setDetailLoading(true);
    setReplayResult(null);
    try {
      const detail = await api<FindingDetail>(`/api/corpus/findings/${findingId}?include_data=true`);
      setSelectedFinding(detail);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleReplay = async () => {
    if (!selectedFinding?.reproducer_hex || !selectedFinding.report) return;
    setReplaying(true);
    setReplayResult(null);
    try {
      const report = selectedFinding.report;
      const result = await api<any>('/api/tests/execute', {
        method: 'POST',
        body: JSON.stringify({
          protocol: report.protocol,
          target_host: report.target_host,
          target_port: report.target_port,
          payload_b64: btoa(
            selectedFinding.reproducer_hex
              .match(/.{1,2}/g)!
              .map((b: string) => String.fromCharCode(parseInt(b, 16)))
              .join('')
          ),
        }),
      });
      setReplayResult(result);
    } catch (err: any) {
      setReplayResult({ error: err.message });
    } finally {
      setReplaying(false);
    }
  };

  const downloadReproducer = () => {
    if (!selectedFinding?.reproducer_hex) return;
    const bytes = new Uint8Array(
      selectedFinding.reproducer_hex.match(/.{1,2}/g)!.map((b: string) => parseInt(b, 16))
    );
    const blob = new Blob([bytes], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `reproducer_${selectedFinding.report.id}.bin`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const severityClass = (severity: string) => {
    switch (severity?.toLowerCase()) {
      case 'critical': return 'severity-critical';
      case 'high': return 'severity-high';
      case 'medium': return 'severity-medium';
      case 'low': return 'severity-low';
      default: return 'severity-unknown';
    }
  };

  const resultIcon = (result: string) => {
    switch (result?.toUpperCase()) {
      case 'CRASH': return '💥';
      case 'HANG': return '⏳';
      case 'ANOMALY': return '⚠';
      case 'LOGICAL_FAILURE': return '🔍';
      default: return '•';
    }
  };

  return (
    <div className="findings-page">
      <div className="page-header">
        <h1>Findings</h1>
        <div className="page-header-actions">
          <select
            className="filter-select"
            value={selectedSession}
            onChange={(e) => setSelectedSession(e.target.value)}
          >
            <option value="">All Sessions</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.protocol} — {s.id.slice(0, 8)}… ({s.crashes} crashes)
              </option>
            ))}
          </select>
          <button className="btn btn-ghost" onClick={loadFindings}>↻ Refresh</button>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="findings-grid">
        {/* Left: Findings list */}
        <div className="findings-list-panel">
          <div className="panel-header">
            <span className="panel-title">Crash Artifacts</span>
            <span className="finding-count">{findings.length}</span>
          </div>
          <div className="findings-list">
            {loading ? (
              <div className="empty-state">Loading…</div>
            ) : findings.length === 0 ? (
              <div className="empty-state">
                <p>No findings yet.</p>
                <p className="hint">Findings appear here when the fuzzer detects crashes, hangs, or anomalies during a session.</p>
              </div>
            ) : (
              findings.map((f) => (
                <button
                  key={f.finding_id}
                  className={`finding-item ${selectedFinding?.report.id === f.finding_id ? 'active' : ''}`}
                  onClick={() => loadFindingDetail(f.finding_id)}
                >
                  <span className="finding-id">{f.finding_id.slice(0, 12)}…</span>
                  <span className="finding-meta">
                    <span className="finding-session">{f.session_id?.slice(0, 8)}</span>
                    {f.timestamp && (
                      <span className="finding-time">{new Date(f.timestamp).toLocaleString()}</span>
                    )}
                  </span>
                </button>
              ))
            )}
          </div>
        </div>

        {/* Right: Finding detail */}
        <div className="finding-detail-panel">
          {detailLoading ? (
            <div className="empty-state">Loading finding…</div>
          ) : !selectedFinding ? (
            <div className="empty-state">
              <h3>Select a finding</h3>
              <p>Click a finding from the list to view crash details, reproducer data, and replay capabilities.</p>
            </div>
          ) : (
            <div className="finding-detail">
              <div className="detail-header">
                <div className="detail-title-row">
                  <span className="result-icon">{resultIcon(selectedFinding.report.result_type)}</span>
                  <h2>{selectedFinding.report.result_type}</h2>
                  <span className={`severity-badge ${severityClass(selectedFinding.report.severity)}`}>
                    {selectedFinding.report.severity}
                  </span>
                </div>
                <div className="detail-actions">
                  <button className="btn btn-primary" onClick={handleReplay} disabled={replaying}>
                    {replaying ? 'Replaying…' : '▶ Replay'}
                  </button>
                  <button className="btn btn-ghost" onClick={downloadReproducer}>
                    ↓ Download .bin
                  </button>
                </div>
              </div>

              <div className="detail-grid">
                <div className="detail-card">
                  <h3>Report</h3>
                  <dl className="detail-list">
                    <dt>Finding ID</dt>
                    <dd className="mono">{selectedFinding.report.id}</dd>
                    <dt>Session</dt>
                    <dd className="mono">{selectedFinding.report.session_id}</dd>
                    <dt>Protocol</dt>
                    <dd>{selectedFinding.report.protocol}</dd>
                    <dt>Target</dt>
                    <dd>{selectedFinding.report.target_host}:{selectedFinding.report.target_port}</dd>
                    {selectedFinding.report.signal && (
                      <>
                        <dt>Signal</dt>
                        <dd>{selectedFinding.report.signal}</dd>
                      </>
                    )}
                    {selectedFinding.report.error_message && (
                      <>
                        <dt>Error</dt>
                        <dd className="error-text">{selectedFinding.report.error_message}</dd>
                      </>
                    )}
                    {selectedFinding.report.execution_time_ms != null && (
                      <>
                        <dt>Execution Time</dt>
                        <dd>{selectedFinding.report.execution_time_ms}ms</dd>
                      </>
                    )}
                    <dt>Reproducer Size</dt>
                    <dd>{selectedFinding.reproducer_size} bytes</dd>
                  </dl>
                </div>

                {selectedFinding.reproducer_hex && (
                  <div className="detail-card">
                    <h3>Reproducer Hex</h3>
                    <pre className="hex-dump">
                      {selectedFinding.reproducer_hex
                        .match(/.{1,2}/g)
                        ?.reduce((rows: string[], byte: string, i: number) => {
                          const rowIdx = Math.floor(i / 16);
                          if (!rows[rowIdx]) rows[rowIdx] = '';
                          rows[rowIdx] += byte + ' ';
                          return rows;
                        }, [])
                        .map((row: string, i: number) => (
                          `${(i * 16).toString(16).padStart(4, '0')}  ${row.trim()}`
                        ))
                        .join('\n')}
                    </pre>
                  </div>
                )}

                {selectedFinding.report.stack_trace && (
                  <div className="detail-card full-width">
                    <h3>Stack Trace</h3>
                    <pre className="stack-trace">{selectedFinding.report.stack_trace}</pre>
                  </div>
                )}

                {replayResult && (
                  <div className="detail-card full-width">
                    <h3>Replay Result</h3>
                    <pre className="replay-output">{JSON.stringify(replayResult, null, 2)}</pre>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
