import { ReactNode, useMemo, useState } from 'react';
import ValidationPanel, { ValidationIssue } from '../components/ValidationPanel';
import { api } from '../services/api';
import './ProtocolStudioPage.css';

type FieldType =
  | 'bits'
  | 'bytes'
  | 'uint8'
  | 'uint16'
  | 'uint32'
  | 'uint64'
  | 'int8'
  | 'int16'
  | 'int32'
  | 'int64'
  | 'string';

type EndianType = '' | 'big' | 'little';

type BitOrder = '' | 'msb' | 'lsb';

type SizeUnit = '' | 'bits' | 'bytes' | 'words' | 'dwords';

interface BlockRow {
  id: string;
  name: string;
  type: FieldType;
  size: string;
  maxSize: string;
  defaultValue: string;
  mutable: boolean;
  description: string;
  endian: EndianType;
  bitOrder: BitOrder;
  isSizeField: boolean;
  sizeOf: string;
  sizeUnit: SizeUnit;
}

interface TransitionRow {
  id: string;
  from: string;
  to: string;
  messageType: string;
  trigger: string;
  expectedResponse: string;
}

interface ValidationResult {
  valid: boolean;
  plugin_name: string;
  error_count: number;
  warning_count: number;
  issues: ValidationIssue[];
}

const FIELD_TYPES: FieldType[] = [
  'bits',
  'bytes',
  'uint8',
  'uint16',
  'uint32',
  'uint64',
  'int8',
  'int16',
  'int32',
  'int64',
  'string',
];

const SIZE_UNITS: SizeUnit[] = ['', 'bits', 'bytes', 'words', 'dwords'];

const EMPTY_BLOCK: BlockRow = {
  id: 'block-1',
  name: '',
  type: 'uint8',
  size: '',
  maxSize: '',
  defaultValue: '',
  mutable: true,
  description: '',
  endian: '',
  bitOrder: '',
  isSizeField: false,
  sizeOf: '',
  sizeUnit: '',
};

const EMPTY_TRANSITION: TransitionRow = {
  id: 'transition-1',
  from: '',
  to: '',
  messageType: '',
  trigger: '',
  expectedResponse: '',
};

function InfoTooltip({
  label,
  children,
  className = '',
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <button type="button" className={`tooltip-trigger ${className}`.trim()} aria-label={label}>
      ⓘ
      <span className="tooltip-content">{children}</span>
    </button>
  );
}

function buildPythonStringLiteral(value: string): string {
  const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  return `"${escaped}"`;
}

function isHexBytes(value: string): boolean {
  if (!value) return false;
  const compact = value.replace(/\s+/g, '');
  return /^[0-9a-fA-F]+$/.test(compact) && compact.length % 2 === 0;
}

function hexToPythonBytes(value: string): string {
  const compact = value.replace(/\s+/g, '');
  const bytes = compact.match(/.{1,2}/g) ?? [];
  const escaped = bytes.map((byte) => `\\x${byte.toLowerCase()}`).join('');
  return `b"${escaped}"`;
}

function stringToPythonBytes(value: string): string {
  const escaped = value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  return `b"${escaped}"`;
}

function buildBlockPython(block: BlockRow): Record<string, string | number | boolean | string[] | null> {
  const result: Record<string, string | number | boolean | string[] | null> = {
    name: block.name.trim(),
    type: block.type,
  };

  const size = Number(block.size);
  if (!Number.isNaN(size) && size > 0) {
    result.size = size;
  }

  const maxSize = Number(block.maxSize);
  if (!Number.isNaN(maxSize) && maxSize > 0) {
    result.max_size = maxSize;
  }

  if (block.defaultValue.trim()) {
    if (block.type === 'bytes') {
      result.default = isHexBytes(block.defaultValue)
        ? hexToPythonBytes(block.defaultValue)
        : stringToPythonBytes(block.defaultValue);
    } else if (block.type === 'string') {
      result.default = buildPythonStringLiteral(block.defaultValue.trim());
    } else {
      result.default = block.defaultValue.trim();
    }
  }

  if (!block.mutable) {
    result.mutable = false;
  }

  if (block.description.trim()) {
    result.description = buildPythonStringLiteral(block.description.trim());
  }

  if (block.endian) {
    result.endian = block.endian;
  }

  if (block.bitOrder) {
    result.bit_order = block.bitOrder;
  }

  if (block.isSizeField) {
    result.is_size_field = true;
    const sizeOf = block.sizeOf
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    if (sizeOf.length > 0) {
      result.size_of = sizeOf;
    }
    if (block.sizeUnit) {
      result.size_unit = block.sizeUnit;
    }
  }

  return result;
}

