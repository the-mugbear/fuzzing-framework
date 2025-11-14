import { useEffect, useState } from 'react';
import EditableFieldTable, { FieldValue } from '../components/EditableFieldTable';
import LivePacketBuilder from '../components/LivePacketBuilder';
import MutationControls from '../components/MutationControls';
import { api, API_BASE } from '../services/api';
import './MutationWorkbenchPage.css';

interface Plugin {
  name: string;
  data_model: {
    blocks: Block[];
  };
}

interface Block {
  name: string;
  type: string;
  size?: number;
  default?: any;
  mutable?: boolean;
  is_size_field?: boolean;
  size_of?: string;
}

interface ParseResponse {
  success: boolean;
  fields: FieldValue[];
  total_bytes: number;
  error?: string;
}

interface BuildResponse {
  success: boolean;
  hex_data: string;
  total_bytes: number;
  error?: string;
}

interface MutateResponse {
  success: boolean;
  original_hex: string;
  mutated_hex: string;
  mutator_used: string;
  original_bytes: number;
  mutated_bytes: number;
  fields: FieldValue[];
  error?: string;
}

interface TestExecuteResponse {
  success: boolean;
  sent_bytes: number;
  response_bytes: number;
  response_hex?: string;
  duration_ms: number;
  error?: string;
}

interface HistoryEntry {
  id: string;
  timestamp: Date;
  seedIndex: number;
  mutationsApplied: string[];
  hexPreview: string;
  totalBytes: number;
  response: TestExecuteResponse;
}

