import { useState } from 'react';
import { FieldValue } from './EditableFieldTable';
import './FieldMutationPanel.css';

interface Mutation {
  name: string;
  label: string;
  description: string;
}

const STRUCTURE_AWARE_STRATEGIES: Mutation[] = [
  {
    name: 'boundary_values',
    label: 'Boundary Values',
    description: 'Test edge cases like 0, 1, MAX, MIN, empty, max_size',
  },
  {
    name: 'expand_field',
    label: 'Expand Field',
    description: 'Increase field size by 1.5x-3x (variable-length fields)',
  },
  {
    name: 'shrink_field',
    label: 'Shrink Field',
    description: 'Reduce field size by 50%-90% (variable-length fields)',
  },
  {
    name: 'repeat_pattern',
    label: 'Repeat Pattern',
    description: 'Fill field with repeating bytes (0x00, 0xFF, "A")',
  },
  {
    name: 'interesting_values',
    label: 'Interesting Values',
    description: 'Inject known problematic patterns and magic values',
  },
  {
    name: 'bit_flip_field',
    label: 'Bit Flip Field',
    description: 'Flip random bits within this field',
  },
  {
    name: 'arithmetic',
    label: 'Arithmetic',
    description: 'Add/subtract small values (integers only)',
  },
];

const BYTE_LEVEL_MUTATORS: Mutation[] = [
  {
    name: 'bitflip',
    label: 'Bit Flip',
    description: 'Flip ~1% of bits within this field',
  },
  {
    name: 'byteflip',
    label: 'Byte Flip',
    description: 'Replace ~5% of bytes within this field with random values',
  },
  {
    name: 'arithmetic',
    label: 'Arithmetic',
    description: 'Add/subtract integers from bytes in this field',
  },
  {
    name: 'interesting',
    label: 'Interesting Values',
    description: 'Inject boundary values (0, 255, 65535) within this field',
  },
];

interface FieldMutationPanelProps {
  selectedField: FieldValue | null;
  onMutate: (fieldName: string, mutator: string, strategy?: string) => void;
  disabled: boolean;
}

function FieldMutationPanel({
  selectedField,
  onMutate,
  disabled,
}: FieldMutationPanelProps) {
  const [activeTab, setActiveTab] = useState<'structure' | 'byte'>('structure');

  if (!selectedField) {
    return (
      <div className="field-mutation-panel empty">
        <div className="empty-state">
          <span className="empty-icon">Select</span>
          <h4>No Field Selected</h4>
          <p>Click a field in the table above to select it for mutation</p>
        </div>
      </div>
    );
  }

  const handleMutation = (mutator: string, strategy?: string) => {
    onMutate(selectedField.name, mutator, strategy);
  };

  return (
    <div className="field-mutation-panel">
      <div className="panel-header">
        <h4>Mutate Field: <span className="field-name">{selectedField.name}</span></h4>
        <div className="field-info">
          <span className="field-type">{selectedField.type}</span>
          <span className="field-size">{selectedField.size} bytes</span>
        </div>
      </div>

      <div className="mutation-tabs">
        <button
          className={`tab-button ${activeTab === 'structure' ? 'active' : ''}`}
          onClick={() => setActiveTab('structure')}
        >
          Structure-Aware
        </button>
        <button
          className={`tab-button ${activeTab === 'byte' ? 'active' : ''}`}
          onClick={() => setActiveTab('byte')}
        >
          Byte-Level
        </button>
      </div>

      {activeTab === 'structure' ? (
        <div className="mutation-section">
          <p className="section-description">
            Intelligent mutations that respect field type and protocol grammar.
            Auto-fixes dependent fields (like size fields).
          </p>
          <div className="mutation-grid">
            {STRUCTURE_AWARE_STRATEGIES.map((mutation) => (
              <button
                key={mutation.name}
                type="button"
                className="mutation-button structure"
                onClick={() => handleMutation('structure_aware', mutation.name)}
                disabled={disabled}
                title={mutation.description}
              >
                <span className="mutation-label">{mutation.label}</span>
                <span className="mutation-desc">{mutation.description}</span>
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="mutation-section">
          <p className="section-description">
            Raw byte mutations applied <strong>only within this field's byte range</strong>.
            May break field validity but constrained to selected field.
          </p>
          <div className="mutation-grid">
            {BYTE_LEVEL_MUTATORS.map((mutation) => (
              <button
                key={mutation.name}
                type="button"
                className="mutation-button byte"
                onClick={() => handleMutation(mutation.name)}
                disabled={disabled}
                title={mutation.description}
              >
                <span className="mutation-label">{mutation.label}</span>
                <span className="mutation-desc">{mutation.description}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="panel-footer">
        <p className="hint">
          <strong>Tip:</strong> The diff viewer will show exactly what changed after you apply a mutation.
        </p>
      </div>
    </div>
  );
}

export default FieldMutationPanel;