function formatPythonDict(value: Record<string, string | number | boolean | string[] | null>, indent: string): string {
  const lines = Object.entries(value)
    .filter(([, fieldValue]) => fieldValue !== null && fieldValue !== '')
    .map(([key, fieldValue]) => {
      if (Array.isArray(fieldValue)) {
        return `${indent}"${key}": ${JSON.stringify(fieldValue)},`;
      }
      if (typeof fieldValue === 'string') {
        if (
          fieldValue.startsWith('b"') ||
          fieldValue.startsWith('"') ||
          /^-?(0x[0-9a-fA-F]+|\d+)$/.test(fieldValue)
        ) {
          return `${indent}"${key}": ${fieldValue},`;
        }
        return `${indent}"${key}": "${fieldValue}",`;
      }
      return `${indent}"${key}": ${fieldValue},`;
    });

  return lines.join('\n');
}

function buildPluginCode(
  moduleName: string,
  version: string,
  description: string,
  blocks: BlockRow[],
  seeds: string[],
  initialState: string,
  states: string[],
  transitions: TransitionRow[],
): string {
  const filteredBlocks = blocks.filter((block) => block.name.trim());
  const blockLines = filteredBlocks.map((block) => {
    const blockDict = buildBlockPython(block);
    const formatted = formatPythonDict(blockDict, '        ');
    return `    {\n${formatted}\n    },`;
  });

  const seedLines = seeds
    .map((seed) => seed.trim())
    .filter(Boolean)
    .map((seed) => (isHexBytes(seed) ? hexToPythonBytes(seed) : stringToPythonBytes(seed)));

  const stateList = states.map((state) => state.trim()).filter(Boolean);
  const transitionLines = transitions
    .filter((transition) => transition.from.trim() && transition.to.trim())
    .map((transition) => {
      const transitionDict: Record<string, string> = {
        from: buildPythonStringLiteral(transition.from.trim()),
        to: buildPythonStringLiteral(transition.to.trim()),
      };
      if (transition.messageType.trim()) {
        transitionDict.message_type = buildPythonStringLiteral(transition.messageType.trim());
      }
      if (transition.trigger.trim()) {
        transitionDict.trigger = buildPythonStringLiteral(transition.trigger.trim());
      }
      if (transition.expectedResponse.trim()) {
        transitionDict.expected_response = buildPythonStringLiteral(transition.expectedResponse.trim());
      }
      const formatted = formatPythonDict(transitionDict, '        ');
      return `    {\n${formatted}\n    },`;
    });

  const moduleHeader = moduleName.trim() || 'new_protocol';
  const versionValue = version.trim() || '0.1.0';

  return `"""
Protocol plugin generated by Protocol Studio.

Module: ${moduleHeader}
"""

__version__ = "${versionValue}"

data_model = {
    "name": "${moduleHeader}",
    "description": ${description.trim() ? buildPythonStringLiteral(description.trim()) : '""'},
    "version": "${versionValue}",
    "blocks": [
${blockLines.join('\n') || '        # TODO: add blocks\n        {"name": "field", "type": "uint8"},'}
    ],
    "seeds": [
${seedLines.map((seed) => `        ${seed},`).join('\n') || '        # Optional: add base seeds\n'}
    ]
}

state_model = {
    "initial_state": "${initialState.trim() || 'INIT'}",
    "states": ${stateList.length ? JSON.stringify(stateList) : '["INIT"]'},
    "transitions": [
${transitionLines.join('\n') || '        # Optional: add transitions\n'}
    ]
}
`;
}

