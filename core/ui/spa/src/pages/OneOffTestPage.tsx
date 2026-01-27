import { FormEvent, useEffect, useMemo, useState } from 'react';
import './OneOffTestPage.css';
import { api, API_BASE } from '../services/api';

type ExecutionMode = 'core' | 'agent';

const toBase64 = (input: string) => {
  const bytes = new TextEncoder().encode(input);
  let binary = '';
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
};

function OneOffTestPage() {
  const [protocols, setProtocols] = useState<string[]>([]);
  const [protocol, setProtocol] = useState('');
  const [host, setHost] = useState('target');
  const [port, setPort] = useState(9999);
  const [payload, setPayload] = useState('');
  const [mode, setMode] = useState<ExecutionMode>('core');
  const [result, setResult] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [structure, setStructure] = useState<string>('');

  useEffect(() => {
    api<string[]>(`/api/plugins`)
      .then((names) => {
        setProtocols(names);
        if (names.length) {
          setProtocol((prev) => prev || names[0]);
        }
      })
      .catch((err) => setResult(`Error loading plugins: ${err.message}`));
  }, []);

  useEffect(() => {
    if (!protocol) return;
    api<any>(`/api/plugins/${protocol}`)
      .then((plugin) => {
        const blocks = plugin.data_model?.blocks || [];
        const template = blocks.map((block: any) => `${block.name}: ${block.type}`).join('\n');
        setStructure(template);
      })
      .catch(() => setStructure(''));
  }, [protocol]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setResult('');
    try {
      const body = {
        protocol,
        target_host: host,
        target_port: Number(port),
        payload: toBase64(payload),
        execution_mode: mode,
      };
      const response = await fetch(`${API_BASE}/api/tests/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.detail || 'Request failed');
      }
      setResult(JSON.stringify(data, null, 2));
    } catch (error) {
      setResult(`Error: ${(error as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>One-Off Execution</h2>
      <p>Send a single payload to the target without starting a session.</p>
      <form className="oneoff-form" onSubmit={handleSubmit}>
        <label>
          Protocol
          <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
            {protocols.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Target Host
          <input value={host} onChange={(e) => setHost(e.target.value)} />
        </label>
        <label>
          Target Port
          <input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} />
        </label>
        <label>
          Execution Mode
          <select value={mode} onChange={(e) => setMode(e.target.value as ExecutionMode)}>
            <option value="core">Core</option>
            <option value="agent">Agent</option>
          </select>
        </label>
        <label>
          Payload (UTF-8)
          <textarea
            rows={6}
            value={payload}
            onChange={(e) => setPayload(e.target.value)}
          />
        </label>
        {structure && (
          <div className="structure-hint">
            <p className="eyebrow">Structure</p>
            <pre>{structure}</pre>
          </div>
        )}
        <button type="submit" disabled={busy}>
          {busy ? 'Sending...' : 'Execute'}
        </button>
      </form>
      {result && (
        <pre className="oneoff-result">{result}</pre>
      )}
    </div>
  );
}

export default OneOffTestPage;
