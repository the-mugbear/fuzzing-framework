import { useEffect, useState } from 'react';
import EditableFieldTable, { FieldValue } from '../components/EditableFieldTable';
import LivePacketBuilder from '../components/LivePacketBuilder';
import FieldMutationPanel from '../components/FieldMutationPanel';
import AdvancedMutations from '../components/AdvancedMutations';
import MutationTimeline, { MutationStackEntry } from '../components/MutationTimeline';
import DiffHexViewer from '../components/DiffHexViewer';
import Tooltip from '../components/Tooltip';
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
  mutationStack: MutationStackEntry[];
  fields: FieldValue[];
  hexData: string;
  totalBytes: number;
  response: TestExecuteResponse;
  description: string;
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

  // New state for mutation tracking
  const [baseHexData, setBaseHexData] = useState(''); // Original seed hex
  const [mutationStack, setMutationStack] = useState<MutationStackEntry[]>([]);
  const [redoStack, setRedoStack] = useState<MutationStackEntry[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [statusMessage, setStatusMessage] = useState<string>('');
  const [showDiffView, setShowDiffView] = useState(false);
  const [diffViewEntry, setDiffViewEntry] = useState<MutationStackEntry | null>(null);
  const [selectedField, setSelectedField] = useState<string | null>(null);

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
        return api<{ previews: any[] }>(
          `/api/plugins/${selectedProtocol}/preview`,
          {
            method: 'POST',
            body: JSON.stringify({ mode: 'seeds', count: 10 }),
          }
        ).then((previewData) => {
          setSeedCount(previewData.previews.length);
          setSeedIndex(0);
        });
      })
      .catch((err) => {
        setError(err.message);
        setPlugin(null);
      })
      .finally(() => setLoading(false));
  }, [selectedProtocol]);

  // Load base message when protocol or seed index changes
  useEffect(() => {
    if (!selectedProtocol || seedIndex < 0) return;
    loadSeed();
  }, [selectedProtocol, seedIndex]);

  const loadSeed = async () => {
    setLoading(true);
    setError(null);
    setResponse(null);
    setMutationStack([]);
    setRedoStack([]);
    setShowDiffView(false);

    try {
      const previewResponse = await api<{ previews: any[] }>(
        `/api/plugins/${selectedProtocol}/preview`,
        {
          method: 'POST',
          body: JSON.stringify({ mode: 'seeds', count: seedIndex + 1 }),
        }
      );

      if (previewResponse.previews.length <= seedIndex) {
        throw new Error(`Base message ${seedIndex} not found`);
      }

      const seedPreview = previewResponse.previews[seedIndex];

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
        setBaseHexData(seedPreview.hex_dump);
        setTotalBytes(parseResponse.total_bytes);
        setStatusMessage(`OK Loaded base message ${seedIndex + 1}`);
        setTimeout(() => setStatusMessage(''), 3000);
      } else {
        setError(parseResponse.error || 'Failed to parse base message');
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Calculate which bytes changed between two hex strings
  const calculateDiff = (beforeHex: string, afterHex: string): number[] => {
    const beforeBytes = beforeHex.match(/.{1,2}/g) || [];
    const afterBytes = afterHex.match(/.{1,2}/g) || [];
    const maxLen = Math.max(beforeBytes.length, afterBytes.length);
    const changedOffsets: number[] = [];

    for (let i = 0; i < maxLen; i++) {
      if (beforeBytes[i] !== afterBytes[i]) {
        changedOffsets.push(i);
      }
    }

    return changedOffsets;
  };

  const handleFieldChange = async (fieldName: string, newValue: any) => {
    const beforeHex = hexData;
    const updatedFields = fields.map((f) =>
      f.name === fieldName ? { ...f, value: newValue } : f
    );
    setFields(updatedFields);

    await rebuildPacket(updatedFields);

    // After rebuild, create mutation stack entry
    setTimeout(() => {
      const afterHex = hexData;
      const changedOffsets = calculateDiff(beforeHex, afterHex);

      const stackEntry: MutationStackEntry = {
        id: Date.now().toString(),
        type: 'manual_edit',
        fieldChanged: fieldName,
        timestamp: new Date(),
        bytesChanged: changedOffsets,
        beforeHex: beforeHex,
        afterHex: afterHex,
        description: `Edited field: ${fieldName}`,
      };

      setMutationStack([...mutationStack, stackEntry]);
      setRedoStack([]); // Clear redo stack on new action
      setStatusMessage(`OK Updated field: ${fieldName}`);
      setTimeout(() => setStatusMessage(''), 3000);
    }, 100);
  };

  const rebuildPacket = async (updatedFields: FieldValue[]) => {
    setBuilding(true);
    setBuildError(null);

    try {
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

    const beforeHex = hexData;

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

        // Calculate diff
        const changedOffsets = calculateDiff(beforeHex, mutateResponse.mutated_hex);

        // Create mutation stack entry
        const stackEntry: MutationStackEntry = {
          id: Date.now().toString(),
          type: 'mutator',
          mutator: mutatorName,
          timestamp: new Date(),
          bytesChanged: changedOffsets,
          beforeHex: beforeHex,
          afterHex: mutateResponse.mutated_hex,
          description:
            changedOffsets.length === 0
              ? `${mutatorName} (no changes)`
              : `Changed ${changedOffsets.length} byte${
                  changedOffsets.length !== 1 ? 's' : ''
                }`,
        };

        setMutationStack([...mutationStack, stackEntry]);
        setRedoStack([]); // Clear redo stack on new action
        setShowDiffView(true);
        setDiffViewEntry(stackEntry);
        setStatusMessage(`OK Applied ${mutatorName} mutation to full message`);
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

  const handleFieldMutation = async (
    fieldName: string,
    mutator: string,
    strategy?: string
  ) => {
    setLoading(true);
    setError(null);
    setResponse(null);

    const beforeHex = hexData;

    try {
      const response = await api<any>(
        `/api/plugins/${selectedProtocol}/mutate_field`,
        {
          method: 'POST',
          body: JSON.stringify({
            seed_index: seedIndex,
            field_name: fieldName,
            mutator: mutator,
            strategy: strategy,
          }),
        }
      );

      if (response.success) {
        setHexData(response.mutated_hex);
        setTotalBytes(response.mutated_bytes);
        setFields(response.fields);

        // Calculate diff
        const changedOffsets = calculateDiff(beforeHex, response.mutated_hex);

        // Create description
        let description = '';
        if (strategy) {
          description = `${fieldName}: ${strategy} (${changedOffsets.length} byte${
            changedOffsets.length !== 1 ? 's' : ''
          } changed)`;
        } else {
          description = `${fieldName}: ${mutator} (${changedOffsets.length} byte${
            changedOffsets.length !== 1 ? 's' : ''
          } changed)`;
        }

        // Create mutation stack entry
        const stackEntry: MutationStackEntry = {
          id: Date.now().toString(),
          type: 'mutator',
          mutator: strategy || mutator,
          fieldChanged: fieldName,
          timestamp: new Date(),
          bytesChanged: changedOffsets,
          beforeHex: beforeHex,
          afterHex: response.mutated_hex,
          description: description,
        };

        setMutationStack([...mutationStack, stackEntry]);
        setRedoStack([]); // Clear redo stack on new action
        setShowDiffView(true);
        setDiffViewEntry(stackEntry);
        setStatusMessage(`OK Mutated field: ${fieldName}`);
        setTimeout(() => setStatusMessage(''), 3000);
      } else {
        setError(response.error || 'Field mutation failed');
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  const handleUndo = () => {
    if (mutationStack.length === 0) return;

    const lastEntry = mutationStack[mutationStack.length - 1];
    const newStack = mutationStack.slice(0, -1);

    setMutationStack(newStack);
    setRedoStack([...redoStack, lastEntry]);

    // Restore to previous state
    if (newStack.length === 0) {
      // Restore to base message
      loadSeed();
      setShowDiffView(false);
    } else {
      const prevEntry = newStack[newStack.length - 1];
      setHexData(prevEntry.afterHex);
      parseHexData(prevEntry.afterHex);
      setDiffViewEntry(prevEntry);
    }

    setStatusMessage(`Undid ${lastEntry.mutator || 'edit'}`);
    setTimeout(() => setStatusMessage(''), 3000);
  };

  const handleRedo = () => {
    if (redoStack.length === 0) return;

    const nextEntry = redoStack[redoStack.length - 1];
    const newRedoStack = redoStack.slice(0, -1);

    setMutationStack([...mutationStack, nextEntry]);
    setRedoStack(newRedoStack);

    setHexData(nextEntry.afterHex);
    parseHexData(nextEntry.afterHex);
    setShowDiffView(true);
    setDiffViewEntry(nextEntry);

    setStatusMessage(`Redid ${nextEntry.mutator || 'edit'}`);
    setTimeout(() => setStatusMessage(''), 3000);
  };

  const handleRemoveMutation = async (mutationId: string) => {
    const index = mutationStack.findIndex((m) => m.id === mutationId);
    if (index === -1) return;

    const newStack = mutationStack.filter((m) => m.id !== mutationId);
    setMutationStack(newStack);
    setRedoStack([]); // Clear redo stack

    // Restore to base and replay remaining mutations
    await loadSeed();

    // Note: Full replay would require API support for applying mutations sequentially
    // For now, we'll just reset to base message
    setStatusMessage('Mutation removed - reset to base message');
    setTimeout(() => setStatusMessage(''), 3000);
  };

  const handleClearAll = () => {
    setMutationStack([]);
    setRedoStack([]);
    setShowDiffView(false);
    loadSeed();
  };

  const handleViewDiff = (entry: MutationStackEntry) => {
    setShowDiffView(true);
    setDiffViewEntry(entry);
  };

  const parseHexData = async (hex: string) => {
    try {
      const parseResponse = await api<ParseResponse>(
        `/api/plugins/${selectedProtocol}/parse`,
        {
          method: 'POST',
          body: JSON.stringify({
            packet: hex,
            format: 'hex',
          }),
        }
      );

      if (parseResponse.success) {
        setFields(parseResponse.fields);
        setTotalBytes(parseResponse.total_bytes);
      }
    } catch (err) {
      console.error('Failed to parse hex data:', err);
    }
  };

  const handleSend = async () => {
    setSending(true);
    setError(null);
    setResponse(null);

    try {
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

      // Build description
      const mutationDesc =
        mutationStack.length === 0
          ? 'No mutations'
          : mutationStack.map((m) => m.mutator || 'edit').join(' + ');

      // Add to history
      const historyEntry: HistoryEntry = {
        id: Date.now().toString(),
        timestamp: new Date(),
        seedIndex: seedIndex,
        mutationStack: [...mutationStack],
        fields: [...fields],
        hexData: hexData,
        totalBytes: totalBytes,
        response: data,
        description: `Base ${seedIndex + 1}${
          mutationStack.length > 0 ? ` + ${mutationDesc}` : ''
        }`,
      };
      setHistory((prev) => [historyEntry, ...prev].slice(0, 10)); // Keep last 10

      setStatusMessage(`OK Sent ${totalBytes} bytes to ${targetHost}:${targetPort}`);
      setTimeout(() => setStatusMessage(''), 3000);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSending(false);
    }
  };

  const handleRestoreHistory = (entry: HistoryEntry) => {
    setSeedIndex(entry.seedIndex);
    setMutationStack(entry.mutationStack);
    setFields(entry.fields);
    setHexData(entry.hexData);
    setTotalBytes(entry.totalBytes);
    setRedoStack([]);

    if (entry.mutationStack.length > 0) {
      const lastMutation = entry.mutationStack[entry.mutationStack.length - 1];
      setShowDiffView(true);
      setDiffViewEntry(lastMutation);
    } else {
      setShowDiffView(false);
    }

    setStatusMessage(`OK Restored: ${entry.description}`);
    setTimeout(() => setStatusMessage(''), 3000);
  };

  const handleByteHover = (offset: number | null) => {
    if (offset === null) {
      setHoveredField(null);
      return;
    }

    const field = fields.find((f) => offset >= f.offset && offset < f.offset + f.size);
    setHoveredField(field?.name || null);
  };

  const getBaseMessageName = () => {
    return `${selectedProtocol} base message ${seedIndex + 1}`;
  };

  return (
    <div className="mutation-workbench-page">
      <div className="workbench-header card">
        <div>
          <p className="eyebrow">Interactive Testing</p>
          <h2>Mutation Workbench</h2>
          <p>
            Craft and mutate protocol messages, verify mutation behavior, and test against live
            targets.
          </p>
        </div>
      </div>

      {error && (
        <div className="error-banner card">
          <strong>Error:</strong> {error}
        </div>
      )}

      {statusMessage && <div className="status-banner card">{statusMessage}</div>}

      <div className="workbench-controls card">
        <div className="control-row">
          <div className="control-group">
            <label htmlFor="protocol">
              <span className="label-text">
                Protocol
                <Tooltip content="Select a protocol plugin that defines message structure and validation rules." />
              </span>
            </label>
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
              <span className="label-text">
                Base Message ({seedIndex + 1} of {seedCount})
                <Tooltip content="Valid protocol examples to start from. These are defined in the protocol plugin and serve as mutation seeds." />
              </span>
            </label>
            <div className="seed-selector">
              <button
                type="button"
                onClick={() => setSeedIndex(Math.max(0, seedIndex - 1))}
                disabled={seedIndex === 0 || loading}
                className="seed-nav-btn"
              >
                Prev
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
                Next
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
        <div className="workbench-content">
          {/* Timeline Sidebar */}
          <div className="timeline-sidebar">
            <MutationTimeline
              stack={mutationStack}
              baseName={getBaseMessageName()}
              onRemoveMutation={handleRemoveMutation}
              onClearAll={handleClearAll}
              onUndo={handleUndo}
              onRedo={handleRedo}
              onViewDiff={handleViewDiff}
              canUndo={mutationStack.length > 0}
              canRedo={redoStack.length > 0}
            />
          </div>

          {/* Main Content */}
          <div className="main-content">
            <div className="workbench-section card">
              <h3>Editable Fields</h3>
              <p className="section-hint">
                Click a row to select a field for mutation. Click "Edit" to manually modify values. Size fields update automatically.
              </p>
              <EditableFieldTable
                fields={fields}
                onFieldChange={handleFieldChange}
                hoveredField={hoveredField}
                onFieldHover={setHoveredField}
                selectedField={selectedField}
                onFieldSelect={setSelectedField}
              />
            </div>

            {showDiffView && diffViewEntry ? (
              <div className="workbench-section card">
                <DiffHexViewer
                  originalHex={diffViewEntry.beforeHex}
                  mutatedHex={diffViewEntry.afterHex}
                  fields={fields}
                  mutationSummary={{
                    bytesChanged: diffViewEntry.bytesChanged.length,
                    offsets: diffViewEntry.bytesChanged,
                    mutator: diffViewEntry.mutator || 'Manual Edit',
                  }}
                  onByteHover={handleByteHover}
                />
              </div>
            ) : (
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
            )}

            <div className="workbench-section card">
              <FieldMutationPanel
                selectedField={fields.find(f => f.name === selectedField) || null}
                onMutate={handleFieldMutation}
                disabled={loading}
              />
            </div>

            <div className="workbench-section">
              <AdvancedMutations
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
                <h3>Test History (Last 10)</h3>
                <p className="section-hint">Click "Restore" to load a previous test case.</p>
                <div className="history-list">
                  {history.map((entry) => (
                    <div key={entry.id} className="history-item">
                      <div className="history-header">
                        <span className="history-time">
                          {entry.timestamp.toLocaleTimeString()}
                        </span>
                        <span className="history-desc">{entry.description}</span>
                        <button
                          type="button"
                          onClick={() => handleRestoreHistory(entry)}
                          className="restore-btn"
                        >
                          Restore
                        </button>
                      </div>
                      <div className="history-hex">
                        {entry.hexData.substring(0, 64)}
                        {entry.hexData.length > 64 && '...'}
                      </div>
                      <div className="history-result">
                        <span className={entry.response.success ? 'success' : 'failure'}>
                          {entry.response.success ? 'OK' : 'FAIL'}
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
          </div>
        </div>
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
