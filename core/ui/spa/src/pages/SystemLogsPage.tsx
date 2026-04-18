import React, { useEffect, useState } from 'react';
import { api } from '../services/api';
import './SystemLogsPage.css';

interface LogFile {
  name: string;
  size_bytes: number;
  modified: string;
}

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

function SystemLogsPage() {
  const [logFiles, setLogFiles] = useState<LogFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [logContent, setLogContent] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tailLines, setTailLines] = useState<number>(200);
  const [levelFilter, setLevelFilter] = useState<string>('');
  const [bundleLoading, setBundleLoading] = useState(false);

  useEffect(() => {
    loadLogFiles();
  }, []);

  const loadLogFiles = async () => {
    try {
      const data = await api<{ files: LogFile[] }>('/api/system/logs');
      setLogFiles(data.files);
      if (data.files.length > 0 && !selectedFile) {
        loadLogContent(data.files[0].name);
      }
    } catch (err) {
      setError(`Failed to list log files: ${(err as Error).message}`);
    }
  };

  const loadLogContent = async (filename: string) => {
    setSelectedFile(filename);
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (tailLines) params.set('tail', String(tailLines));
      if (levelFilter) params.set('level', levelFilter);
      const qs = params.toString();
      const url = `/api/system/logs/${encodeURIComponent(filename)}${qs ? '?' + qs : ''}`;
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      setLogContent(await resp.text());
    } catch (err) {
      setError(`Failed to load ${filename}: ${(err as Error).message}`);
      setLogContent('');
    } finally {
      setLoading(false);
    }
  };

  const handleDownloadFile = (filename: string) => {
    window.open(`/api/system/logs/${encodeURIComponent(filename)}/download`, '_blank');
  };

  const handleDownloadBundle = async () => {
    setBundleLoading(true);
    try {
      const resp = await fetch('/api/system/diagnostic-bundle');
      if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText}`);
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `fuzzer-diagnostic-${new Date().toISOString().slice(0, 19).replace(/[T:]/g, '-')}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(`Bundle download failed: ${(err as Error).message}`);
    } finally {
      setBundleLoading(false);
    }
  };

  const refresh = () => {
    loadLogFiles();
    if (selectedFile) loadLogContent(selectedFile);
  };

  return (
    <div className="syslog-page">
      <div className="syslog-header">
        <div>
          <h1>System Logs</h1>
          <p className="syslog-subtitle">View, filter, and export application logs for debugging.</p>
        </div>
        <div className="syslog-actions">
          <button onClick={refresh} className="btn-ghost">Refresh</button>
          <button onClick={handleDownloadBundle} className="btn-primary" disabled={bundleLoading}>
            {bundleLoading ? 'Generating…' : '⬇ Download Diagnostic Bundle'}
          </button>
        </div>
      </div>

      {error && <div className="syslog-error">{error}</div>}

      <div className="syslog-layout">
        {/* File list sidebar */}
        <div className="syslog-file-list">
          <h3>Log Files</h3>
          {logFiles.length === 0 && <p className="syslog-empty">No log files found</p>}
          {logFiles.map((f) => (
            <div
              key={f.name}
              className={`syslog-file-item${selectedFile === f.name ? ' active' : ''}`}
              onClick={() => loadLogContent(f.name)}
            >
              <div className="syslog-file-name">{f.name}</div>
              <div className="syslog-file-meta">
                {formatBytes(f.size_bytes)} · {new Date(f.modified).toLocaleString()}
              </div>
              <button
                className="syslog-download-btn"
                onClick={(e) => { e.stopPropagation(); handleDownloadFile(f.name); }}
                title="Download raw file"
              >
                ⬇
              </button>
            </div>
          ))}
        </div>

        {/* Log viewer */}
        <div className="syslog-viewer">
          <div className="syslog-viewer-controls">
            <label>
              Lines:
              <select value={tailLines} onChange={(e) => setTailLines(Number(e.target.value))}>
                <option value={50}>Last 50</option>
                <option value={200}>Last 200</option>
                <option value={500}>Last 500</option>
                <option value={1000}>Last 1000</option>
                <option value={5000}>Last 5000</option>
              </select>
            </label>
            <label>
              Level:
              <select value={levelFilter} onChange={(e) => setLevelFilter(e.target.value)}>
                <option value="">All</option>
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </label>
            <button
              onClick={() => selectedFile && loadLogContent(selectedFile)}
              disabled={!selectedFile || loading}
            >
              Apply
            </button>
          </div>
          <pre className="syslog-content">
            {loading ? 'Loading…' : logContent || (selectedFile ? '(empty)' : 'Select a log file')}
          </pre>
        </div>
      </div>

      <div className="syslog-footer">
        <p>
          <strong>Sharing logs:</strong> Click "Download Diagnostic Bundle" to generate a ZIP
          containing all log files, session summaries, and system info. Share this with developers
          when reporting issues — no credentials or raw payloads are included.
        </p>
      </div>
    </div>
  );
}

export default SystemLogsPage;
