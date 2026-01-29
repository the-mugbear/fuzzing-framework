import { useMemo, useState } from 'react';
import Tooltip from '../components/Tooltip';
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
type ResponseOperation = '' | 'add_constant' | 'xor_constant' | 'and_mask' | 'or_mask' | 'shift_left' | 'shift_right';

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

interface MatchRule {
  id: string;
  field: string;
  values: string;
}

interface SetFieldRule {
  id: string;
  targetField: string;
  sourceType: 'literal' | 'copy';
  literalValue: string;
  responseField: string;
  extractStart: string;
  extractCount: string;
  operation: ResponseOperation;
  operationValue: string;
}

interface ResponseHandlerRow {
  id: string;
  name: string;
  matchRules: MatchRule[];
  setRules: SetFieldRule[];
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
const RESPONSE_OPERATIONS: ResponseOperation[] = [
  '',
  'add_constant',
  'xor_constant',
  'and_mask',
  'or_mask',
  'shift_left',
  'shift_right',
];

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

const EMPTY_MATCH_RULE: MatchRule = {
  id: 'match-1',
  field: '',
  values: '',
};

const EMPTY_SET_RULE: SetFieldRule = {
  id: 'set-1',
  targetField: '',
  sourceType: 'copy',
  literalValue: '',
  responseField: '',
  extractStart: '',
  extractCount: '',
  operation: '',
  operationValue: '',
};

const EMPTY_RESPONSE_HANDLER: ResponseHandlerRow = {
  id: 'handler-1',
  name: '',
  matchRules: [{ ...EMPTY_MATCH_RULE }],
  setRules: [{ ...EMPTY_SET_RULE }],
};

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

function formatPythonScalar(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return '""';
  }
  if (isHexBytes(trimmed)) {
    return hexToPythonBytes(trimmed);
  }
  if (
    trimmed.startsWith('b"') ||
    trimmed.startsWith("b'") ||
    trimmed.startsWith('"') ||
    trimmed.startsWith("'") ||
    /^-?(0x[0-9a-fA-F]+|\d+)$/.test(trimmed) ||
    /^(True|False|None)$/.test(trimmed)
  ) {
    return trimmed;
  }
  return buildPythonStringLiteral(trimmed);
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

function buildMatchValue(value: string): string {
  const values = value
    .split(',')
    .map((entry) => entry.trim())
    .filter(Boolean);

  if (values.length > 1) {
    return `[${values.map((entry) => formatPythonScalar(entry)).join(', ')}]`;
  }
  if (values.length === 1) {
    return formatPythonScalar(values[0]);
  }
  return formatPythonScalar('');
}

function buildSetFieldValue(rule: SetFieldRule): string {
  if (rule.sourceType === 'literal') {
    return formatPythonScalar(rule.literalValue);
  }

  const specs: string[] = [];
  if (rule.responseField.trim()) {
    specs.push(`"copy_from_response": "${rule.responseField.trim()}"`);
  }

  const start = Number(rule.extractStart);
  const count = Number(rule.extractCount);
  if (!Number.isNaN(start) && !Number.isNaN(count)) {
    specs.push(`"extract_bits": {"start": ${start}, "count": ${count}}`);
  }

  if (rule.operation) {
    specs.push(`"operation": "${rule.operation}"`);
    if (rule.operationValue.trim()) {
      specs.push(`"value": ${formatPythonScalar(rule.operationValue)}`);
    }
  }

  return `{ ${specs.join(', ')} }`;
}

function buildPluginCode(
  moduleName: string,
  version: string,
  description: string,
  blocks: BlockRow[],
  responseBlocks: BlockRow[],
  seeds: string[],
  initialState: string,
  states: string[],
  transitions: TransitionRow[],
  responseHandlers: ResponseHandlerRow[],
): string {
  const filteredBlocks = blocks.filter((block) => block.name.trim());
  const blockLines = filteredBlocks.map((block) => {
    const blockDict = buildBlockPython(block);
    const formatted = formatPythonDict(blockDict, '        ');
    return `    {\n${formatted}\n    },`;
  });

  const filteredResponseBlocks = responseBlocks.filter((block) => block.name.trim());
  const responseBlockLines = filteredResponseBlocks.map((block) => {
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

  const handlers = responseHandlers.filter((handler) => handler.name.trim());
  const handlerLines = handlers.map((handler) => {
    const matchLines = handler.matchRules
      .filter((rule) => rule.field.trim())
      .map((rule) => `        "${rule.field.trim()}": ${buildMatchValue(rule.values)},`)
      .join('\n');
    const setLines = handler.setRules
      .filter((rule) => rule.targetField.trim())
      .map((rule) => `        "${rule.targetField.trim()}": ${buildSetFieldValue(rule)},`)
      .join('\n');

    return `    {\n        "name": "${handler.name.trim()}",\n        "match": {\n${matchLines || '            # Add match rules\n'}        },\n        "set_fields": {\n${setLines || '            # Add field updates\n'}        }\n    },`;
  });

  const responseModelBlock = filteredResponseBlocks.length
    ? `\nresponse_model = {\n    "blocks": [\n${responseBlockLines.join('\n')}\n    ]\n}\n`
    : '';

  const responseHandlerBlock = handlers.length
    ? `\nresponse_handlers = [\n${handlerLines.join('\n')}\n]\n`
    : '';

  const moduleHeader = moduleName.trim() || 'new_protocol';
  const versionValue = version.trim() || '0.1.0';

  return `"""\nProtocol plugin generated by Protocol Studio.\n\nModule: ${moduleHeader}\n"""\n\n__version__ = "${versionValue}"\n\ndata_model = {\n    "name": "${moduleHeader}",\n    "description": ${description.trim() ? buildPythonStringLiteral(description.trim()) : '""'},\n    "version": "${versionValue}",\n    "blocks": [\n${blockLines.join('\n') || '        # TODO: add blocks\\n        {"name": "field", "type": "uint8"},'}\n    ],\n    "seeds": [\n${seedLines.map((seed) => `        ${seed},`).join('\n') || '        # Optional: add base seeds\\n'}\n    ]\n}\n\nstate_model = {\n    "initial_state": "${initialState.trim() || 'INIT'}",\n    "states": ${stateList.length ? JSON.stringify(stateList) : '["INIT"]'},\n    "transitions": [\n${transitionLines.join('\n') || '        # Optional: add transitions\\n'}\n    ]\n}\n${responseModelBlock}${responseHandlerBlock}`;
}

function ProtocolStudioPage() {
  const [moduleName, setModuleName] = useState('custom_protocol');
  const [version, setVersion] = useState('0.1.0');
  const [description, setDescription] = useState('');
  const [blocks, setBlocks] = useState<BlockRow[]>([{ ...EMPTY_BLOCK }]);
  const [responseBlocks, setResponseBlocks] = useState<BlockRow[]>([{ ...EMPTY_BLOCK, id: 'response-block-1' }]);
  const [seeds, setSeeds] = useState('');
  const [initialState, setInitialState] = useState('INIT');
  const [states, setStates] = useState('INIT');
  const [transitions, setTransitions] = useState<TransitionRow[]>([{ ...EMPTY_TRANSITION }]);
  const [responseHandlers, setResponseHandlers] = useState<ResponseHandlerRow[]>([
    { ...EMPTY_RESPONSE_HANDLER, id: 'handler-1' },
  ]);
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
      responseBlocks,
      seedLines,
      initialState,
      stateList,
      transitions,
      responseHandlers,
    );
  }, [moduleName, version, description, blocks, responseBlocks, seeds, initialState, states, transitions, responseHandlers]);

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

