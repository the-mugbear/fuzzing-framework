import { FormEvent, useEffect, useState } from 'react';
import './OneOffTestPage.css';
import { api, API_BASE } from '../services/api';

type ExecutionMode = 'core' | 'agent';

interface ProtocolBlock {
  name: string;
  type: string;
  default?: unknown;
  size?: number;
  max_size?: number;
  mutable?: boolean;
  behavior?: Record<string, unknown>;
  is_size_field?: boolean;
  is_checksum?: boolean;
  checksum_algorithm?: string;
}

interface BuildResponse {
  success: boolean;
  hex_data: string;
  total_bytes: number;
  error?: string;
}

const base64FromBytes = (bytes: Uint8Array) => {
  let binary = '';
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
};

const bytesFromHex = (hex: string) => {
  const clean = hex.replace(/\s+/g, '');
  if (!clean.length) return new Uint8Array();
  const pairs = clean.match(/.{1,2}/g) || [];
  return new Uint8Array(pairs.map((byte) => parseInt(byte, 16)));
};

const decodeBase64ToText = (value: string) => {
  try {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i += 1) {
      bytes[i] = binary.charCodeAt(i);
    }
    const text = new TextDecoder('utf-8').decode(bytes);
    if (text.includes('\uFFFD')) {
      return '';
    }
    return text;
  } catch (error) {
    return '';
  }
};

const isAutoField = (block: ProtocolBlock) =>
  Boolean(block.is_size_field || block.is_checksum || block.checksum_algorithm || block.behavior);

const isNumericField = (block: ProtocolBlock) =>
  block.type.startsWith('uint') || block.type.startsWith('int') || block.type === 'bits';

function OneOffTestPage() {
  const [protocols, setProtocols] = useState<string[]>([]);
  const [protocol, setProtocol] = useState('');
  const [host, setHost] = useState('target');
  const [port, setPort] = useState(9999);
  const [mode, setMode] = useState<ExecutionMode>('core');
  const [result, setResult] = useState<string>('');
  const [busy, setBusy] = useState(false);
  const [blocks, setBlocks] = useState<ProtocolBlock[]>([]);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({});
  const [buildHex, setBuildHex] = useState('');
  const [buildBytes, setBuildBytes] = useState(0);
  const [buildError, setBuildError] = useState('');

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
        const protocolBlocks = plugin.data_model?.blocks || [];
        setBlocks(protocolBlocks);
        const nextValues: Record<string, string> = {};
        protocolBlocks.forEach((block: ProtocolBlock) => {
          if (isAutoField(block)) {
            nextValues[block.name] = '';
            return;
          }
          if (block.default === undefined || block.default === null) {
            nextValues[block.name] = '';
            return;
          }
          if (block.type === 'bytes' && typeof block.default === 'string') {
            nextValues[block.name] = decodeBase64ToText(block.default);
            return;
          }
          nextValues[block.name] = String(block.default);
        });
        setFieldValues(nextValues);
        setBuildHex('');
        setBuildBytes(0);
        setBuildError('');
      })
      .catch(() => {
        setBlocks([]);
        setFieldValues({});
        setBuildHex('');
        setBuildBytes(0);
        setBuildError('');
      });
  }, [protocol]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setResult('');
    setBuildError('');
    try {
      const fields: Record<string, unknown> = {};
      blocks.forEach((block) => {
        if (isAutoField(block)) {
          return;
        }
        const rawValue = fieldValues[block.name];
        if (rawValue === undefined || rawValue.trim() === '') {
          return;
        }
        if (isNumericField(block)) {
          const trimmed = rawValue.trim();
          const parsed = trimmed.startsWith('0x') || trimmed.startsWith('0X')
            ? parseInt(trimmed, 16)
            : parseInt(trimmed, 10);
          if (Number.isNaN(parsed)) {
            throw new Error(`Invalid number for ${block.name}: ${rawValue}`);
          }
          fields[block.name] = parsed;
          return;
        }
        fields[block.name] = rawValue;
      });

      const buildResponse = await api<BuildResponse>(`/api/plugins/${protocol}/build`, {
        method: 'POST',
        body: JSON.stringify({ fields }),
      });

      if (!buildResponse.success) {
        throw new Error(buildResponse.error || 'Failed to build packet');
      }

      const packetBytes = bytesFromHex(buildResponse.hex_data);
      const packetBase64 = base64FromBytes(packetBytes);
      setBuildHex(buildResponse.hex_data);
      setBuildBytes(buildResponse.total_bytes);

      const body = {
        protocol,
        target_host: host,
        target_port: Number(port),
        payload: packetBase64,
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
      setBuildError((error as Error).message);
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
        <div className="oneoff-fields">
          <div className="oneoff-fields-header">
            <p className="eyebrow">Packet Fields</p>
            <p className="oneoff-fields-subtitle">Enter values for each protocol field (UTF-8 for bytes). Auto fields are locked.</p>
          </div>
          <div className="oneoff-fields-grid">
            {blocks.map((block) => {
              const disabled = isAutoField(block);
              const value = fieldValues[block.name] ?? '';
              const labelMeta = block.type ? `(${block.type})` : '';
              const placeholder = disabled ? 'auto' : block.type === 'bytes' ? 'UTF-8 bytes' : '';
              return (
                <label key={block.name} className={`oneoff-field ${disabled ? 'auto' : ''}`}>
                  <span className="field-label">
                    {block.name} <small>{labelMeta}</small>
                  </span>
                  {block.type === 'bytes' || block.type === 'string' ? (
                    <textarea
                      rows={2}
                      value={value}
                      placeholder={placeholder}
                      disabled={disabled}
                      onChange={(e) =>
                        setFieldValues((prev) => ({ ...prev, [block.name]: e.target.value }))
                      }
                    />
                  ) : (
                    <input
                      type="text"
                      value={value}
                      placeholder={placeholder}
                      disabled={disabled}
                      onChange={(e) =>
                        setFieldValues((prev) => ({ ...prev, [block.name]: e.target.value }))
                      }
                    />
                  )}
                </label>
              );
            })}
          </div>
          {(buildHex || buildError) && (
            <div className="oneoff-build-preview">
              <div>
                <h4>Built Payload</h4>
                {buildHex && <p className="oneoff-build-meta">{buildBytes} bytes</p>}
              </div>
              {buildError ? (
                <p className="oneoff-build-error">{buildError}</p>
              ) : (
                <pre>{buildHex}</pre>
              )}
            </div>
          )}
        </div>
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
