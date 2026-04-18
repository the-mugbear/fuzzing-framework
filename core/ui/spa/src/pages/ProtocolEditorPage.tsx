import { useState, useEffect, useCallback } from 'react';
import { api } from '../services/api';
import ProtocolStudioPage from './ProtocolStudioPage';
import PluginDebuggerPage from './PluginDebuggerPage';
import './ProtocolEditorPage.css';

interface ValidationIssue {
  severity: string;
  category: string;
  message: string;
  suggestion?: string;
}

export default function ProtocolEditorPage() {
  const [tab, setTab] = useState<'design' | 'source' | 'inspect'>('design');
  const [plugins, setPlugins] = useState<string[]>([]);
  const [selectedPlugin, setSelectedPlugin] = useState<string>('');
  const [sourceCode, setSourceCode] = useState('');
  const [sourceModified, setSourceModified] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [validationIssues, setValidationIssues] = useState<ValidationIssue[]>([]);
  const [validating, setValidating] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const loadPlugins = useCallback(async () => {
    try {
      const list = await api<string[]>('/api/plugins');
      setPlugins(list);
    } catch {}
  }, []);

  useEffect(() => {
    loadPlugins();
  }, [loadPlugins]);

  const loadSource = useCallback(async (name: string) => {
    if (!name) return;
    try {
      const data = await api<{ source_code: string }>(`/api/plugins/${name}/source`);
      setSourceCode(data.source_code);
      setSourceModified(false);
      setSaveResult(null);
      setValidationIssues([]);
    } catch (err: any) {
      setSourceCode(`# Failed to load source: ${err.message}`);
    }
  }, []);

  useEffect(() => {
    if (selectedPlugin && tab === 'source') {
      loadSource(selectedPlugin);
    }
  }, [selectedPlugin, tab, loadSource]);

  const handleSave = async () => {
    if (!sourceCode.trim()) return;
    setSaving(true);
    setSaveResult(null);
    try {
      // Derive name from selected plugin or extract from code
      const name = selectedPlugin || extractPluginName(sourceCode);
      if (!name) {
        setSaveResult({ ok: false, message: 'Could not determine plugin name. Select or create a plugin first.' });
        setSaving(false);
        return;
      }
      const result = await api<any>('/api/plugins/save', {
        method: 'POST',
        body: JSON.stringify({ name, code: sourceCode }),
      });
      if (result.saved) {
        setSaveResult({
          ok: true,
          message: result.reloaded
            ? `Saved and loaded "${result.plugin_name}" successfully.`
            : `Saved "${result.plugin_name}" but reload failed: ${result.reload_error}`,
        });
        setSourceModified(false);
        loadPlugins();
        if (!selectedPlugin) setSelectedPlugin(result.plugin_name);
      } else {
        setSaveResult({ ok: false, message: result.error || 'Save failed' });
        if (result.issues) setValidationIssues(result.issues);
      }
    } catch (err: any) {
      setSaveResult({ ok: false, message: err.message });
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async () => {
    setValidating(true);
    setValidationIssues([]);
    try {
      const result = await api<any>('/api/plugins/validate_code', {
        method: 'POST',
        body: JSON.stringify({ code: sourceCode }),
      });
      setValidationIssues(result.issues || []);
    } catch (err: any) {
      setValidationIssues([{ severity: 'error', category: 'request', message: err.message }]);
    } finally {
      setValidating(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedPlugin) return;
    if (!window.confirm(`Delete custom plugin "${selectedPlugin}"? This cannot be undone.`)) return;
    setDeleting(true);
    try {
      await api<any>(`/api/plugins/custom/${selectedPlugin}`, { method: 'DELETE' });
      setSelectedPlugin('');
      setSourceCode('');
      setSourceModified(false);
      setSaveResult({ ok: true, message: `Deleted "${selectedPlugin}"` });
      loadPlugins();
    } catch (err: any) {
      setSaveResult({ ok: false, message: `Delete failed: ${err.message}` });
    } finally {
      setDeleting(false);
    }
  };

  const handleNewPlugin = () => {
    setSelectedPlugin('');
    setSourceCode(PLUGIN_TEMPLATE);
    setSourceModified(true);
    setSaveResult(null);
    setValidationIssues([]);
    setTab('source');
  };

  return (
    <div className="protocol-editor-page">
      <div className="editor-toolbar">
        <div className="toolbar-left">
          <h1>Protocol Editor</h1>
          <select
            className="plugin-select"
            value={selectedPlugin}
            onChange={(e) => {
              setSelectedPlugin(e.target.value);
              setSaveResult(null);
              setValidationIssues([]);
            }}
          >
            <option value="">— select plugin —</option>
            {plugins.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
          <button className="btn btn-primary btn-sm" onClick={handleNewPlugin}>+ New Plugin</button>
        </div>
        <div className="toolbar-right">
          {tab === 'source' && (
            <>
              <button
                className="btn btn-ghost btn-sm"
                onClick={handleValidate}
                disabled={validating || !sourceCode.trim()}
              >
                {validating ? 'Validating…' : '✓ Validate'}
              </button>
              <button
                className="btn btn-primary btn-sm"
                onClick={handleSave}
                disabled={saving || !sourceCode.trim()}
              >
                {saving ? 'Saving…' : '💾 Save'}
              </button>
              <button
                className="btn btn-danger btn-sm"
                onClick={handleDelete}
                disabled={deleting || !selectedPlugin}
              >
                Delete
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="editor-tabs">
        <button className={`editor-tab ${tab === 'design' ? 'active' : ''}`} onClick={() => setTab('design')}>
          <span className="tab-icon">✎</span> Design
        </button>
        <button className={`editor-tab ${tab === 'source' ? 'active' : ''}`} onClick={() => setTab('source')}>
          <span className="tab-icon">{'</>'}</span> Source
          {sourceModified && <span className="modified-dot" />}
        </button>
        <button className={`editor-tab ${tab === 'inspect' ? 'active' : ''}`} onClick={() => setTab('inspect')}>
          <span className="tab-icon">⚙</span> Inspect
        </button>
      </div>

      {/* Save/validation messages */}
      {saveResult && (
        <div className={`editor-message ${saveResult.ok ? 'success' : 'error'}`}>
          {saveResult.message}
        </div>
      )}

      {/* Tab content */}
      <div className="editor-content">
        {tab === 'design' && (
          <div className="tab-panel">
            <ProtocolStudioPage />
          </div>
        )}

        {tab === 'source' && (
          <div className="tab-panel source-panel">
            <textarea
              className="code-editor"
              value={sourceCode}
              onChange={(e) => {
                setSourceCode(e.target.value);
                setSourceModified(true);
                setSaveResult(null);
              }}
              spellCheck={false}
              placeholder="# Write or paste your protocol plugin code here…"
            />
            {validationIssues.length > 0 && (
              <div className="validation-panel">
                <h3>Validation Results ({validationIssues.length} issues)</h3>
                <ul className="issue-list">
                  {validationIssues.map((issue, i) => (
                    <li key={i} className={`issue-item ${issue.severity}`}>
                      <span className="issue-severity">{issue.severity}</span>
                      <span className="issue-category">{issue.category}</span>
                      <span className="issue-message">{issue.message}</span>
                      {issue.suggestion && <span className="issue-suggestion">→ {issue.suggestion}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        {tab === 'inspect' && (
          <div className="tab-panel">
            {selectedPlugin ? (
              <PluginDebuggerPage />
            ) : (
              <div className="empty-tab">
                <p>Select a plugin above to inspect its data model, state machine, and generated seeds.</p>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function extractPluginName(code: string): string {
  // Try to find data_model name
  const match = code.match(/["']name["']\s*:\s*["']([^"']+)["']/);
  if (match) return match[1].toLowerCase().replace(/\s+/g, '_');
  return '';
}

const PLUGIN_TEMPLATE = `"""
My Custom Protocol Plugin

Describe your protocol here.
"""

__version__ = "1.0.0"

# Transport: "tcp" or "udp"
transport = "tcp"

data_model = {
    "name": "MyProtocol",
    "description": "A custom protocol definition",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"MYPK",
            "mutable": False,
        },
        {
            "name": "length",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True,
            "size_of": "payload",
        },
        {
            "name": "command",
            "type": "uint8",
            "values": {
                0x01: "INIT",
                0x02: "DATA",
                0x03: "CLOSE",
            },
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 1024,
        },
    ],
}

state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "CONNECTED", "CLOSED"],
    "transitions": [
        {
            "from": "INIT",
            "to": "CONNECTED",
            "message_type": "INIT",
            "trigger": "send",
        },
        {
            "from": "CONNECTED",
            "to": "CONNECTED",
            "message_type": "DATA",
            "trigger": "send",
        },
        {
            "from": "CONNECTED",
            "to": "CLOSED",
            "message_type": "CLOSE",
            "trigger": "send",
        },
    ],
}


def validate_response(response: bytes) -> bool:
    """Optional: check responses for logical correctness."""
    return len(response) >= 4
`;
