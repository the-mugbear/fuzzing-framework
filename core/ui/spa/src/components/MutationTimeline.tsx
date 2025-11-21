import { useState } from 'react';
import './MutationTimeline.css';

export interface MutationStackEntry {
  id: string;
  type: 'manual_edit' | 'mutator';
  mutator?: string;
  fieldChanged?: string;
  timestamp: Date;
  bytesChanged: number[];
  beforeHex: string;
  afterHex: string;
  description: string;
}

interface MutationTimelineProps {
  stack: MutationStackEntry[];
  baseName: string; // e.g., "simple_tcp base message 1"
  onRemoveMutation: (mutationId: string) => void;
  onClearAll: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onViewDiff: (entry: MutationStackEntry) => void;
  canUndo: boolean;
  canRedo: boolean;
}

function MutationTimeline({
  stack,
  baseName,
  onRemoveMutation,
  onClearAll,
  onUndo,
  onRedo,
  onViewDiff,
  canUndo,
  canRedo,
}: MutationTimelineProps) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  return (
    <div className="mutation-timeline">
      <div className="timeline-header">
        <h3>Mutation Timeline</h3>
        <div className="timeline-controls">
          <button
            type="button"
            onClick={onUndo}
            disabled={!canUndo}
            className="timeline-btn"
            title="Undo last mutation"
          >
            ↶ Undo
          </button>
          <button
            type="button"
            onClick={onRedo}
            disabled={!canRedo}
            className="timeline-btn"
            title="Redo mutation"
          >
            ↷ Redo
          </button>
          <button
            type="button"
            onClick={onClearAll}
            disabled={stack.length === 0}
            className="timeline-btn clear-btn"
            title="Clear all mutations and reset to base message"
          >
            Clear All
          </button>
        </div>
      </div>

      <div className="timeline-content">
        {/* Base message */}
        <div className="timeline-entry base-entry">
          <div className="entry-icon">📦</div>
          <div className="entry-content">
            <div className="entry-title">Base Message</div>
            <div className="entry-subtitle">{baseName}</div>
          </div>
        </div>

        {/* Mutation stack */}
        {stack.length === 0 ? (
          <div className="timeline-empty">
            <p>No mutations applied yet</p>
            <p className="hint">Apply mutations below to see them here</p>
          </div>
        ) : (
          stack.map((entry, index) => (
            <div key={entry.id} className="timeline-flow">
              <div className="flow-arrow">↓</div>
              <div
                className={`timeline-entry mutation-entry ${
                  expandedId === entry.id ? 'expanded' : ''
                }`}
              >
                <div className="entry-header" onClick={() => toggleExpand(entry.id)}>
                  <div className="entry-icon">
                    {entry.type === 'manual_edit' ? '✏️' : '⚡'}
                  </div>
                  <div className="entry-content">
                    <div className="entry-title">
                      <span className="entry-number">{index + 1}.</span>
                      {entry.type === 'manual_edit' ? (
                        <span>Manual Edit</span>
                      ) : (
                        <span className="mutator-name">{entry.mutator}</span>
                      )}
                    </div>
                    <div className="entry-subtitle">{entry.description}</div>
                  </div>
                  <div className="entry-actions">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onViewDiff(entry);
                      }}
                      className="action-btn view-btn"
                      title="View what changed"
                    >
                      👁
                    </button>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemoveMutation(entry.id);
                      }}
                      className="action-btn remove-btn"
                      title="Remove this mutation"
                    >
                      ×
                    </button>
                  </div>
                </div>

                {expandedId === entry.id && (
                  <div className="entry-details">
                    <div className="detail-row">
                      <span className="detail-label">Time:</span>
                      <span className="detail-value">
                        {entry.timestamp.toLocaleTimeString()}
                      </span>
                    </div>
                    {entry.fieldChanged && (
                      <div className="detail-row">
                        <span className="detail-label">Field:</span>
                        <span className="detail-value">{entry.fieldChanged}</span>
                      </div>
                    )}
                    <div className="detail-row">
                      <span className="detail-label">Bytes changed:</span>
                      <span className="detail-value">
                        {entry.bytesChanged.length === 0
                          ? 'None'
                          : `${entry.bytesChanged.length} at offsets [${entry.bytesChanged
                              .slice(0, 10)
                              .join(', ')}${
                              entry.bytesChanged.length > 10 ? ', ...' : ''
                            }]`}
                      </span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))
        )}

        {/* Current state indicator */}
        {stack.length > 0 && (
          <div className="timeline-current">
            <div className="flow-arrow">↓</div>
            <div className="current-state">
              <strong>Current State</strong>
              <p>
                {stack.length} mutation{stack.length !== 1 ? 's' : ''} applied
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default MutationTimeline;
