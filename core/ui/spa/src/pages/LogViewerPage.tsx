import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import './LogViewerPage.css';

/* ---------- Types ---------- */

interface LogResponse {
  target_id: string;
  lines: string[];
  total_lines: number;
}

interface RunningTarget {
  id: string;
  script: string;
  name: string;
  transport: 'tcp' | 'udp';
  host: string;
  port: number;
  pid: number | null;
  health: 'unknown' | 'healthy' | 'unhealthy' | 'starting';
  started_at: string;
  log_lines: number;
}

type LogLevel = 'DEBUG' | 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR' | 'UNKNOWN';

interface ParsedLine {
  raw: string;
  stream: 'stdout' | 'stderr' | '';
  level: LogLevel;
  message: string;
}

/* ---------- Helpers ---------- */

const TM_BASE = import.meta.env.VITE_TARGET_MANAGER_URL ?? 'http://localhost:8001';

async function tmApi<T>(path: string): Promise<T> {
  const res = await fetch(`${TM_BASE}${path}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

const LEVEL_PATTERNS: [RegExp, LogLevel][] = [
  [/\bERROR\b|\bFATAL\b|\bCRITICAL\b|\[ERROR\s*\]|\[FATAL\s*\]/i, 'ERROR'],
  [/\bWARN(?:ING)?\b|\[WARN(?:ING)?\s*\]/i, 'WARNING'],
  [/\bSUCCESS\b|\[SUCCESS\s*\]/i, 'SUCCESS'],
  [/\bINFO\b|\[INFO\s*\]/i, 'INFO'],
  [/\bDEBUG\b|\[DEBUG\s*\]/i, 'DEBUG'],
];

function parseLine(raw: string): ParsedLine {
  let stream: 'stdout' | 'stderr' | '' = '';
  let message = raw;

  if (raw.startsWith('[stdout] ')) {
    stream = 'stdout';
    message = raw.slice(9);
  } else if (raw.startsWith('[stderr] ')) {
    stream = 'stderr';
    message = raw.slice(9);
  }

  let level: LogLevel = 'UNKNOWN';
  for (const [pat, lv] of LEVEL_PATTERNS) {
    if (pat.test(message)) { level = lv; break; }
  }
  // stderr defaults to ERROR if no level detected
  if (stream === 'stderr' && level === 'UNKNOWN') level = 'ERROR';

  return { raw, stream, level, message };
}

const LEVEL_ORDER: LogLevel[] = ['DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'UNKNOWN'];

/* ---------- Component ---------- */

export default function LogViewerPage() {
  const { targetId } = useParams<{ targetId: string }>();
  const [searchParams] = useSearchParams();
  const targetName = searchParams.get('name') ?? targetId ?? 'Unknown';

  const [lines, setLines] = useState<ParsedLine[]>([]);
  const [target, setTarget] = useState<RunningTarget | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [paused, setPaused] = useState(false);
  const [search, setSearch] = useState('');
  const [levelFilter, setLevelFilter] = useState<Set<LogLevel>>(new Set(LEVEL_ORDER));
  const [pollInterval, setPollInterval] = useState(2000);

  const logEndRef = useRef<HTMLDivElement>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const pollRef = useRef<number>();

  /* ---- Fetch logs ---- */
  const fetchLogs = useCallback(async () => {
    if (!targetId) return;
    try {
      const [lr, targets] = await Promise.all([
        tmApi<LogResponse>(`/api/targets/${targetId}/logs?tail=2000`),
        tmApi<RunningTarget[]>('/api/targets'),
      ]);
      const t = targets.find((x) => x.id === targetId) ?? null;
      setTarget(t);
      setLines(lr.lines.map(parseLine));
      setError(null);
    } catch (err: any) {
      setError(err.message);
    }
  }, [targetId]);

  /* ---- Polling ---- */
  useEffect(() => {
    fetchLogs();
    if (!paused) {
      pollRef.current = window.setInterval(fetchLogs, pollInterval);
    }
    return () => clearInterval(pollRef.current);
  }, [fetchLogs, paused, pollInterval]);

  /* ---- Auto-scroll ---- */
  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [lines, autoScroll]);

  /* ---- Detect user scroll-up to pause auto-scroll ---- */
  const handleScroll = useCallback(() => {
    const el = logContainerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  }, []);

  /* ---- Filter / search ---- */
  const searchLower = search.toLowerCase();
  const filtered = lines.filter((l) => {
    if (!levelFilter.has(l.level)) return false;
    if (search && !l.message.toLowerCase().includes(searchLower)) return false;
    return true;
  });

  const toggleLevel = (lv: LogLevel) => {
    setLevelFilter((prev) => {
      const next = new Set(prev);
      if (next.has(lv)) next.delete(lv);
      else next.add(lv);
      return next;
    });
  };

  /* ---- Level counts ---- */
  const counts = new Map<LogLevel, number>();
  for (const l of lines) counts.set(l.level, (counts.get(l.level) ?? 0) + 1);

  /* ---- Render ---- */
  return (
    <div className="log-viewer-page">
      {/* Header bar */}
      <header className="lv-header">
        <div className="lv-title-row">
          <h1>
            <span className="lv-icon">&#9654;</span>
            {targetName}
          </h1>
          {target && (
            <div className="lv-meta">
              <span className={`lv-health ${target.health}`}>{target.health}</span>
              <span className="lv-detail">:{target.port}</span>
              <span className="lv-detail">PID {target.pid ?? '—'}</span>
              <span className="lv-detail">{lines.length} lines</span>
            </div>
          )}
          {error && <span className="lv-error">{error}</span>}
        </div>

        {/* Controls row */}
        <div className="lv-controls">
          {/* Search */}
          <input
            type="text"
            className="lv-search"
            placeholder="Search logs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          {/* Level filters */}
          <div className="lv-level-filters">
            {LEVEL_ORDER.map((lv) => (
              <button
                key={lv}
                className={`lv-level-btn level-${lv.toLowerCase()} ${levelFilter.has(lv) ? 'active' : ''}`}
                onClick={() => toggleLevel(lv)}
                title={`${lv}: ${counts.get(lv) ?? 0} lines`}
              >
                {lv}
                <span className="lv-count">{counts.get(lv) ?? 0}</span>
              </button>
            ))}
          </div>

          {/* Pause / refresh controls */}
          <div className="lv-playback">
            <button
              className={`lv-btn ${paused ? 'paused' : ''}`}
              onClick={() => setPaused(!paused)}
              title={paused ? 'Resume auto-refresh' : 'Pause auto-refresh'}
            >
              {paused ? '▶ Resume' : '⏸ Pause'}
            </button>
            <select
              className="lv-interval"
              value={pollInterval}
              onChange={(e) => setPollInterval(Number(e.target.value))}
              title="Refresh interval"
            >
              <option value={1000}>1s</option>
              <option value={2000}>2s</option>
              <option value={5000}>5s</option>
              <option value={10000}>10s</option>
            </select>
            <button className="lv-btn" onClick={fetchLogs} title="Refresh now">
              ↻ Refresh
            </button>
          </div>
        </div>
      </header>

      {/* Log output */}
      <div
        className="lv-log-container"
        ref={logContainerRef}
        onScroll={handleScroll}
      >
        {filtered.length === 0 ? (
          <div className="lv-empty">
            {lines.length === 0 ? 'Waiting for log output…' : 'No lines match current filters'}
          </div>
        ) : (
          <div className="lv-lines">
            {filtered.map((line, i) => (
              <div
                key={i}
                className={`lv-line level-${line.level.toLowerCase()}`}
              >
                <span className="lv-linenum">{i + 1}</span>
                <span className="lv-level-tag">{line.level.padEnd(7)}</span>
                <span className="lv-text">{line.message}</span>
              </div>
            ))}
            <div ref={logEndRef} />
          </div>
        )}
      </div>

      {/* Footer status */}
      <footer className="lv-footer">
        <span>
          Showing {filtered.length} of {lines.length} lines
          {search && ` · filter: "${search}"`}
        </span>
        <span>
          {paused ? '⏸ Paused' : `↻ Every ${pollInterval / 1000}s`}
          {!autoScroll && ' · Scroll locked (scroll to bottom to resume)'}
        </span>
      </footer>
    </div>
  );
}
