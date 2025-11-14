import './ValidationPanel.css';

export interface ValidationIssue {
  severity: string; // "error" | "warning" | "info"
  category: string;
  message: string;
  line?: number | null;
  field?: string | null;
}

interface ValidationPanelProps {
  issues: ValidationIssue[];
  summary: string;
  valid: boolean;
}

function ValidationPanel({ issues, summary, valid }: ValidationPanelProps) {
  const errors = issues.filter((issue) => issue.severity === 'error');
  const warnings = issues.filter((issue) => issue.severity === 'warning');
  const infos = issues.filter((issue) => issue.severity === 'info');

  const getIcon = (severity: string) => {
    switch (severity) {
      case 'error':
        return '❌';
      case 'warning':
        return '⚠️';
      case 'info':
        return 'ℹ️';
      default:
        return '•';
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

  return (
    <div className="validation-panel">
      <div className={`validation-summary ${valid ? 'valid' : 'invalid'}`}>
        <div className="summary-icon">{valid ? '✅' : '❌'}</div>
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
                  </div>
                  <div className="issue-message">{issue.message}</div>
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
                  </div>
                  <div className="issue-message">{issue.message}</div>
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
                  </div>
                  <div className="issue-message">{issue.message}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {issues.length === 0 && valid && (
        <div className="no-issues">
          <p>✨ No issues found - your plugin is ready to use!</p>
        </div>
      )}
    </div>
  );
}

export default ValidationPanel;