function MutationWorkbenchPage() {
  const [protocols, setProtocols] = useState<string[]>([]);
  const [selectedProtocol, setSelectedProtocol] = useState('');
  const [plugin, setPlugin] = useState<Plugin | null>(null);
  const [seedIndex, setSeedIndex] = useState(0);
  const [seedCount, setSeedCount] = useState(0);
  const [fields, setFields] = useState<FieldValue[]>([]);
  const [hexData, setHexData] = useState('');
  const [totalBytes, setTotalBytes] = useState(0);
  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [building, setBuilding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [targetHost, setTargetHost] = useState('target');
  const [targetPort, setTargetPort] = useState(9999);
  const [sending, setSending] = useState(false);
  const [response, setResponse] = useState<TestExecuteResponse | null>(null);

  // State tracking and history
  const [currentState, setCurrentState] = useState<string>('No packet loaded');
  const [mutationsApplied, setMutationsApplied] = useState<string[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [statusMessage, setStatusMessage] = useState<string>('');

  // Load available protocols
  useEffect(() => {
    api<string[]>('/api/plugins')
      .then((names) => {
        setProtocols(names);
        if (names.length > 0) {
          setSelectedProtocol(names[0]);
        }
      })
      .catch((err) => setError(err.message));
  }, []);

  // Load selected protocol
  useEffect(() => {
    if (!selectedProtocol) return;

    setLoading(true);
    setError(null);

    api<Plugin>(`/api/plugins/${selectedProtocol}`)
      .then((p) => {
        setPlugin(p);
        // Count seeds from data model (seeds are base64 encoded in the plugin response)
        // Request a small preview to get actual count
        return api<{ previews: any[] }>(
          `/api/plugins/${selectedProtocol}/preview`,
          {
            method: 'POST',
            body: JSON.stringify({ mode: 'seeds', count: 10 }),
          }
        ).then((previewData) => {
          // If we got 10, there might be more, but we'll use 10 as a reasonable max for the workbench
          setSeedCount(previewData.previews.length);
          setSeedIndex(0); // Reset to first seed
        });
      })
      .catch((err) => {
        setError(err.message);
        setPlugin(null);
      })
      .finally(() => setLoading(false));
  }, [selectedProtocol]);

  // Load seed when protocol or seed index changes
  useEffect(() => {
    if (!selectedProtocol || seedIndex < 0) return;

    loadSeed();
  }, [selectedProtocol, seedIndex]);

  const loadSeed = async () => {
    setLoading(true);
    setError(null);
    setResponse(null);

    try {
      // Get preview to obtain seed data
      const previewResponse = await api<{ previews: any[] }>(
        `/api/plugins/${selectedProtocol}/preview`,
        {
          method: 'POST',
          body: JSON.stringify({ mode: 'seeds', count: seedIndex + 1 }),
        }
      );

      if (previewResponse.previews.length <= seedIndex) {
        throw new Error(`Seed ${seedIndex} not found`);
      }

      const seedPreview = previewResponse.previews[seedIndex];

      // Parse the seed hex to get fields
      const parseResponse = await api<ParseResponse>(
        `/api/plugins/${selectedProtocol}/parse`,
        {
          method: 'POST',
          body: JSON.stringify({
            packet: seedPreview.hex_dump,
            format: 'hex',
          }),
        }
      );

      if (parseResponse.success) {
        setFields(parseResponse.fields);
        setHexData(seedPreview.hex_dump);
        setTotalBytes(parseResponse.total_bytes);
        setMutationsApplied([]);
        setCurrentState(`Seed ${seedIndex + 1} of ${seedCount} (unmodified)`);
        setStatusMessage(`✓ Loaded seed ${seedIndex + 1}`);
        setTimeout(() => setStatusMessage(''), 3000);
      } else {
        setError(parseResponse.error || 'Failed to parse seed');
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleFieldChange = async (fieldName: string, newValue: any) => {
    // Update the field value
    const updatedFields = fields.map((f) =>
      f.name === fieldName ? { ...f, value: newValue } : f
    );
    setFields(updatedFields);

    // Track manual edit
    if (!mutationsApplied.includes('manual_edit')) {
      setMutationsApplied([...mutationsApplied, 'manual_edit']);
    }
    setCurrentState(`Seed ${seedIndex + 1} + manual edits`);
    setStatusMessage(`✓ Updated field: ${fieldName}`);
    setTimeout(() => setStatusMessage(''), 3000);

    // Rebuild packet with new field values
    await rebuildPacket(updatedFields);
  };

  const rebuildPacket = async (updatedFields: FieldValue[]) => {
    setBuilding(true);
    setBuildError(null);

    try {
      // Convert fields array to field dictionary
      const fieldDict: Record<string, any> = {};
      updatedFields.forEach((f) => {
        fieldDict[f.name] = f.value;
      });

      const buildResponse = await api<BuildResponse>(
        `/api/plugins/${selectedProtocol}/build`,
        {
          method: 'POST',
          body: JSON.stringify({ fields: fieldDict }),
        }
      );

      if (buildResponse.success) {
        setHexData(buildResponse.hex_data);
        setTotalBytes(buildResponse.total_bytes);

        // Re-parse to update field hex values and offsets
        const parseResponse = await api<ParseResponse>(
          `/api/plugins/${selectedProtocol}/parse`,
          {
            method: 'POST',
            body: JSON.stringify({
              packet: buildResponse.hex_data,
              format: 'hex',
            }),
          }
        );

        if (parseResponse.success) {
          setFields(parseResponse.fields);
        }
      } else {
        setBuildError(buildResponse.error || 'Failed to build packet');
      }
    } catch (err) {
      setBuildError((err as Error).message);
    } finally {
      setBuilding(false);
    }
  };

  const handleMutate = async (mutatorName: string) => {
    setLoading(true);
    setError(null);
    setResponse(null);

    try {
      const mutateResponse = await api<MutateResponse>(
        `/api/plugins/${selectedProtocol}/mutate_with`,
        {
          method: 'POST',
          body: JSON.stringify({
            seed_index: seedIndex,
            mutator: mutatorName,
          }),
        }
      );

      if (mutateResponse.success) {
        setHexData(mutateResponse.mutated_hex);
        setTotalBytes(mutateResponse.mutated_bytes);
        setFields(mutateResponse.fields);

        // Track mutation
        const newMutations = [...mutationsApplied.filter(m => m !== 'manual_edit'), mutatorName];
        setMutationsApplied(newMutations);
        setCurrentState(`Seed ${seedIndex + 1} + ${mutatorName}`);
        setStatusMessage(`✓ Applied ${mutatorName} mutation`);
        setTimeout(() => setStatusMessage(''), 3000);
      } else {
        setError(mutateResponse.error || 'Mutation failed');
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleSend = async () => {
    setSending(true);
    setError(null);
    setResponse(null);

    try {
      // Convert hex to base64
      const hexBytes = hexData.match(/.{1,2}/g)?.map((byte) => parseInt(byte, 16)) || [];
      const byteArray = new Uint8Array(hexBytes);
      let binary = '';
      byteArray.forEach((b) => {
        binary += String.fromCharCode(b);
      });
      const base64Payload = btoa(binary);

      const executeResponse = await fetch(`${API_BASE}/api/tests/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          protocol: selectedProtocol,
          target_host: targetHost,
          target_port: targetPort,
          payload: base64Payload,
          execution_mode: 'core',
        }),
      });

      const data = await executeResponse.json();

      if (!executeResponse.ok) {
        throw new Error(data.detail || 'Request failed');
      }

      setResponse(data);

      // Add to history
      const historyEntry: HistoryEntry = {
        id: Date.now().toString(),
        timestamp: new Date(),
        seedIndex: seedIndex,
        mutationsApplied: [...mutationsApplied],
        hexPreview: hexData.substring(0, 64), // First 32 bytes
        totalBytes: totalBytes,
        response: data,
      };
      setHistory((prev) => [historyEntry, ...prev].slice(0, 5)); // Keep last 5

      setStatusMessage(`✓ Sent ${totalBytes} bytes to ${targetHost}:${targetPort}`);
      setTimeout(() => setStatusMessage(''), 3000);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  };

  const handleByteHover = (offset: number | null) => {
    if (offset === null) {
      setHoveredField(null);
      return;
    }

    // Find which field contains this offset
    const field = fields.find((f) => offset >= f.offset && offset < f.offset + f.size);
    setHoveredField(field?.name || null);
  };

  return (
    <div className="mutation-workbench-page">
      <div className="workbench-header card">
        <div>
          <p className="eyebrow">Interactive Testing</p>
          <h2>Mutation Workbench</h2>
          <p>
            Manually craft and mutate packets, test mutations, and send to target for real-time
            feedback.
          </p>
        </div>
      </div>

      {error && (
        <div className="error-banner card">
          <strong>Error:</strong> {error}
        </div>
      )}

      {statusMessage && (
        <div className="status-banner card">
          {statusMessage}
        </div>
      )}

      <div className="current-state-card card">
        <div className="state-indicator">
          <div>
            <strong>Current Packet State:</strong> {currentState}
          </div>
          {mutationsApplied.length > 0 && (
            <div className="mutations-applied">
              <span>Mutations: </span>
              {mutationsApplied.map((m, i) => (
                <span key={i} className="mutation-tag">{m}</span>
              ))}
            </div>
          )}
        </div>
        <div className="state-info">
          <span>{totalBytes} bytes will be sent when you click "Send to Target"</span>
        </div>
      </div>

      <div className="workbench-controls card">
        <div className="control-row">
          <div className="control-group">
            <label htmlFor="protocol">Protocol</label>
            <select
              id="protocol"
              value={selectedProtocol}
              onChange={(e) => setSelectedProtocol(e.target.value)}
              disabled={loading}
            >
              {protocols.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          <div className="control-group">
            <label htmlFor="seed">
              Seed ({seedIndex + 1} of {seedCount})
            </label>
            <div className="seed-selector">
              <button
                type="button"
                onClick={() => setSeedIndex(Math.max(0, seedIndex - 1))}
                disabled={seedIndex === 0 || loading}
                className="seed-nav-btn"
              >
                ←
              </button>
              <input
                id="seed"
                type="number"
                min={0}
                max={seedCount - 1}
                value={seedIndex}
                onChange={(e) => setSeedIndex(Number(e.target.value))}
                disabled={loading}
                className="seed-input"
              />
              <button
                type="button"
                onClick={() => setSeedIndex(Math.min(seedCount - 1, seedIndex + 1))}
                disabled={seedIndex >= seedCount - 1 || loading}
                className="seed-nav-btn"
              >
                →
              </button>
              <button
                type="button"
                onClick={loadSeed}
                disabled={loading}
                className="reload-btn"
              >
                Reload
              </button>
            </div>
          </div>
        </div>

        <div className="control-row">
          <div className="control-group">
            <label htmlFor="target-host">Target Host</label>
            <input
              id="target-host"
              value={targetHost}
              onChange={(e) => setTargetHost(e.target.value)}
              disabled={sending}
            />
          </div>

          <div className="control-group">
            <label htmlFor="target-port">Target Port</label>
            <input
              id="target-port"
              type="number"
              value={targetPort}
              onChange={(e) => setTargetPort(Number(e.target.value))}
              disabled={sending}
            />
          </div>

          <div className="control-group send-group">
            <label>&nbsp;</label>
            <button
              type="button"
              onClick={handleSend}
              disabled={sending || !hexData}
              className="send-btn"
            >
              {sending ? 'Sending...' : 'Send to Target'}
            </button>
          </div>
        </div>
      </div>

      {fields.length > 0 && (
        <>
          <div className="workbench-section card">
            <h3>Editable Fields</h3>
            <p className="section-hint">
              Click "Edit" to modify field values. Computed fields (like size_of) update
              automatically.
            </p>
            <EditableFieldTable
              fields={fields}
              onFieldChange={handleFieldChange}
              hoveredField={hoveredField}
              onFieldHover={setHoveredField}
            />
          </div>

          <div className="workbench-section card">
            <LivePacketBuilder
              hexData={hexData}
              fields={fields}
              totalBytes={totalBytes}
              onByteHover={handleByteHover}
              building={building}
              error={buildError}
            />
          </div>

          <div className="workbench-section card">
            <h3>Apply Mutations</h3>
            <p className="section-hint">
              Apply a mutation strategy to the current seed and see the result.
            </p>
            <MutationControls
              onMutate={handleMutate}
              disabled={loading}
              seedCount={seedCount}
            />
          </div>

          {response && (
            <div className="workbench-section card response-section">
              <h3>Target Response</h3>
              <div className="response-details">
                <div className="response-meta">
                  <div>
                    <span>Sent</span>
                    <strong>{response.sent_bytes} bytes</strong>
                  </div>
                  <div>
                    <span>Received</span>
                    <strong>{response.response_bytes} bytes</strong>
                  </div>
                  <div>
                    <span>Duration</span>
                    <strong>{response.duration_ms.toFixed(2)} ms</strong>
                  </div>
                </div>
                {response.response_hex && (
                  <div className="response-hex">
                    <label>Response Data (Hex)</label>
                    <pre>{response.response_hex}</pre>
                  </div>
                )}
              </div>
            </div>
          )}

          {history.length > 0 && (
            <div className="workbench-section card history-section">
              <h3>Send History (Last 5)</h3>
              <p className="section-hint">
                Click a history entry to reload that packet state.
              </p>
              <div className="history-list">
                {history.map((entry) => (
                  <div
                    key={entry.id}
                    className="history-item"
                    onClick={() => {
                      // Reload this packet (note: this is simplified - in production you'd restore full state)
                      setStatusMessage(`History entry from ${entry.timestamp.toLocaleTimeString()} cannot be fully restored yet`);
                      setTimeout(() => setStatusMessage(''), 3000);
                    }}
                  >
                    <div className="history-header">
                      <span className="history-time">
                        {entry.timestamp.toLocaleTimeString()}
                      </span>
                      <span className="history-seed">Seed {entry.seedIndex + 1}</span>
                      {entry.mutationsApplied.length > 0 && (
                        <span className="history-mutations">
                          {entry.mutationsApplied.join(' + ')}
                        </span>
                      )}
                    </div>
                    <div className="history-hex">
                      {entry.hexPreview}
                      {entry.hexPreview.length < entry.totalBytes * 2 && '...'}
                    </div>
                    <div className="history-result">
                      <span className={entry.response.success ? 'success' : 'failure'}>
                        {entry.response.success ? '✓' : '✗'}
                      </span>
                      <span>{entry.totalBytes} bytes sent</span>
                      <span>{entry.response.response_bytes} bytes received</span>
                      <span>{entry.response.duration_ms.toFixed(2)} ms</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {loading && (
        <div className="loading-overlay">
          <p>Loading...</p>
        </div>
      )}
    </div>
  );
}

export default MutationWorkbenchPage;
