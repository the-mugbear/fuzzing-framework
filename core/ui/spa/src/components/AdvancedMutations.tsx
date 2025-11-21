import { useState } from 'react';
import './AdvancedMutations.css';

interface AdvancedMutationsProps {
  onMutate: (mutatorName: string) => void;
  disabled: boolean;
  seedCount: number;
}

function AdvancedMutations({ onMutate, disabled, seedCount }: AdvancedMutationsProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const isSpliceDisabled = seedCount < 2;

  return (
    <div className="advanced-mutations">
      <button
        className="expand-button"
        onClick={() => setIsExpanded(!isExpanded)}
        type="button"
      >
        <span className="expand-icon">{isExpanded ? '▼' : '▶'}</span>
        <span>Advanced: Full-Message Mutations</span>
      </button>

      {isExpanded && (
        <div className="advanced-content">
          <p className="warning-text">
            ⚠️ These mutations affect <strong>random positions across the entire message</strong>,
            not just a single field. Use for exploratory testing when you want maximum chaos.
          </p>

          <div className="advanced-grid">
            <button
              type="button"
              className="advanced-mutation-btn havoc"
              onClick={() => onMutate('havoc')}
              disabled={disabled}
              title="Applies 2-10 aggressive random operations: insert, delete, duplicate, shuffle"
            >
              <span className="mutation-icon">💥</span>
              <div className="mutation-content">
                <span className="mutation-label">Havoc</span>
                <span className="mutation-desc">
                  Aggressive multi-mutation: inserts, deletes, duplicates, shuffles chunks
                </span>
              </div>
            </button>

            <button
              type="button"
              className="advanced-mutation-btn splice"
              onClick={() => onMutate('splice')}
              disabled={disabled || isSpliceDisabled}
              title={
                isSpliceDisabled
                  ? 'Splice requires at least 2 base messages'
                  : 'Combines portions of two different base messages at random split points'
              }
            >
              <span className="mutation-icon">🔀</span>
              <div className="mutation-content">
                <span className="mutation-label">
                  Splice {isSpliceDisabled && '(Requires 2+ messages)'}
                </span>
                <span className="mutation-desc">
                  {isSpliceDisabled
                    ? 'Need at least 2 base messages to splice'
                    : 'Combines portions of two base messages to merge states/features'}
                </span>
              </div>
            </button>
          </div>

          <div className="info-box">
            <strong>When to use:</strong>
            <ul>
              <li>
                <strong>Havoc:</strong> Maximum mutation intensity - good for finding parser
                bugs and crashes
              </li>
              <li>
                <strong>Splice:</strong> Combine features from different messages - good for
                testing state confusion
              </li>
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}

export default AdvancedMutations;
