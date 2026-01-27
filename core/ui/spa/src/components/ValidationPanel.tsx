import './ValidationPanel.css';

export interface ValidationIssue {
  severity: string; // "error" | "warning" | "info"
  category: string;
  message: string;
  line?: number | null;
  field?: string | null;
  suggestion?: string | null;
}

interface ValidationPanelProps {
  issues: ValidationIssue[];
  summary: string;
  valid: boolean;
  pluginName?: string;
}

function ValidationPanel({ issues, summary, valid, pluginName }: ValidationPanelProps) {
  const errors = issues.filter((issue) => issue.severity === 'error');
  const warnings = issues.filter((issue) => issue.severity === 'warning');
  const infos = issues.filter((issue) => issue.severity === 'info');

  const renderSuggestion = (issue: ValidationIssue) => {
    if (!issue.suggestion) return null;
    return <div className="issue-suggestion">Tip: {issue.suggestion}</div>;
  };

  const getIcon = (severity: string) => {
    switch (severity) {
      case 'error':
        return 'Error';
      case 'warning':
        return 'Warn';
      case 'info':
        return 'Info';
      default:
        return 'Note';
    }
  };

  const getCategoryColor = (category: string) => {
    switch (category) {
      case 'syntax':
        return '#ef4444';
      case 'model':
        return '#f59e0b';
      case 'data_model':
        return '#3b82f6';
      case 'state_model':
        return '#8b5cf6';
      case 'seeds':
        return '#10b981';
      default:
        return '#6b7280';
    }
  };

  const getVerboseGuidance = (issue: ValidationIssue) => {
    const message = issue.message.toLowerCase();

    if (message.includes("unhashable type: 'list'")) {
      return (
        "This usually means a list was used as a dictionary key or set entry. " +
        "Example: if the plugin 'feature_showcase' fails with this error, check " +
        "enum/value maps or response handler keys that use lists. Convert the " +
        "list to a tuple or string before using it as a key."
      );
    }

    if (message.startsWith('failed to execute plugin code')) {
      return (
        'Validation executes module-level code to load data_model/state_model. ' +
        'Any import-time exception will fail here; keep module-level logic ' +
        'side-effect free and move runtime code into functions.'
      );
    }

    if (message.includes("missing required 'data_model' attribute")) {
      return (
        'Expose a top-level `data_model` dictionary in the plugin module. ' +
        'The validator expects it to define blocks and (optionally) seeds.'
      );
    }

    if (message.includes("missing required 'state_model' attribute")) {
      return (
        'Expose a top-level `state_model` dictionary. Even a minimal state ' +
        'model helps the orchestrator understand valid transitions.'
      );
    }

    if (message.includes("data_model missing required 'blocks' field")) {
      return (
        'Add a `blocks` list to data_model. Each block should include at least ' +
        '`name` and `type`, and appear in on-wire order.'
      );
    }

    if (message.includes('no blocks defined in data_model')) {
      return (
        'Add at least one block to data_model.blocks so the parser can build a ' +
        'frame layout. Empty models cannot generate payloads.'
      );
    }

    if (message.includes('has invalid type')) {
      return (
        'Use one of the supported field types (bytes, uint*, int*, string). ' +
        'If you need a custom type, model it as bytes plus a size or max_size.'
      );
    }

    if (message.includes('seed') && message.includes('failed to parse')) {
      return (
        'Seeds must match the declared block layout and sizes. Regenerate the ' +
        'seed from a known-good capture or adjust the model to match.'
      );
    }

    if (message.includes('seed') && message.includes('is not bytes')) {
      return (
        'Seeds must be raw bytes, not strings or lists. Use base64 decoding or ' +
        'prefix with b"" in the plugin file.'
      );
    }

    if (message.includes('size_of references non-existent field')) {
      return (
        'Make sure size_of points to a real block name and that the size field ' +
        'appears before the referenced block.'
      );
    }

    if (message.includes('circular size_of reference')) {
      return (
        'Size fields cannot reference themselves. Use a separate length field or ' +
        'compute the size with a behavior instead.'
      );
    }

    if (message.includes('unreachable states detected')) {
      return (
        'Add transitions from the initial_state (or other reachable states) to ' +
        'cover every state, or remove dead states to keep the model tight.'
      );
    }

    if (message.includes("state_model missing 'initial_state'")) {
      return (
        'Set an initial_state so reachability and transition validation can start ' +
        'from a known entry point.'
      );
    }

    if (message.includes('transition') && message.includes('references undefined')) {
      return (
        'Ensure every transition refers to states listed in state_model.states. ' +
        'Typos here will block traversal.'
      );
    }

    if (message.includes('all fields are marked as mutable=false')) {
      return (
        'Mark at least one block mutable so the mutation engine has something to ' +
        'change. Otherwise fuzzing becomes a replay-only session.'
      );
    }

    if (message.startsWith('syntax error')) {
      return (
        'Fix the syntax error on the reported line, then rerun validation. ' +
        'Running `python -m py_compile` against the plugin file can help isolate it.'
      );
    }

    return null;
  };

  const renderGuidance = (issue: ValidationIssue) => {
    const guidance = getVerboseGuidance(issue);
    if (!guidance) return null;
    return <div className="issue-guidance">Guidance: {guidance}</div>;
  };

  return (
    <div className="validation-panel">
      <div className={`validation-summary ${valid ? 'valid' : 'invalid'}`}>
        <div className="summary-icon">{valid ? 'Valid' : 'Invalid'}</div>
        <div className="summary-text">{summary}</div>
      </div>

      {errors.length > 0 && (
        <div className="issue-section error-section">
          <h4>Errors ({errors.length})</h4>
          <ul className="issue-list">
            {errors.map((issue, index) => (
              <li key={index} className="issue-item error">
                <span className="issue-icon">{getIcon(issue.severity)}</span>
                <div className="issue-content">
                  <div className="issue-header">
                    <span
                      className="issue-category"
                      style={{ backgroundColor: getCategoryColor(issue.category) }}
                    >
                      {issue.category}
                    </span>
                    {issue.line && <span className="issue-line">Line {issue.line}</span>}
                    {issue.field && <span className="issue-field">Field: {issue.field}</span>}
                    {pluginName && <span className="issue-field">Plugin: {pluginName}</span>}
                  </div>
                  <div className="issue-message">{issue.message}</div>
                  {renderSuggestion(issue)}
                  {renderGuidance(issue)}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="issue-section warning-section">
          <h4>Warnings ({warnings.length})</h4>
          <ul className="issue-list">
            {warnings.map((issue, index) => (
              <li key={index} className="issue-item warning">
                <span className="issue-icon">{getIcon(issue.severity)}</span>
                <div className="issue-content">
                  <div className="issue-header">
                    <span
                      className="issue-category"
                      style={{ backgroundColor: getCategoryColor(issue.category) }}
                    >
                      {issue.category}
                    </span>
                    {issue.line && <span className="issue-line">Line {issue.line}</span>}
                    {issue.field && <span className="issue-field">Field: {issue.field}</span>}
                    {pluginName && <span className="issue-field">Plugin: {pluginName}</span>}
                  </div>
                  <div className="issue-message">{issue.message}</div>
                  {renderSuggestion(issue)}
                  {renderGuidance(issue)}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {infos.length > 0 && (
        <div className="issue-section info-section">
          <h4>Info ({infos.length})</h4>
          <ul className="issue-list">
            {infos.map((issue, index) => (
              <li key={index} className="issue-item info">
                <span className="issue-icon">{getIcon(issue.severity)}</span>
                <div className="issue-content">
                  <div className="issue-header">
                    <span
                      className="issue-category"
                      style={{ backgroundColor: getCategoryColor(issue.category) }}
                    >
                      {issue.category}
                    </span>
                    {issue.line && <span className="issue-line">Line {issue.line}</span>}
                    {issue.field && <span className="issue-field">Field: {issue.field}</span>}
                    {pluginName && <span className="issue-field">Plugin: {pluginName}</span>}
                  </div>
                  <div className="issue-message">{issue.message}</div>
                  {renderSuggestion(issue)}
                  {renderGuidance(issue)}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {issues.length === 0 && valid && (
        <div className="no-issues">
          <p>No issues found - your plugin is ready to use!</p>
        </div>
      )}
    </div>
  );
}

export default ValidationPanel;
