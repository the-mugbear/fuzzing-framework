import { useState } from 'react';
import HexViewer, { HexHighlight } from './HexViewer';
import { FieldValue } from './EditableFieldTable';
import './DiffHexViewer.css';

interface DiffHexViewerProps {
  originalHex: string;
  mutatedHex: string;
  fields: FieldValue[];
  mutationSummary: {
    bytesChanged: number;
    offsets: number[];
    mutator: string;
  };
  onByteHover?: (offset: number | null) => void;
}

// Color palette for field highlighting
const FIELD_COLORS = [
  '#3b82f680', // blue
  '#10b98180', // green
  '#8b5cf680', // purple
  '#f59e0b80', // orange
  '#ef444480', // red
  '#06b6d480', // cyan
  '#ec489980', // pink
];

const CHANGED_BYTE_COLOR = '#fbbf2480'; // yellow highlight for changed bytes

function DiffHexViewer({
  originalHex,
  mutatedHex,
  fields,
  mutationSummary,
  onByteHover,
}: DiffHexViewerProps) {
  const [showDiff, setShowDiff] = useState(true);

  // Calculate which bytes changed
  const getChangedOffsets = (): Set<number> => {
    const changed = new Set<number>();
    const origBytes = originalHex.match(/.{1,2}/g) || [];
    const mutBytes = mutatedHex.match(/.{1,2}/g) || [];
    const maxLen = Math.max(origBytes.length, mutBytes.length);

    for (let i = 0; i < maxLen; i++) {
      if (origBytes[i] !== mutBytes[i]) {
        changed.add(i);
      }
    }

    return changed;
  };

  const changedOffsets = getChangedOffsets();

  // Generate highlights from fields
  const getFieldHighlights = (): HexHighlight[] => {
    return fields.map((field, index) => ({
      start: field.offset,
      end: field.offset + field.size,
      color: FIELD_COLORS[index % FIELD_COLORS.length],
      label: `${field.name} (${field.type})`,
    }));
  };

  // Generate highlights for changed bytes (overlay on top of field highlights)
  const getChangedHighlights = (): HexHighlight[] => {
    return Array.from(changedOffsets).map((offset) => ({
      start: offset,
      end: offset + 1,
      color: CHANGED_BYTE_COLOR,
      label: 'Changed byte',
    }));
  };

  const fieldHighlights = getFieldHighlights();
  const changedHighlights = getChangedHighlights();

  // Combine highlights (changed bytes overlay on field highlights)
  const originalHighlights = showDiff
    ? [...fieldHighlights, ...changedHighlights]
    : fieldHighlights;
  const mutatedHighlights = [...fieldHighlights, ...changedHighlights];

  return (
    <div className="diff-hex-viewer">
      <div className="diff-header">
        <div>
          <h4>Before/After Comparison</h4>
          <p className="diff-summary">
            <strong>{mutationSummary.mutator}</strong> changed{' '}
            <strong>{mutationSummary.bytesChanged}</strong> byte
            {mutationSummary.bytesChanged !== 1 ? 's' : ''}
            {mutationSummary.offsets.length > 0 && (
              <>
                {' '}
                at offset{mutationSummary.offsets.length !== 1 ? 's' : ''}{' '}
                <code>
                  [
                  {mutationSummary.offsets.slice(0, 10).join(', ')}
                  {mutationSummary.offsets.length > 10 && ', ...'}]
                </code>
              </>
            )}
          </p>
        </div>
        <label className="diff-toggle">
          <input
            type="checkbox"
            checked={showDiff}
            onChange={(e) => setShowDiff(e.target.checked)}
          />
          <span>Highlight changes</span>
        </label>
      </div>

      <div className="diff-legend">
        <div className="legend-item">
          <span className="legend-swatch field-swatch"></span>
          <span>Protocol fields</span>
        </div>
        <div className="legend-item">
          <span className="legend-swatch changed-swatch"></span>
          <span>Changed bytes</span>
        </div>
      </div>

      <div className="diff-panels">
        <div className="diff-panel">
          <div className="panel-header">
            <h5>Original (Before)</h5>
            <span className="byte-count">
              {(originalHex.match(/.{1,2}/g) || []).length} bytes
            </span>
          </div>
          <div className="panel-content">
            <HexViewer
              data={originalHex}
              highlights={originalHighlights}
              onByteHover={onByteHover}
            />
          </div>
        </div>

        <div className="diff-divider">
          <div className="divider-line"></div>
          <div className="divider-icon">→</div>
          <div className="divider-line"></div>
        </div>

        <div className="diff-panel">
          <div className="panel-header">
            <h5>Mutated (After)</h5>
            <span className="byte-count">
              {(mutatedHex.match(/.{1,2}/g) || []).length} bytes
            </span>
          </div>
          <div className="panel-content">
            <HexViewer
              data={mutatedHex}
              highlights={mutatedHighlights}
              onByteHover={onByteHover}
            />
          </div>
        </div>
      </div>

      {mutationSummary.bytesChanged === 0 && (
        <div className="no-changes-notice">
          ⚠️ No bytes were changed by this mutation. This may indicate the mutation
          strategy didn't find suitable targets in this message.
        </div>
      )}
    </div>
  );
}

export default DiffHexViewer;
