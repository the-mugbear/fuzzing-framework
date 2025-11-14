import './MutationControls.css';

interface Mutator {
  name: string;
  label: string;
  description: string;
  category: 'structure' | 'byte';
}

const MUTATORS: Mutator[] = [
  {
    name: 'structure_aware',
    label: 'Structure-Aware',
    description: 'Mutates fields while respecting protocol grammar',
    category: 'structure',
  },
  {
    name: 'bitflip',
    label: 'Bit Flip',
    description: 'Randomly flips individual bits',
    category: 'byte',
  },
  {
    name: 'byteflip',
    label: 'Byte Flip',
    description: 'Replaces random bytes with random values',
    category: 'byte',
  },
  {
    name: 'arithmetic',
    label: 'Arithmetic',
    description: 'Adds/subtracts small integers to sequences',
    category: 'byte',
  },
  {
    name: 'interesting',
    label: 'Interesting Values',
    description: 'Injects boundary values (0, 255, 65535, etc.)',
    category: 'byte',
  },
  {
    name: 'havoc',
    label: 'Havoc',
    description: 'Aggressive random mutations',
    category: 'byte',
  },
  {
    name: 'splice',
    label: 'Splice',
    description: 'Combines portions of multiple seeds',
    category: 'byte',
  },
];

interface MutationControlsProps {
  onMutate: (mutatorName: string) => void;
  disabled: boolean;
  seedCount: number;
}

function MutationControls({ onMutate, disabled, seedCount }: MutationControlsProps) {
  const structureMutators = MUTATORS.filter((m) => m.category === 'structure');
  const byteMutators = MUTATORS.filter((m) => m.category === 'byte');

  const isSpliceDisabled = seedCount < 2;

  return (
    <div className="mutation-controls">
      <div className="mutator-section">
        <h4>Structure-Aware Mutations</h4>
        <p className="section-desc">Mutations that understand protocol structure</p>
        <div className="mutator-grid">
          {structureMutators.map((mutator) => (
            <button
              key={mutator.name}
              type="button"
              onClick={() => onMutate(mutator.name)}
              disabled={disabled}
              className="mutator-btn structure"
              title={mutator.description}
            >
              <span className="mutator-label">{mutator.label}</span>
              <span className="mutator-desc">{mutator.description}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="mutator-section">
        <h4>Byte-Level Mutations</h4>
        <p className="section-desc">Blind mutations that ignore protocol structure</p>
        <div className="mutator-grid">
          {byteMutators.map((mutator) => (
            <button
              key={mutator.name}
              type="button"
              onClick={() => onMutate(mutator.name)}
              disabled={disabled || (mutator.name === 'splice' && isSpliceDisabled)}
              className="mutator-btn byte"
              title={
                mutator.name === 'splice' && isSpliceDisabled
                  ? 'Splice requires at least 2 seeds'
                  : mutator.description
              }
            >
              <span className="mutator-label">{mutator.label}</span>
              <span className="mutator-desc">
                {mutator.name === 'splice' && isSpliceDisabled
                  ? 'Requires 2+ seeds'
                  : mutator.description}
              </span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default MutationControls;