function ProtocolStudioPage() {
  const [moduleName, setModuleName] = useState('custom_protocol');
  const [version, setVersion] = useState('0.1.0');
  const [description, setDescription] = useState('');
  const [blocks, setBlocks] = useState<BlockRow[]>([{ ...EMPTY_BLOCK }]);
  const [seeds, setSeeds] = useState('');
  const [initialState, setInitialState] = useState('INIT');
  const [states, setStates] = useState('INIT');
  const [transitions, setTransitions] = useState<TransitionRow[]>([{ ...EMPTY_TRANSITION }]);
  const [codeValidation, setCodeValidation] = useState<ValidationResult | null>(null);
  const [codeValidationError, setCodeValidationError] = useState<string | null>(null);
  const [codeValidationLoading, setCodeValidationLoading] = useState(false);
  const [customCode, setCustomCode] = useState('');
  const [customValidation, setCustomValidation] = useState<ValidationResult | null>(null);
  const [customValidationError, setCustomValidationError] = useState<string | null>(null);
  const [customValidationLoading, setCustomValidationLoading] = useState(false);

  const generatedCode = useMemo(() => {
    const seedLines = seeds
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean);
    const stateList = states
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    return buildPluginCode(
      moduleName,
      version,
      description,
      blocks,
      seedLines,
      initialState,
      stateList,
      transitions,
    );
  }, [moduleName, version, description, blocks, seeds, initialState, states, transitions]);

  const updateBlock = (id: string, updates: Partial<BlockRow>) => {
    setBlocks((prev) => prev.map((block) => (block.id === id ? { ...block, ...updates } : block)));
  };

  const addBlock = () => {
    setBlocks((prev) => [
      ...prev,
      {
        ...EMPTY_BLOCK,
        id: `block-${prev.length + 1}`,
      },
    ]);
  };

  const removeBlock = (id: string) => {
    setBlocks((prev) => prev.filter((block) => block.id !== id));
  };

  const updateTransition = (id: string, updates: Partial<TransitionRow>) => {
    setTransitions((prev) => prev.map((transition) => (transition.id === id ? { ...transition, ...updates } : transition)));
  };

  const addTransition = () => {
    setTransitions((prev) => [
      ...prev,
      {
        ...EMPTY_TRANSITION,
        id: `transition-${prev.length + 1}`,
      },
    ]);
  };

  const removeTransition = (id: string) => {
    setTransitions((prev) => prev.filter((transition) => transition.id !== id));
  };

  const validateGeneratedCode = async () => {
    setCodeValidationLoading(true);
    setCodeValidationError(null);
    try {
      const result = await api<ValidationResult>('/api/plugins/validate_code', {
        method: 'POST',
        body: JSON.stringify({ code: generatedCode }),
      });
      setCodeValidation(result);
    } catch (err) {
      setCodeValidationError((err as Error).message);
    } finally {
      setCodeValidationLoading(false);
    }
  };

  const validateCustomCode = async () => {
    if (!customCode.trim()) {
      setCustomValidationError('Paste plugin code to validate.');
      setCustomValidation(null);
      return;
    }
    setCustomValidationLoading(true);
    setCustomValidationError(null);
    try {
      const result = await api<ValidationResult>('/api/plugins/validate_code', {
        method: 'POST',
        body: JSON.stringify({ code: customCode }),
      });
      setCustomValidation(result);
    } catch (err) {
      setCustomValidationError((err as Error).message);
    } finally {
      setCustomValidationLoading(false);
    }
  };

  const buildValidationSummary = (result: ValidationResult) => {
    if (result.valid) {
      if (result.warning_count > 0) {
        return `Plugin is valid with ${result.warning_count} warning(s)`;
      }
      return 'Plugin is valid with no issues';
    }
    let summary = `Plugin has ${result.error_count} error(s)`;
    if (result.warning_count > 0) {
      summary += ` and ${result.warning_count} warning(s)`;
    }
    return summary;
  };

  return (
    <div className="card protocol-studio">
      <div className="studio-header">
        <div>
          <p className="eyebrow">Protocol Studio</p>
          <h2>Define, generate, and validate plugins</h2>
          <p>Build protocol models visually, then validate generated or custom plugin code.</p>
        </div>
        <div className="studio-tip">
          <span className="tip-label">Tip</span>
          <p>Defaults for bytes should be hex (e.g., DE AD BE EF). Seeds accept hex per line.</p>
        </div>
      </div>

      <div className="studio-grid">
        <section className="studio-panel">
          <div className="panel-header">
            <h3>Protocol Definition</h3>
            <p>Describe the request model and optional state machine.</p>
          </div>
          <div className="panel-section">
            <h4>Metadata</h4>
            <div className="form-grid">
              <label>
                Module Name
                <input value={moduleName} onChange={(e) => setModuleName(e.target.value)} placeholder="my_protocol" />
              </label>
              <label>
                Version
                <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="0.1.0" />
              </label>
              <label className="span-2">
                Description
                <input
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Short description for your protocol"
                />
              </label>
            </div>
          </div>

          <div className="panel-section">
            <div className="section-header">
              <div className="header-with-tooltip">
                <h4>Blocks</h4>
                <InfoTooltip label="Blocks help" className="inline">
                  <p>Blocks are ordered fields that map directly to on-wire bytes/bits.</p>
                  <p>They are not arbitrary groupings; order controls parsing and serialization.</p>
                </InfoTooltip>
              </div>
              <button type="button" onClick={addBlock} className="secondary-button">
                Add Block
              </button>
            </div>
            <p className="section-hint">
              Blocks define the packet layout in order. Size values are in bytes unless the type is <code>bits</code>.
            </p>
            <div className="blocks-list">
              {blocks.map((block, index) => (
                <div key={block.id} className="block-card">
                  <div className="block-title">
                    <strong>Block {index + 1}</strong>
                    {blocks.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeBlock(block.id)}
                        className="text-button"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <div className="form-grid">
                    <label>
                      Name
                      <input
                        value={block.name}
                        onChange={(e) => updateBlock(block.id, { name: e.target.value })}
                        placeholder="field_name"
                      />
                    </label>
                    <label>
                      Type
                      <select
                        value={block.type}
                        onChange={(e) => updateBlock(block.id, { type: e.target.value as FieldType })}
                      >
                        {FIELD_TYPES.map((type) => (
                          <option key={type} value={type}>
                            {type}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Size
                        <InfoTooltip label="Size help" className="inline">
                          <p>For <code>bytes</code> and integers, size is in bytes.</p>
                          <p>For <code>bits</code>, size is in bits (1-64).</p>
                        </InfoTooltip>
                      </span>
                      <input
                        value={block.size}
                        onChange={(e) => updateBlock(block.id, { size: e.target.value })}
                        placeholder={block.type === 'bits' ? '4' : 'Bytes'}
                      />
                    </label>
                    <label>
                      Max Size
                      <input
                        value={block.maxSize}
                        onChange={(e) => updateBlock(block.id, { maxSize: e.target.value })}
                        placeholder="Optional"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Default
                        <InfoTooltip label="Default value help" className="inline">
                          <p>Bytes defaults accept hex (e.g., DE AD BE EF) or a raw string.</p>
                          <p>Integers accept decimal or 0x-prefixed hex.</p>
                        </InfoTooltip>
                      </span>
                      <input
                        value={block.defaultValue}
                        onChange={(e) => updateBlock(block.id, { defaultValue: e.target.value })}
                        placeholder={block.type === 'bytes' ? 'DE AD BE EF' : 'Optional'}
                      />
                    </label>
                    <label>
                      Endian
                      <select
                        value={block.endian}
                        onChange={(e) => updateBlock(block.id, { endian: e.target.value as EndianType })}
                      >
                        <option value="">Default</option>
                        <option value="big">big</option>
                        <option value="little">little</option>
                      </select>
                    </label>
                    <label>
                      Bit Order
                      <select
                        value={block.bitOrder}
                        onChange={(e) => updateBlock(block.id, { bitOrder: e.target.value as BitOrder })}
                      >
                        <option value="">Default</option>
                        <option value="msb">msb</option>
                        <option value="lsb">lsb</option>
                      </select>
                    </label>
                    <label>
                      Mutable
                      <select
                        value={block.mutable ? 'yes' : 'no'}
                        onChange={(e) => updateBlock(block.id, { mutable: e.target.value === 'yes' })}
                      >
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                      </select>
                    </label>
                    <label className="span-2">
                      Description
                      <input
                        value={block.description}
                        onChange={(e) => updateBlock(block.id, { description: e.target.value })}
                        placeholder="Optional field notes"
                      />
                    </label>
                  </div>
                  <div className="form-grid inline-grid">
                    <label>
                      <span className="label-with-tooltip">
                        Size Field
                        <InfoTooltip label="Size field help" className="inline">
                          <p>Enable for length fields that should auto-update.</p>
                          <p>Use Size Of to list target fields in order.</p>
                        </InfoTooltip>
                      </span>
                      <select
                        value={block.isSizeField ? 'yes' : 'no'}
                        onChange={(e) => updateBlock(block.id, { isSizeField: e.target.value === 'yes' })}
                      >
                        <option value="no">No</option>
                        <option value="yes">Yes</option>
                      </select>
                    </label>
                    <label>
                      Size Of
                      <input
                        value={block.sizeOf}
                        onChange={(e) => updateBlock(block.id, { sizeOf: e.target.value })}
                        placeholder="payload, checksum"
                      />
                    </label>
                    <label>
                      Size Unit
                      <select
                        value={block.sizeUnit}
                        onChange={(e) => updateBlock(block.id, { sizeUnit: e.target.value as SizeUnit })}
                      >
                        {SIZE_UNITS.map((unit) => (
                          <option key={unit || 'default'} value={unit}>
                            {unit || 'default'}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel-section">
            <div className="header-with-tooltip">
              <h4>Seeds</h4>
              <InfoTooltip label="Seeds help" className="inline">
                <p>Seeds are optional. If omitted, the server auto-generates baseline seeds.</p>
                <p>One hex payload per line keeps previews deterministic.</p>
              </InfoTooltip>
            </div>
            <textarea
              value={seeds}
              onChange={(e) => setSeeds(e.target.value)}
              placeholder="One hex seed per line (e.g., 45 00 00 54 ...)"
            />
          </div>

          <div className="panel-section">
            <div className="section-header">
              <div className="header-with-tooltip">
                <h4>State Model</h4>
                <InfoTooltip label="State model help" className="inline">
                  <p>Optional for stateless protocols.</p>
                  <p>For stateful protocols, define states and transitions to guide walkers.</p>
                </InfoTooltip>
              </div>
              <button type="button" onClick={addTransition} className="secondary-button">
                Add Transition
              </button>
            </div>
            <div className="form-grid">
              <label>
                Initial State
                <input value={initialState} onChange={(e) => setInitialState(e.target.value)} />
              </label>
              <label className="span-2">
                States (comma-separated)
                <input
                  value={states}
                  onChange={(e) => setStates(e.target.value)}
                  placeholder="INIT, AUTH, READY"
                />
              </label>
            </div>
            <div className="transitions-list">
              {transitions.map((transition, index) => (
                <div key={transition.id} className="transition-row">
                  <div className="transition-header">
                    <strong>Transition {index + 1}</strong>
                    {transitions.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeTransition(transition.id)}
                        className="text-button"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <div className="form-grid">
                    <label>
                      From
                      <input
                        value={transition.from}
                        onChange={(e) => updateTransition(transition.id, { from: e.target.value })}
                        placeholder="INIT"
                      />
                    </label>
                    <label>
                      To
                      <input
                        value={transition.to}
                        onChange={(e) => updateTransition(transition.id, { to: e.target.value })}
                        placeholder="READY"
                      />
                    </label>
                    <label>
                      Message Type
                      <input
                        value={transition.messageType}
                        onChange={(e) => updateTransition(transition.id, { messageType: e.target.value })}
                        placeholder="login_request"
                      />
                    </label>
                    <label>
                      Trigger
                      <input
                        value={transition.trigger}
                        onChange={(e) => updateTransition(transition.id, { trigger: e.target.value })}
                        placeholder="response_ok"
                      />
                    </label>
                    <label className="span-2">
                      Expected Response
                      <input
                        value={transition.expectedResponse}
                        onChange={(e) => updateTransition(transition.id, { expectedResponse: e.target.value })}
                        placeholder="login_ack"
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="studio-panel">
          <div className="panel-header">
            <h3>Generated Plugin Code</h3>
            <p>Copy this into a plugin file, or validate it before saving.</p>
          </div>
          <div className="panel-section">
            <textarea className="code-area" readOnly value={generatedCode} />
            <div className="button-row">
              <button type="button" onClick={validateGeneratedCode} disabled={codeValidationLoading}>
                {codeValidationLoading ? 'Validating…' : 'Validate Generated Code'}
              </button>
            </div>
            {codeValidationError && <p className="error">{codeValidationError}</p>}
            {codeValidation && (
              <ValidationPanel
                issues={codeValidation.issues}
                valid={codeValidation.valid}
                summary={buildValidationSummary(codeValidation)}
                pluginName={codeValidation.plugin_name}
              />
            )}
          </div>

          <div className="panel-section">
            <div className="section-header">
              <h4>Validate Custom Plugin Code</h4>
              <button type="button" onClick={validateCustomCode} disabled={customValidationLoading}>
                {customValidationLoading ? 'Validating…' : 'Validate Custom Code'}
              </button>
            </div>
            <textarea
              className="code-area"
              value={customCode}
              onChange={(e) => setCustomCode(e.target.value)}
              placeholder="Paste an existing plugin to validate it without loading from disk."
            />
            {customValidationError && <p className="error">{customValidationError}</p>}
            {customValidation && (
              <ValidationPanel
                issues={customValidation.issues}
                valid={customValidation.valid}
                summary={buildValidationSummary(customValidation)}
                pluginName={customValidation.plugin_name}
              />
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

export default ProtocolStudioPage;
