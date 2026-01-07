import { useEffect, useState } from 'react';
import { api } from '../services/api';
import './PluginValidationPage.css';

interface ValidationIssue {
  severity: 'error' | 'warning' | 'info';
  category: string;
  message: string;
  suggestion?: string;
}

interface ValidationResult {
  valid: boolean;
  plugin_name: string;
  error_count: number;
  warning_count: number;
  issues: ValidationIssue[];
}

function PluginValidationPage() {
  const [plugins, setPlugins] = useState<string[]>([]);
  const [validationResults, setValidationResults] = useState<Map<string, ValidationResult>>(new Map());
  const [loading, setLoading] = useState(true);
  const [validatingPlugin, setValidatingPlugin] = useState<string | null>(null);
  const [codeValidationMode, setCodeValidationMode] = useState(false);
  const [codeInput, setCodeInput] = useState('');
  const [codeValidationResult, setCodeValidationResult] = useState<ValidationResult | null>(null);
  const [validatingCode, setValidatingCode] = useState(false);

  useEffect(() => {
    loadPlugins();
  }, []);

  const loadPlugins = async () => {
    try {
      const data = await api<string[]>('/api/plugins');
      setPlugins(data);
    } catch (err) {
      console.error('Failed to load plugins:', err);
    } finally {
      setLoading(false);
    }
  };

  const validatePlugin = async (pluginName: string) => {
    setValidatingPlugin(pluginName);
    try {
      const result = await api<ValidationResult>(`/api/plugins/${pluginName}/validate`);
      setValidationResults(prev => new Map(prev).set(pluginName, result));
    } catch (err) {
      console.error(`Failed to validate plugin ${pluginName}:`, err);
    } finally {
      setValidatingPlugin(null);
    }
  };

  const validateCode = async () => {
    if (!codeInput.trim()) return;

    setValidatingCode(true);
    try {
      const result = await api<ValidationResult>('/api/plugins/validate_code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: codeInput })
      });
      setCodeValidationResult(result);
    } catch (err) {
      console.error('Failed to validate code:', err);
    } finally {
      setValidatingCode(false);
    }
  };

  const getSeverityIcon = (severity: string) => {
    switch (severity) {
      case 'error': return '❌';
      case 'warning': return '⚠️';
      case 'info': return 'ℹ️';
      default: return '•';
    }
  };

  const getSeverityClass = (severity: string) => {
    return `severity-${severity}`;
  };

  if (loading) {
    return (
      <div className="plugin-validation-page">
        <div className="loading-message">Loading plugins...</div>
      </div>
    );
  }

  return (
    <div className="plugin-validation-page">
      <div className="page-header">
        <div className="page-title">
          <h1>Plugin Validation</h1>
          <p className="page-subtitle">
            Validate protocol plugins for errors and best practices
          </p>
        </div>
        <div className="page-controls">
          <button
            onClick={() => setCodeValidationMode(!codeValidationMode)}
            className={`mode-toggle ${codeValidationMode ? 'active' : ''}`}
          >
            {codeValidationMode ? '📋 Show Installed Plugins' : '✏️ Validate Code Snippet'}
          </button>
        </div>
      </div>

      {!codeValidationMode ? (
        <div className="installed-plugins-section">
          <h2>Installed Plugins</h2>
          {plugins.length === 0 ? (
            <div className="empty-message">No plugins installed</div>
          ) : (
            <div className="plugins-list">
              {plugins.map((pluginName) => {
                const result = validationResults.get(pluginName);
                const isValidating = validatingPlugin === pluginName;

                return (
                  <div key={pluginName} className="plugin-card">
                    <div className="plugin-header">
                      <div className="plugin-info">
                        <h3>{pluginName}</h3>
                      </div>
                      <button
                        onClick={() => validatePlugin(pluginName)}
                        disabled={isValidating}
                        className="validate-btn"
                      >
                        {isValidating ? 'Validating...' : 'Validate'}
                      </button>
                    </div>

                    {result && (
                      <div className={`validation-result ${result.valid ? 'valid' : 'invalid'}`}>
                        <div className="result-summary">
                          <span className={`status-badge ${result.valid ? 'success' : 'failure'}`}>
                            {result.valid ? '✓ Valid' : '✗ Invalid'}
                          </span>
                          {result.error_count > 0 && (
                            <span className="count-badge error">
                              {result.error_count} error{result.error_count !== 1 ? 's' : ''}
                            </span>
                          )}
                          {result.warning_count > 0 && (
                            <span className="count-badge warning">
                              {result.warning_count} warning{result.warning_count !== 1 ? 's' : ''}
                            </span>
                          )}
                        </div>

                        {result.issues.length > 0 && (
                          <div className="issues-list">
                            {result.issues.map((issue, idx) => (
                              <div key={idx} className={`issue ${getSeverityClass(issue.severity)}`}>
                                <div className="issue-header">
                                  <span className="issue-icon">{getSeverityIcon(issue.severity)}</span>
                                  <span className="issue-category">[{issue.category}]</span>
                                  <span className="issue-message">{issue.message}</span>
                                </div>
                                {issue.suggestion && (
                                  <div className="issue-suggestion">
                                    💡 {issue.suggestion}
                                  </div>
                                )}
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      ) : (
        <div className="code-validation-section">
          <h2>Validate Code Snippet</h2>
          <p className="section-description">
            Paste your plugin code below to validate it before saving to a file.
          </p>

          <textarea
            className="code-input"
            placeholder="# Paste your plugin code here&#10;&#10;__version__ = '1.0.0'&#10;&#10;data_model = {&#10;    'name': 'MyProtocol',&#10;    'blocks': [...]&#10;}&#10;&#10;state_model = {&#10;    'initial_state': 'INIT',&#10;    'states': [...],&#10;    'transitions': [...]&#10;}"
            value={codeInput}
            onChange={(e) => setCodeInput(e.target.value)}
            rows={20}
          />

          <button
            onClick={validateCode}
            disabled={validatingCode || !codeInput.trim()}
            className="validate-code-btn"
          >
            {validatingCode ? 'Validating...' : 'Validate Code'}
          </button>

          {codeValidationResult && (
            <div className={`validation-result ${codeValidationResult.valid ? 'valid' : 'invalid'}`}>
              <div className="result-header">
                <h3>Validation Results</h3>
                {codeValidationResult.plugin_name && (
                  <span className="detected-name">
                    Detected plugin: <strong>{codeValidationResult.plugin_name}</strong>
                  </span>
                )}
              </div>

              <div className="result-summary">
                <span className={`status-badge ${codeValidationResult.valid ? 'success' : 'failure'}`}>
                  {codeValidationResult.valid ? '✓ Valid' : '✗ Invalid'}
                </span>
                {codeValidationResult.error_count > 0 && (
                  <span className="count-badge error">
                    {codeValidationResult.error_count} error{codeValidationResult.error_count !== 1 ? 's' : ''}
                  </span>
                )}
                {codeValidationResult.warning_count > 0 && (
                  <span className="count-badge warning">
                    {codeValidationResult.warning_count} warning{codeValidationResult.warning_count !== 1 ? 's' : ''}
                  </span>
                )}
              </div>

              {codeValidationResult.issues.length > 0 ? (
                <div className="issues-list">
                  {codeValidationResult.issues.map((issue, idx) => (
                    <div key={idx} className={`issue ${getSeverityClass(issue.severity)}`}>
                      <div className="issue-header">
                        <span className="issue-icon">{getSeverityIcon(issue.severity)}</span>
                        <span className="issue-category">[{issue.category}]</span>
                        <span className="issue-message">{issue.message}</span>
                      </div>
                      {issue.suggestion && (
                        <div className="issue-suggestion">
                          💡 {issue.suggestion}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="no-issues">
                  ✓ No issues found. Your plugin looks good!
                </div>
              )}
            </div>
          )}
        </div>
      )}

      <div className="validation-guide">
        <h3>Validation Checks</h3>
        <div className="checks-grid">
          <div className="check-category">
            <h4>Syntax</h4>
            <ul>
              <li>Valid Python syntax</li>
              <li>Required attributes present (<code>__version__</code>, <code>data_model</code>, <code>state_model</code>)</li>
              <li>Correct data types</li>
            </ul>
          </div>
          <div className="check-category">
            <h4>Data Model</h4>
            <ul>
              <li>Valid block types</li>
              <li>Required block attributes</li>
              <li><code>size_of</code> references valid blocks</li>
              <li>Size fields use numeric types</li>
            </ul>
          </div>
          <div className="check-category">
            <h4>State Model</h4>
            <ul>
              <li>Initial state exists</li>
              <li>All transitions reference valid states</li>
              <li>No unreachable states</li>
              <li>Message types match data model</li>
            </ul>
          </div>
          <div className="check-category">
            <h4>Best Practices</h4>
            <ul>
              <li>Seeds provided (or auto-generated)</li>
              <li>Reasonable field sizes</li>
              <li>At least one mutable field</li>
              <li>Optional validator function</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  );
}

export default PluginValidationPage;