  const updateResponseBlock = (id: string, updates: Partial<BlockRow>) => {
    setResponseBlocks((prev) => prev.map((block) => (block.id === id ? { ...block, ...updates } : block)));
  };

  const addResponseBlock = () => {
    setResponseBlocks((prev) => [
      ...prev,
      {
        ...EMPTY_BLOCK,
        id: `response-block-${prev.length + 1}`,
      },
    ]);
  };

  const removeResponseBlock = (id: string) => {
    setResponseBlocks((prev) => prev.filter((block) => block.id !== id));
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

  const updateResponseHandler = (id: string, updates: Partial<ResponseHandlerRow>) => {
    setResponseHandlers((prev) => prev.map((handler) => (handler.id === id ? { ...handler, ...updates } : handler)));
  };

  const addResponseHandler = () => {
    setResponseHandlers((prev) => [
      ...prev,
      {
        ...EMPTY_RESPONSE_HANDLER,
        id: `handler-${prev.length + 1}`,
      },
    ]);
  };

  const removeResponseHandler = (id: string) => {
    setResponseHandlers((prev) => prev.filter((handler) => handler.id !== id));
  };

  const updateMatchRule = (handlerId: string, ruleId: string, updates: Partial<MatchRule>) => {
    setResponseHandlers((prev) =>
      prev.map((handler) => {
        if (handler.id !== handlerId) return handler;
        return {
          ...handler,
          matchRules: handler.matchRules.map((rule) => (rule.id === ruleId ? { ...rule, ...updates } : rule)),
        };
      }),
    );
  };

  const addMatchRule = (handlerId: string) => {
    setResponseHandlers((prev) =>
      prev.map((handler) => {
        if (handler.id !== handlerId) return handler;
        return {
          ...handler,
          matchRules: [
            ...handler.matchRules,
            {
              ...EMPTY_MATCH_RULE,
              id: `match-${handler.matchRules.length + 1}`,
            },
          ],
        };
      }),
    );
  };

  const removeMatchRule = (handlerId: string, ruleId: string) => {
    setResponseHandlers((prev) =>
      prev.map((handler) => {
        if (handler.id !== handlerId) return handler;
        return {
          ...handler,
          matchRules: handler.matchRules.filter((rule) => rule.id !== ruleId),
        };
      }),
    );
  };

  const updateSetRule = (handlerId: string, ruleId: string, updates: Partial<SetFieldRule>) => {
    setResponseHandlers((prev) =>
      prev.map((handler) => {
        if (handler.id !== handlerId) return handler;
        return {
          ...handler,
          setRules: handler.setRules.map((rule) => (rule.id === ruleId ? { ...rule, ...updates } : rule)),
        };
      }),
    );
  };

  const addSetRule = (handlerId: string) => {
    setResponseHandlers((prev) =>
      prev.map((handler) => {
        if (handler.id !== handlerId) return handler;
        return {
          ...handler,
          setRules: [
            ...handler.setRules,
            {
              ...EMPTY_SET_RULE,
              id: `set-${handler.setRules.length + 1}`,
            },
          ],
        };
      }),
    );
  };

  const removeSetRule = (handlerId: string, ruleId: string) => {
    setResponseHandlers((prev) =>
      prev.map((handler) => {
        if (handler.id !== handlerId) return handler;
        return {
          ...handler,
          setRules: handler.setRules.filter((rule) => rule.id !== ruleId),
        };
      }),
    );
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
                <span className="label-with-tooltip">
                  Module Name
                  <Tooltip content="Python module identifier for the plugin. Used in generated code and displayed in the UI." />
                </span>
                <input value={moduleName} onChange={(e) => setModuleName(e.target.value)} placeholder="my_protocol" />
              </label>
              <label>
                <span className="label-with-tooltip">
                  Version
                  <Tooltip content="Semantic version for your plugin. Helps track protocol changes over time." />
                </span>
                <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder="0.1.0" />
              </label>
              <label className="span-2">
                <span className="label-with-tooltip">
                  Description
                  <Tooltip content="Short summary shown in the UI and documentation." />
                </span>
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
                <Tooltip content="Blocks are ordered fields that map directly to on-wire bytes/bits. Order controls parsing and serialization." />
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
                      <span className="label-with-tooltip">
                        Name
                        <Tooltip content="Unique identifier for this field. Used by size fields, response handlers, and validators." />
                      </span>
                      <input
                        value={block.name}
                        onChange={(e) => updateBlock(block.id, { name: e.target.value })}
                        placeholder="field_name"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Type
                        <Tooltip content="Defines how the field is parsed and serialized. Bit fields support 1-64 bits." />
                      </span>
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
                        <Tooltip content="For bytes/integers, size is in bytes. For bits, size is in bits (1-64)." />
                      </span>
                      <input
                        value={block.size}
                        onChange={(e) => updateBlock(block.id, { size: e.target.value })}
                        placeholder={block.type === 'bits' ? '4' : 'Bytes'}
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Max Size
                        <Tooltip content="Optional upper bound for variable-length bytes/string fields." />
                      </span>
                      <input
                        value={block.maxSize}
                        onChange={(e) => updateBlock(block.id, { maxSize: e.target.value })}
                        placeholder="Optional"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Default
                        <Tooltip content="Bytes accept hex (DE AD BE EF) or strings. Integers accept decimal or 0x hex." />
                      </span>
                      <input
                        value={block.defaultValue}
                        onChange={(e) => updateBlock(block.id, { defaultValue: e.target.value })}
                        placeholder={block.type === 'bytes' ? 'DE AD BE EF' : 'Optional'}
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Endian
                        <Tooltip content="Byte order for multi-byte integers. Use big for network order, little for host." />
                      </span>
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
                      <span className="label-with-tooltip">
                        Bit Order
                        <Tooltip content="Controls how bits are ordered within bytes. Keep default for MSB-first protocols." />
                      </span>
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
                      <span className="label-with-tooltip">
                        Mutable
                        <Tooltip content="Allow the mutator to change this field. Mark false for checksums or fixed headers." />
                      </span>
                      <select
                        value={block.mutable ? 'yes' : 'no'}
                        onChange={(e) => updateBlock(block.id, { mutable: e.target.value === 'yes' })}
                      >
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                      </select>
                    </label>
                    <label className="span-2">
                      <span className="label-with-tooltip">
                        Description
                        <Tooltip content="Human-readable notes shown in UI and documentation." />
                      </span>
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
                        <Tooltip content="Enable for length fields that should auto-update based on target fields." />
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
                      <span className="label-with-tooltip">
                        Size Of
                        <Tooltip content="Comma-separated list of fields this size field covers. Order matters." />
                      </span>
                      <input
                        value={block.sizeOf}
                        onChange={(e) => updateBlock(block.id, { sizeOf: e.target.value })}
                        placeholder="payload, checksum"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Size Unit
                        <Tooltip content="Units for the size field (bytes, bits, words). Defaults to bytes." />
                      </span>
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
            <div className="section-header">
              <div className="header-with-tooltip">
                <h4>Response Model</h4>
                <Tooltip content="Define the structure of server responses. Response blocks are ordered fields like request blocks." />
              </div>
              <button type="button" onClick={addResponseBlock} className="secondary-button">
                Add Response Block
              </button>
            </div>
            <p className="section-hint">
              Response model blocks are optional, but required for response handlers.
            </p>
            <div className="blocks-list">
              {responseBlocks.map((block, index) => (
                <div key={block.id} className="block-card">
                  <div className="block-title">
                    <strong>Response Block {index + 1}</strong>
                    {responseBlocks.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeResponseBlock(block.id)}
                        className="text-button"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <div className="form-grid">
                    <label>
                      <span className="label-with-tooltip">
                        Name
                        <Tooltip content="Identifier for the response field. Used by response handlers and parsing." />
                      </span>
                      <input
                        value={block.name}
                        onChange={(e) => updateResponseBlock(block.id, { name: e.target.value })}
                        placeholder="response_field"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Type
                        <Tooltip content="Defines how incoming bytes are parsed. Use bits for packed flags, bytes for raw payloads." />
                      </span>
                      <select
                        value={block.type}
                        onChange={(e) => updateResponseBlock(block.id, { type: e.target.value as FieldType })}
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
                        <Tooltip content="For bytes/integers, size is in bytes. For bits, size is in bits (1-64)." />
                      </span>
                      <input
                        value={block.size}
                        onChange={(e) => updateResponseBlock(block.id, { size: e.target.value })}
                        placeholder={block.type === 'bits' ? '4' : 'Bytes'}
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Max Size
                        <Tooltip content="Optional limit for variable response fields to guard against oversized payloads." />
                      </span>
                      <input
                        value={block.maxSize}
                        onChange={(e) => updateResponseBlock(block.id, { maxSize: e.target.value })}
                        placeholder="Optional"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Default
                        <Tooltip content="Defaults are for documentation; response parsing uses live bytes." />
                      </span>
                      <input
                        value={block.defaultValue}
                        onChange={(e) => updateResponseBlock(block.id, { defaultValue: e.target.value })}
                        placeholder={block.type === 'bytes' ? 'DE AD BE EF' : 'Optional'}
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Endian
                        <Tooltip content="Byte order for multi-byte response fields. Use big for network order." />
                      </span>
                      <select
                        value={block.endian}
                        onChange={(e) => updateResponseBlock(block.id, { endian: e.target.value as EndianType })}
                      >
                        <option value="">Default</option>
                        <option value="big">big</option>
                        <option value="little">little</option>
                      </select>
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Bit Order
                        <Tooltip content="Controls bit ordering within each byte. Only relevant for bits fields." />
                      </span>
                      <select
                        value={block.bitOrder}
                        onChange={(e) => updateResponseBlock(block.id, { bitOrder: e.target.value as BitOrder })}
                      >
                        <option value="">Default</option>
                        <option value="msb">msb</option>
                        <option value="lsb">lsb</option>
                      </select>
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Mutable
                        <Tooltip content="Controls if this field is fuzzed. Typically false for fixed response headers." />
                      </span>
                      <select
                        value={block.mutable ? 'yes' : 'no'}
                        onChange={(e) => updateResponseBlock(block.id, { mutable: e.target.value === 'yes' })}
                      >
                        <option value="yes">Yes</option>
                        <option value="no">No</option>
                      </select>
                    </label>
                    <label className="span-2">
                      <span className="label-with-tooltip">
                        Description
                        <Tooltip content="Optional notes about this response field for protocol documentation." />
                      </span>
                      <input
                        value={block.description}
                        onChange={(e) => updateResponseBlock(block.id, { description: e.target.value })}
                        placeholder="Optional response field notes"
                      />
                    </label>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="panel-section">
            <div className="header-with-tooltip">
              <h4>Seeds</h4>
              <Tooltip content="Seeds are optional. If omitted, the server auto-generates baseline seeds." />
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
                <Tooltip content="Optional for stateless protocols. Define states and transitions to guide walkers." />
              </div>
              <button type="button" onClick={addTransition} className="secondary-button">
                Add Transition
              </button>
            </div>
            <div className="form-grid">
              <label>
                <span className="label-with-tooltip">
                  Initial State
                  <Tooltip content="Starting state for the state machine. Use INIT or DISCONNECTED." />
                </span>
                <input value={initialState} onChange={(e) => setInitialState(e.target.value)} />
              </label>
              <label className="span-2">
                <span className="label-with-tooltip">
                  States (comma-separated)
                  <Tooltip content="All possible states for the protocol. Maps to state_model.states." />
                </span>
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
                      <span className="label-with-tooltip">
                        From
                        <Tooltip content="State where this transition starts." />
                      </span>
                      <input
                        value={transition.from}
                        onChange={(e) => updateTransition(transition.id, { from: e.target.value })}
                        placeholder="INIT"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        To
                        <Tooltip content="State where this transition ends." />
                      </span>
                      <input
                        value={transition.to}
                        onChange={(e) => updateTransition(transition.id, { to: e.target.value })}
                        placeholder="READY"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Message Type
                        <Tooltip content="Optional label that ties a transition to a message type." />
                      </span>
                      <input
                        value={transition.messageType}
                        onChange={(e) => updateTransition(transition.id, { messageType: e.target.value })}
                        placeholder="login_request"
                      />
                    </label>
                    <label>
                      <span className="label-with-tooltip">
                        Trigger
                        <Tooltip content="Optional event label for orchestration or documentation." />
                      </span>
                      <input
                        value={transition.trigger}
                        onChange={(e) => updateTransition(transition.id, { trigger: e.target.value })}
                        placeholder="response_ok"
                      />
                    </label>
                    <label className="span-2">
                      <span className="label-with-tooltip">
                        Expected Response
                        <Tooltip content="Optional response label to verify transition completion." />
                      </span>
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

          <div className="panel-section">
            <div className="section-header">
              <div className="header-with-tooltip">
                <h4>Response Handlers</h4>
                <Tooltip content="Match response fields and copy or transform values into the next request." />
              </div>
              <button type="button" onClick={addResponseHandler} className="secondary-button">
                Add Handler
              </button>
            </div>
            <p className="section-hint">
              Handlers fire when match rules pass; they update request fields for the next message.
            </p>
            <div className="handlers-list">
              {responseHandlers.map((handler, index) => (
                <div key={handler.id} className="handler-card">
                  <div className="handler-header">
                    <strong>Handler {index + 1}</strong>
                    {responseHandlers.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeResponseHandler(handler.id)}
                        className="text-button"
                      >
                        Remove
                      </button>
                    )}
                  </div>
                  <label>
                    <span className="label-with-tooltip">
                      Handler Name
                      <Tooltip content="Identifier for the response handler. Use a descriptive name like sync_session_token." />
                    </span>
                    <input
                      value={handler.name}
                      onChange={(e) => updateResponseHandler(handler.id, { name: e.target.value })}
                      placeholder="sync_session_token"
                    />
                  </label>
                  <div className="handler-section">
                    <div className="section-header">
                      <div className="header-with-tooltip">
                        <h5>Match Rules</h5>
                        <Tooltip content="All match rules must pass for the handler to fire. Comma-separated values become OR." />
                      </div>
                      <button type="button" onClick={() => addMatchRule(handler.id)} className="secondary-button">
                        Add Match
                      </button>
                    </div>
                    <p className="section-hint">Comma-separated values are treated as OR matches.</p>
                    {handler.matchRules.map((rule) => (
                      <div key={rule.id} className="handler-row">
                        <label className="handler-field">
                          <span className="label-with-tooltip">
                            Field
                            <Tooltip content="Response field name to match against." />
                          </span>
                          <input
                            value={rule.field}
                            onChange={(e) => updateMatchRule(handler.id, rule.id, { field: e.target.value })}
                            placeholder="status"
                          />
                        </label>
                        <label className="handler-field">
                          <span className="label-with-tooltip">
                            Values
                            <Tooltip content="Comma-separated allowed values (e.g., 0x00, 0x01)." />
                          </span>
                          <input
                            value={rule.values}
                            onChange={(e) => updateMatchRule(handler.id, rule.id, { values: e.target.value })}
                            placeholder="0x00, 0x01"
                          />
                        </label>
                        {handler.matchRules.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeMatchRule(handler.id, rule.id)}
                            className="text-button"
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                  <div className="handler-section">
                    <div className="section-header">
                      <div className="header-with-tooltip">
                        <h5>Set Fields</h5>
                        <Tooltip content="Copy from a response field or set a literal. Extract bits and apply operations." />
                      </div>
                      <button type="button" onClick={() => addSetRule(handler.id)} className="secondary-button">
                        Add Field
                      </button>
                    </div>
                    {handler.setRules.map((rule) => (
                      <div key={rule.id} className="handler-row">
                        <label className="handler-field">
                          <span className="label-with-tooltip">
                            Target Field
                            <Tooltip content="Request field to update before the next send." />
                          </span>
                          <input
                            value={rule.targetField}
                            onChange={(e) => updateSetRule(handler.id, rule.id, { targetField: e.target.value })}
                            placeholder="session_id"
                          />
                        </label>
                        <label className="handler-field">
                          <span className="label-with-tooltip">
                            Source
                            <Tooltip content="Copy a response field or set a literal value." />
                          </span>
                          <select
                            value={rule.sourceType}
                            onChange={(e) =>
                              updateSetRule(handler.id, rule.id, { sourceType: e.target.value as 'literal' | 'copy' })
                            }
                          >
                            <option value="copy">Copy from response</option>
                            <option value="literal">Literal value</option>
                          </select>
                        </label>
                        {rule.sourceType === 'literal' ? (
                          <label className="handler-field">
                            <span className="label-with-tooltip">
                              Literal
                              <Tooltip content="Value to assign directly to the target field." />
                            </span>
                            <input
                              value={rule.literalValue}
                              onChange={(e) => updateSetRule(handler.id, rule.id, { literalValue: e.target.value })}
                              placeholder="0x10"
                            />
                          </label>
                        ) : (
                          <>
                            <label className="handler-field">
                              <span className="label-with-tooltip">
                                Response Field
                                <Tooltip content="Response field to copy from." />
                              </span>
                              <input
                                value={rule.responseField}
                                onChange={(e) => updateSetRule(handler.id, rule.id, { responseField: e.target.value })}
                                placeholder="session_token"
                              />
                            </label>
                            <label className="handler-field">
                              <span className="label-with-tooltip">
                                Bit Start
                                <Tooltip content="Start bit for extract_bits (0-based)." />
                              </span>
                              <input
                                value={rule.extractStart}
                                onChange={(e) => updateSetRule(handler.id, rule.id, { extractStart: e.target.value })}
                                placeholder="bit start"
                              />
                            </label>
                            <label className="handler-field">
                              <span className="label-with-tooltip">
                                Bit Count
                                <Tooltip content="Number of bits to extract." />
                              </span>
                              <input
                                value={rule.extractCount}
                                onChange={(e) => updateSetRule(handler.id, rule.id, { extractCount: e.target.value })}
                                placeholder="bit count"
                              />
                            </label>
                            <label className="handler-field">
                              <span className="label-with-tooltip">
                                Operation
                                <Tooltip content="Optional transformation applied after copying." />
                              </span>
                              <select
                                value={rule.operation}
                                onChange={(e) =>
                                  updateSetRule(handler.id, rule.id, { operation: e.target.value as ResponseOperation })
                                }
                              >
                                {RESPONSE_OPERATIONS.map((operation) => (
                                  <option key={operation || 'none'} value={operation}>
                                    {operation || 'no-op'}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label className="handler-field">
                              <span className="label-with-tooltip">
                                Op Value
                                <Tooltip content="Value used by the selected operation." />
                              </span>
                              <input
                                value={rule.operationValue}
                                onChange={(e) => updateSetRule(handler.id, rule.id, { operationValue: e.target.value })}
                                placeholder="op value"
                              />
                            </label>
                          </>
                        )}
                        {handler.setRules.length > 1 && (
                          <button
                            type="button"
                            onClick={() => removeSetRule(handler.id, rule.id)}
                            className="text-button"
                          >
                            Remove
                          </button>
                        )}
                      </div>
                    ))}
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
            <textarea className="code-area code-area--tall" readOnly value={generatedCode} />
            <div className="button-row">
              <button type="button" onClick={validateGeneratedCode} disabled={codeValidationLoading}>
                {codeValidationLoading ? 'Validating...' : 'Validate Generated Code'}
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
                {customValidationLoading ? 'Validating...' : 'Validate Custom Code'}
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
