import { useCallback, useEffect, useRef, useState } from 'react';
import Toast, { ToastVariant } from '../components/Toast';
import './TargetsPage.css';

/* ---------- Types matching target_manager models ---------- */

interface ServerMeta {
  script: string;
  name: string;
  description: string;
  transport: 'tcp' | 'udp';
  default_port: number;
  compatible_plugins: string[];
  vulnerabilities: number;
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
  last_health_check: string | null;
  log_lines: number;
  compatible_plugins: string[];
}

interface TMHealth {
  status: string;
  running_targets: number;
  available_servers: number;
  port_pool_available: number;
}

interface LogResponse {
  target_id: string;
  lines: string[];
  total_lines: number;
}

/* ---------- Target Manager API helpers ---------- */

const TM_BASE = import.meta.env.VITE_TARGET_MANAGER_URL ?? 'http://localhost:8001';

async function tmApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${TM_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let msg = res.statusText;
    try { const d = await res.json(); msg = d.detail || d.message || msg; } catch { /* */ }
    throw new Error(msg);
  }
  if (res.status === 204) return {} as T;
  return res.json();
}

/* ---------- Component ---------- */

export default function TargetsPage() {
  const [servers, setServers] = useState<ServerMeta[]>([]);
  const [targets, setTargets] = useState<RunningTarget[]>([]);
  const [tmHealth, setTmHealth] = useState<TMHealth | null>(null);
  const [tmError, setTmError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);   // script being acted on
  const [toast, setToast] = useState<{ variant: ToastVariant; message: string } | null>(null);
  const [logViewId, setLogViewId] = useState<string | null>(null);
  const [logLines, setLogLines] = useState<string[]>([]);
  const pollRef = useRef<number>();

  /* ---- Fetch catalog + running targets ---- */
  const refresh = useCallback(async () => {
    try {
      const [h, s, t] = await Promise.all([
        tmApi<TMHealth>('/api/health'),
        tmApi<ServerMeta[]>('/api/servers'),
        tmApi<RunningTarget[]>('/api/targets'),
      ]);
      setTmHealth(h);
      setServers(s);
      setTargets(t);
      setTmError(null);
    } catch (err: any) {
      setTmError(err.message ?? 'Target Manager unreachable');
    }
  }, []);

  useEffect(() => {
    refresh();
    pollRef.current = window.setInterval(refresh, 4000);
    return () => clearInterval(pollRef.current);
  }, [refresh]);

  /* ---- Actions ---- */
  const startServer = async (script: string, port?: number) => {
    setBusy(script);
    try {
      const t = await tmApi<RunningTarget>('/api/targets', {
        method: 'POST',
        body: JSON.stringify({ script, port: port ?? 0 }),
      });
      setToast({ variant: 'success', message: `Started ${t.name} on port ${t.port}` });
      await refresh();
    } catch (err: any) {
      setToast({ variant: 'error', message: err.message });
    } finally {
      setBusy(null);
    }
  };

  const stopTarget = async (id: string) => {
    setBusy(id);
    try {
      await tmApi('/api/targets/' + id, { method: 'DELETE' });
      setToast({ variant: 'success', message: 'Target stopped' });
      if (logViewId === id) { setLogViewId(null); setLogLines([]); }
      await refresh();
    } catch (err: any) {
      setToast({ variant: 'error', message: err.message });
    } finally {
      setBusy(null);
    }
  };

  const fetchLogs = async (id: string) => {
    if (logViewId === id) { setLogViewId(null); setLogLines([]); return; }
    try {
      const lr = await tmApi<LogResponse>(`/api/targets/${id}/logs?tail=150`);
      setLogLines(lr.lines);
      setLogViewId(id);
    } catch (err: any) {
      setToast({ variant: 'error', message: err.message });
    }
  };

  /* ---- Helpers ---- */
  const runningFor = (script: string): RunningTarget | undefined =>
    targets.find((t) => t.script === script);

  const healthDot = (h: string) => {
    switch (h) {
      case 'healthy': return 'green';
      case 'unhealthy': return 'red';
      case 'starting': return 'yellow';
      default: return 'yellow';
    }
  };

  /* ---- Render ---- */
  return (
    <div className="targets-page">
      <div>
        <h2>Target Servers</h2>
        <p className="section-desc">
          Start, stop, and monitor test servers from the UI. Each server
          exercises a specific protocol plugin — no container restarts needed.
        </p>
      </div>

      {/* Status bar */}
      {tmError ? (
        <div className="tm-status-bar">
          <span className="dot red" />
          <span>Target Manager unreachable — <code>{tmError}</code></span>
        </div>
      ) : tmHealth ? (
        <div className="tm-status-bar">
          <span className="dot green" />
          <span>{tmHealth.available_servers} servers available</span>
          <span>·</span>
          <span>{tmHealth.running_targets} running</span>
          <span>·</span>
          <span>{tmHealth.port_pool_available} ports free</span>
        </div>
      ) : null}

      {/* Running targets */}
      {targets.length > 0 && (
        <section>
          <h3 style={{ margin: '0 0 var(--space-md)' }}>Running</h3>
          <div className="running-targets">
            {targets.map((t) => (
              <div key={t.id}>
                <div className="running-target-row">
                  <span className={`health-dot ${t.health}`} title={t.health} />
                  <div className="target-info">
                    <span className="name">{t.name}</span>
                    <span className="detail">{t.script} · PID {t.pid ?? '—'}</span>
                  </div>
                  <span className="port-tag">:{t.port}</span>
                  <button
                    className="btn-logs"
                    onClick={() => fetchLogs(t.id)}
                    title="Toggle logs"
                  >
                    {logViewId === t.id ? 'Hide logs' : 'Logs'}
                  </button>
                  <button
                    className="btn-stop"
                    onClick={() => stopTarget(t.id)}
                    disabled={busy === t.id}
                  >
                    Stop
                  </button>
                </div>

                {logViewId === t.id && (
                  <div className="log-viewer" role="log" aria-label={`Logs for ${t.name}`}>
                    {logLines.length === 0 ? (
                      <span style={{ color: 'var(--text-tertiary)' }}>No output yet</span>
                    ) : (
                      logLines.map((line, i) => (
                        <div key={i} className="log-line">{line}</div>
                      ))
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Server catalog */}
      <section>
        <h3 style={{ margin: '0 0 var(--space-md)' }}>Server Catalog</h3>
        {servers.length === 0 && !tmError && (
          <div className="empty-state">Loading catalog…</div>
        )}
        <div className="server-catalog">
          {servers.map((s) => {
            const running = runningFor(s.script);
            return (
              <div key={s.script} className="server-card">
                <div className="card-header">
                  <h3>{s.name}</h3>
                  <span className={`transport-badge ${s.transport}`}>
                    {s.transport}
                  </span>
                </div>
                <div className="card-desc">{s.description}</div>
                <div className="card-meta">
                  <span>Port {s.default_port}</span>
                  {s.vulnerabilities > 0 && (
                    <span className="tag vuln-tag">
                      {s.vulnerabilities} vuln{s.vulnerabilities > 1 ? 's' : ''}
                    </span>
                  )}
                </div>
                {s.compatible_plugins.length > 0 && (
                  <div className="compat-pills">
                    {s.compatible_plugins.map((p) => (
                      <span key={p} className="compat-pill">{p}</span>
                    ))}
                  </div>
                )}
                <div className="card-actions">
                  {running ? (
                    <>
                      <button
                        className="btn-stop"
                        onClick={() => stopTarget(running.id)}
                        disabled={busy === running.id}
                      >
                        Stop (:{running.port})
                      </button>
                      <button className="btn-logs" onClick={() => fetchLogs(running.id)}>
                        Logs
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn-start"
                      onClick={() => startServer(s.script, s.default_port)}
                      disabled={busy === s.script || !!tmError}
                    >
                      {busy === s.script ? 'Starting…' : 'Start'}
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {toast && (
        <Toast variant={toast.variant} message={toast.message} onClose={() => setToast(null)} />
      )}
    </div>
  );
}
