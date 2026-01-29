import { ReactNode, useEffect, useReducer, useState } from 'react';
import StateMachineCard from '../components/StateMachineCard';
import ValidationPanel, { ValidationIssue } from '../components/ValidationPanel';
import { useDebounce } from '../hooks/useDebounce';
import { api } from '../services/api';
import './PluginDebuggerPage.css';

interface DataBlock {
  name: string;
  type: string;
  description?: string;
  default?: unknown;
  mutable?: boolean;
  behavior?: Record<string, unknown>;
  size?: number;
  size_of?: string;
  is_size_field?: boolean;
  endian?: string;
  bit_order?: string;
  references?: string | string[] | null;
}

interface PluginStateModel {
  initial_state?: string;
  states?: string[];
  transitions?: Array<{
    from: string;
    to: string;
    message_type?: string;
    trigger?: string;
    expected_response?: string;
  }>;
}

interface ResponseHandler {
  name: string;
  match: Record<string, unknown>;
  set_fields: Record<string, unknown>;
}

interface PluginDetails {
  name: string;
  description?: string;
  data_model: { blocks: DataBlock[] };
  response_model?: { blocks: DataBlock[] };
  response_handlers?: ResponseHandler[];
  state_model?: PluginStateModel;
}

interface PreviewField {
  name: string;
  value: unknown;
  hex: string;
  type: string;
  mutable: boolean;
  computed: boolean;
  mutated: boolean;
  references?: string | string[] | null;
}

interface TestCasePreview {
  id: number;
  mode: string;
  mutation_type?: string;
  total_bytes: number;
  hex_dump: string;
  fields: PreviewField[];
}

interface PreviewResponse {
  previews: TestCasePreview[];
}

interface ValidationResult {
  valid: boolean;
  plugin_name: string;
  error_count: number;
  warning_count: number;
  issues: ValidationIssue[];
}

interface DebuggerState {
  plugins: string[];
  selected: string;
  details: PluginDetails | null;
  loadingDetails: boolean;
  error: string | null;
  previews: TestCasePreview[];
  previewLoading: boolean;
  previewError: string | null;
  validationResult: ValidationResult | null;
  validationLoading: boolean;
  validationError: string | null;
}

const initialState: DebuggerState = {
  plugins: [],
  selected: '',
  details: null,
  loadingDetails: false,
  error: null,
  previews: [],
  previewLoading: false,
  previewError: null,
  validationResult: null,
  validationLoading: false,
  validationError: null,
};

 type Action =
  | { type: 'set_plugins'; payload: string[] }
  | { type: 'set_selected'; payload: string }
  | { type: 'loading_details' }
  | { type: 'set_details'; payload: PluginDetails }
  | { type: 'set_error'; payload: string | null }
  | { type: 'loading_preview' }
  | { type: 'set_preview'; payload: TestCasePreview[] }
  | { type: 'set_preview_error'; payload: string | null }
  | { type: 'loading_validation' }
  | { type: 'set_validation'; payload: ValidationResult | null }
  | { type: 'set_validation_error'; payload: string | null };

function reducer(state: DebuggerState, action: Action): DebuggerState {
  switch (action.type) {
    case 'set_plugins':
      return { ...state, plugins: action.payload };
    case 'set_selected':
      return {
        ...state,
        selected: action.payload,
        previews: [],
        previewError: null,
        validationResult: null,
        validationError: null,
      };
    case 'loading_details':
      return { ...state, loadingDetails: true, error: null };
    case 'set_details':
      return { ...state, loadingDetails: false, details: action.payload };
    case 'set_error':
      return { ...state, error: action.payload, loadingDetails: false };
    case 'loading_preview':
      return { ...state, previewLoading: true, previewError: null };
    case 'set_preview':
      return { ...state, previewLoading: false, previews: action.payload };
    case 'set_preview_error':
      return { ...state, previewLoading: false, previewError: action.payload };
    case 'loading_validation':
      return { ...state, validationLoading: true, validationError: null };
    case 'set_validation':
      return { ...state, validationLoading: false, validationResult: action.payload };
    case 'set_validation_error':
      return { ...state, validationLoading: false, validationError: action.payload };
    default:
      return state;
  }
}

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
      i
      <span className="tooltip-content">{children}</span>
    </button>
  );
}

function PluginDebuggerPage() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [previewMode, setPreviewMode] = useState<'seeds' | 'mutations'>('seeds');
  const [previewCount, setPreviewCount] = useState(3);
  const [focusField, setFocusField] = useState('');
  const debouncedFocus = useDebounce(focusField, 400);

  useEffect(() => {
    api<string[]>('/api/plugins')
      .then((names) => {
        dispatch({ type: 'set_plugins', payload: names });
        if (names.length) {
          dispatch({ type: 'set_selected', payload: names[0] });
        }
      })
      .catch((err) => dispatch({ type: 'set_error', payload: err.message }));
  }, []);

  useEffect(() => {
    if (!state.selected) return;
    dispatch({ type: 'loading_details' });
    api<PluginDetails>(`/api/plugins/${state.selected}`)
      .then((details) => dispatch({ type: 'set_details', payload: details }))
      .catch((err) => dispatch({ type: 'set_error', payload: err.message }));
  }, [state.selected]);

  useEffect(() => {
    if (!state.selected) return;
    generatePreview();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.selected, previewMode, previewCount, debouncedFocus]);

  const generatePreview = async () => {
    if (!state.selected) return;
    dispatch({ type: 'loading_preview' });
    try {
      const body: Record<string, unknown> = {
        mode: previewMode,
        count: previewCount,
      };
      if (debouncedFocus.trim()) {
        body['focus_field'] = debouncedFocus.trim();
      }
      const response = await api<PreviewResponse>(`/api/plugins/${state.selected}/preview`, {
        method: 'POST',
        body: JSON.stringify(body),
      });
      dispatch({ type: 'set_preview', payload: response.previews });
    } catch (err) {
      dispatch({ type: 'set_preview_error', payload: (err as Error).message });
    }
  };

  const validatePlugin = async () => {
    if (!state.selected) return;
    dispatch({ type: 'loading_validation' });
    try {
      const result = await api<ValidationResult>(`/api/plugins/${state.selected}/validate`);
      dispatch({ type: 'set_validation', payload: result });
    } catch (err) {
      dispatch({ type: 'set_validation_error', payload: (err as Error).message });
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
    <div className="card">
      <div className="plugin-header">
        <div>
          <p className="eyebrow">Structure Map</p>
          <h2>Plugin Explorer</h2>
          <p>Inspect block definitions, state machines, and documentation before launching campaigns.</p>
        </div>
        <div className="plugin-selector">
          <div className="selector-label">
            Plugin
            <InfoTooltip label="Plugin picker details" className="inline">
              <p>Choose a protocol plugin to inspect its data_model, state_model, and validation checks.</p>
              <p>Loading a plugin executes its module to read the model definitions.</p>
            </InfoTooltip>
          </div>
          <select
            value={state.selected}
            onChange={(e) => dispatch({ type: 'set_selected', payload: e.target.value })}
            disabled={!state.plugins.length}
          >
            {state.plugins.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </div>
      </div>
      {state.error && <p className="error">{state.error}</p>}
      {state.details && (
        <div className="plugin-details">
          <div className="plugin-hero">
            <div>
              <h3>{state.details.name}</h3>
              {renderPluginDescription(state.details.description)}
            </div>
            <div className="plugin-meta">
              <div>
                <span>Blocks</span>
                <strong>{state.details.data_model.blocks?.length ?? 0}</strong>
              </div>
              <div>
                <span>States</span>
                <strong>{state.details.state_model?.states?.length ?? 0}</strong>
              </div>
            </div>
          </div>
          <div className="block-inspector card">
            <div className="block-inspector-header">
              <div className="header-with-tooltip">
                <h3>Request Model (data_model)</h3>
                <InfoTooltip label="Request model details" className="inline">
                  <p>Defines the on-wire structure the fuzzer sends to the target.</p>
                  <p>Fields appear in order, and behaviors like size_of or increment run before each send.</p>
                </InfoTooltip>
              </div>
              <p>Message structure sent to the target. Dependencies show field relationships and response-driven updates.</p>
            </div>
            {state.details.data_model.blocks?.length ? (
              renderBlockInspectorTable(state.details.data_model.blocks, state.details.response_handlers, false)
            ) : (
              <p className="hint">No blocks defined for this plugin.</p>
            )}
          </div>

          {state.details.response_model && (
            <div className="block-inspector card">
              <div className="block-inspector-header">
                <div className="header-with-tooltip">
                  <h3>Response Model (response_model)</h3>
                  <InfoTooltip label="Response model details" className="inline">
                    <p>Expected format of the target response for parsing and response-aware mutations.</p>
                    <p>Use it to drive handlers that copy values into request fields.</p>
                  </InfoTooltip>
                </div>
                <p>Expected structure of responses from the target. Used for parsing and response-driven mutations.</p>
              </div>
              {state.details.response_model.blocks?.length ? (
                renderBlockInspectorTable(state.details.response_model.blocks, undefined, true)
              ) : (
                <p className="hint">No response model blocks defined.</p>
              )}
            </div>
          )}

          {state.details.response_handlers && state.details.response_handlers.length > 0 && (
            <div className="block-inspector card">
              <div className="block-inspector-header">
                <div className="header-with-tooltip">
                  <h3>Response Handlers</h3>
                  <InfoTooltip label="Response handler details" className="inline">
                    <p>Handlers map parsed response fields to request fields.</p>
                    <p>They run after a response is parsed, before the next request is built.</p>
                  </InfoTooltip>
                </div>
                <p>Declarative rules for updating request fields based on response values.</p>
              </div>
              <div className="response-handlers-list">
                {state.details.response_handlers.map((handler) => (
                  <div key={handler.name} className="response-handler-card">
                    <h4>{handler.name}</h4>
                    <div className="handler-details">
                      <div className="handler-section">
                        <span className="section-label">Match Conditions:</span>
                        <pre className="handler-code">{JSON.stringify(handler.match, null, 2)}</pre>
                      </div>
                      <div className="handler-section">
                        <span className="section-label">Set Fields:</span>
                        <div className="set-fields-list">
                          {Object.entries(handler.set_fields).map(([field, value]) => (
                            <div key={field} className="field-mapping">
                              <span className="target-field">{field}</span>
                              <span className="mapping-arrow">&lt;-</span>
                              <span className="source-value">
                                {typeof value === 'object' && value !== null && 'copy_from_response' in value
                                  ? `response.${(value as Record<string, unknown>).copy_from_response}`
                                  : JSON.stringify(value)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
          <StateMachineCard info={buildStateMachineInfo(state.details.state_model)} />
          <div className="validation-section">
            <div className="validation-header">
              <div>
                <p className="eyebrow">Quality Gate</p>
                <div className="header-with-tooltip">
                  <h3>Plugin Validation</h3>
                  <InfoTooltip label="Plugin validation details" className="inline">
                    <p>Validate Plugin loads the module and runs static checks.</p>
                    <ul>
                      <li>Verify data_model structure and block types.</li>
                      <li>Parse seeds and ensure they match the model.</li>
                      <li>Check state transitions and unreachable states.</li>
                      <li>Validate size_of references and mutability.</li>
                    </ul>
                  </InfoTooltip>
                </div>
                <p>Validate Plugin loads the module and runs structure, seed, and state checks before fuzzing.</p>
              </div>
              <button
                type="button"
                className="validate-button"
                onClick={validatePlugin}
                disabled={state.validationLoading}
              >
                {state.validationLoading ? 'Validating...' : 'Validate Plugin'}
              </button>
            </div>
            <div className="validation-details">
              <div className="validation-detail-item">
                <span>Model integrity</span>
                <p>Checks required fields, block types, and size/endianness constraints.</p>
              </div>
              <div className="validation-detail-item">
                <span>Seed parsing</span>
                <p>Parses seeds against the data_model to catch shape mismatches early.</p>
              </div>
              <div className="validation-detail-item">
                <span>State logic</span>
                <p>Validates transitions, references, and unreachable states in the state_model.</p>
              </div>
              <div className="validation-detail-item">
                <span>Dependencies</span>
                <p>Verifies size_of targets, response copies, and mutability coverage.</p>
              </div>
            </div>
            {state.validationLoading && <div className="validation-loading">Analyzing plugin...</div>}
            {!state.validationLoading && state.validationError && <p className="error">{state.validationError}</p>}
            {!state.validationLoading && !state.validationError && state.validationResult && (
              <ValidationPanel
                issues={state.validationResult.issues}
                valid={state.validationResult.valid}
                summary={buildValidationSummary(state.validationResult)}
                pluginName={state.validationResult.plugin_name}
              />
            )}
            {!state.validationLoading && !state.validationError && !state.validationResult && (
              <p className="hint">Run validation to surface errors and best-practice warnings.</p>
            )}
          </div>
        </div>
      )}

      <div className="preview-controls">
        <div>
          <p className="eyebrow">Test Case Explorer</p>
          <h3>Generate Sample Frames</h3>
        </div>
        <div className="control-grid">
          <label>
            <span className="control-label">
              Mode
              <InfoTooltip label="Preview mode details" className="inline">
                <p>Seeds show baseline payloads from data_model.seeds.</p>
                <p>Mutations apply structure-aware or byte-level mutators to a seed.</p>
              </InfoTooltip>
            </span>
            <select value={previewMode} onChange={(e) => setPreviewMode(e.target.value as 'seeds' | 'mutations')}>
              <option value="seeds">Seeds</option>
              <option value="mutations">Mutations</option>
            </select>
          </label>
          <label>
            <span className="control-label">
              Count ({previewCount})
              <InfoTooltip label="Preview count details" className="inline">
                <p>Controls how many frames are generated per request (1-5).</p>
              </InfoTooltip>
            </span>
            <input
              type="range"
              min={1}
              max={5}
              value={previewCount}
              onChange={(e) => setPreviewCount(Number(e.target.value))}
            />
          </label>
          <label>
            <span className="control-label">
              Focus Field
              <InfoTooltip label="Focus field details" className="inline">
                <p>Optional field name to bias the preview toward changes in one block.</p>
              </InfoTooltip>
            </span>
            <input
              placeholder="Optional field name"
              value={focusField}
              onChange={(e) => setFocusField(e.target.value)}
            />
          </label>
          <button type="button" onClick={generatePreview} disabled={state.previewLoading}>
            {state.previewLoading ? 'Generating...' : 'Generate Previews'}
          </button>
        </div>
      </div>
      {state.previewError && <p className="error">{state.previewError}</p>}
      <div className="preview-grid">
        {state.previews.map((preview) => (
          <div key={`${preview.id}-${preview.mode}`} className="preview-card">
            <div className="preview-meta">
              <span>{preview.mode === 'baseline' ? 'Seed' : preview.mode}</span>
              {preview.mutation_type && <span className="mutator-pill">{preview.mutation_type}</span>}
              <span>{preview.total_bytes} bytes</span>
            </div>
            <pre className="hex-preview">{preview.hex_dump}</pre>
            <table>
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Hex</th>
                </tr>
              </thead>
              <tbody>
                {preview.fields.map((field) => (
                  <tr key={field.name}>
                    <td>
                      <strong>{field.name}</strong>
                      {field.mutated && <span className="mutated-tag">mutated</span>}
                      {field.computed && <span className="computed-tag">auto</span>}
                    </td>
                    <td>{String(field.value)}</td>
                    <td>{field.hex}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
        {!state.previewLoading && state.previews.length === 0 && (
          <p className="hint">No previews yet. Generate samples to visualize payloads.</p>
        )}
      </div>
    </div>
  );
}

export default PluginDebuggerPage;

function renderPluginDescription(description?: string) {
  if (!description || !description.trim()) {
    return <p className="plugin-description empty">No description provided.</p>;
  }

  const blocks = description.replace(/\s+$/g, '').split(/\n\s*\n/);
  const listPattern = /^([-*]|\d+[\.)]|•)\s+/;
  const preformattedPattern = /(^\s{2,}\S)|(\+--\+)|(\|.*\|)/;

  return (
    <div className="plugin-description">
      {blocks.map((block, index) => {
        const rawLines = block.split('\n');
        const trimmedLines = rawLines.map((line) => line.trim()).filter(Boolean);
        if (!trimmedLines.length) return null;
        const isList = trimmedLines.every((line) => listPattern.test(line));
        const isPreformatted = rawLines.some((line) => preformattedPattern.test(line));

        if (isPreformatted) {
          const rawBlock = block.replace(/\s+$/g, '');
          return (
            <pre key={`desc-${index}`} className="plugin-description-pre">
              {rawBlock}
            </pre>
          );
        }
        if (isList) {
          return (
            <ul key={`desc-${index}`}>
              {trimmedLines.map((line, lineIndex) => (
                <li key={`desc-${index}-${lineIndex}`}>{line.replace(listPattern, '')}</li>
              ))}
            </ul>
          );
        }
        return (
          <p key={`desc-${index}`} className="plugin-description-paragraph">
            {trimmedLines.join('\n')}
          </p>
        );
      })}
    </div>
  );
}

function buildStateMachineInfo(stateModel?: PluginStateModel) {
  if (!stateModel || !stateModel.states?.length) {
    return { has_state_model: false };
  }
  return {
    has_state_model: true,
    states: stateModel.states,
    initial_state: stateModel.initial_state,
    transitions: stateModel.transitions?.map((transition) => ({
      from_state: transition.from,
      to_state: transition.to,
      message_type: transition.message_type || transition.trigger,
      expected_response: transition.expected_response,
    })),
  };
}

function renderDefault(defaultValue: unknown) {
  if (typeof defaultValue === 'string') {
    return defaultValue;
  }
  if (typeof defaultValue === 'number' || typeof defaultValue === 'boolean') {
    return String(defaultValue);
  }
  if (Array.isArray(defaultValue)) {
    return `[${defaultValue.join(', ')}]`;
  }
  if (defaultValue && typeof defaultValue === 'object') {
    return JSON.stringify(defaultValue);
  }
  return '-';
}

function describeMutability(block: DataBlock) {
  return block.mutable === false ? 'Fixed' : 'Mutable';
}

function describeBehavior(block: DataBlock) {
  const behaviors: string[] = [];

  if (block.behavior && typeof block.behavior === 'object') {
    const behavior = block.behavior as Record<string, unknown>;
    const op = typeof behavior.operation === 'string' ? behavior.operation : undefined;
    if (op === 'increment') {
      const step = behavior.step ?? 1;
      behaviors.push(`Increment (step ${step})`);
    } else if (op === 'add_constant') {
      const value = Number(behavior.value ?? behavior.constant ?? 0);
      behaviors.push(`Add constant 0x${value.toString(16).toUpperCase()}`);
    } else if (op) {
      behaviors.push(op);
    }
  }

  if (block.is_size_field && block.size_of) {
    const targets = Array.isArray(block.size_of) ? block.size_of.join(', ') : block.size_of;
    behaviors.push(`Size of: ${targets}`);
  }

  return behaviors.length ? behaviors.join(' |') : '-';
}

function describeNotes(block: DataBlock) {
  const notes: string[] = [];
  if (block.is_size_field && block.size_of) {
    notes.push(`Declares size for ${block.size_of}`);
  } else if (block.size_of) {
    notes.push(`Sized by ${block.size_of}`);
  }
  if (block.references) {
    const refs = Array.isArray(block.references) ? block.references.join(', ') : block.references;
    notes.push(`References ${refs}`);
  }
  if (block.default !== undefined) {
    notes.push(`Default ${renderDefault(block.default)}`);
  }
  if (!notes.length && block.description) {
    notes.push(block.description);
  }
  return notes.length ? notes.join(' |') : '-';
}

function renderBlockTooltip(block: DataBlock): ReactNode {
  return (
    <div>
      <p>{block.description || 'No author notes provided.'}</p>
      <ul>
        <li>Type: {block.type}</li>
        <li>Mutable: {describeMutability(block)}</li>
        {block.size !== undefined && <li>Width: {block.size} byte(s)</li>}
        {block.default !== undefined && <li>Default: {renderDefault(block.default)}</li>}
        {block.endian && <li>Endian: {block.endian}</li>}
        {block.bit_order && <li>Bit order: {block.bit_order}</li>}
        {block.behavior && <li>Behavior: {describeBehavior(block)}</li>}
        {block.size_of && <li>Length relationship: {block.size_of}</li>}
        {block.references && (
          <li>
            References: {Array.isArray(block.references) ? block.references.join(', ') : block.references}
          </li>
        )}
      </ul>
    </div>
  );
}

function findResponseDependencies(
  fieldName: string,
  responseHandlers?: ResponseHandler[]
): string[] {
  if (!responseHandlers) return [];

  const dependencies: string[] = [];
  responseHandlers.forEach((handler) => {
    const setFields = handler.set_fields || {};
    Object.entries(setFields).forEach(([targetField, value]) => {
      if (targetField === fieldName && typeof value === 'object') {
        const valueObj = value as Record<string, unknown>;
        if (valueObj.copy_from_response && typeof valueObj.copy_from_response === 'string') {
          dependencies.push(`&lt;- ${valueObj.copy_from_response} (${handler.name})`);
        }
      }
    });
  });

  return dependencies;
}

function renderBlockInspectorTable(
  blocks: DataBlock[],
  responseHandlers?: ResponseHandler[],
  isResponseModel: boolean = false
) {
  return (
    <table className="blocks-table">
      <thead>
        <tr>
          <th title="Field name from the model, in on-wire order.">Field</th>
          <th title="Type used for parsing and serialization.">Type</th>
          <th title="Whether this field is mutated during fuzzing.">Mutability</th>
          <th title="Pre-send behavior (increment, add_constant, size_of).">Behavior</th>
          <th title="Other fields this entry depends on or references.">Dependencies</th>
        </tr>
      </thead>
      <tbody>
        {blocks.map((block) => {
          const responseDeps = !isResponseModel ? findResponseDependencies(block.name, responseHandlers) : [];
          const sizeTarget = block.is_size_field && block.size_of
            ? (Array.isArray(block.size_of) ? block.size_of : [block.size_of])
            : [];
          const references = block.references
            ? (Array.isArray(block.references) ? block.references : [block.references])
            : [];

          const allDeps = [...sizeTarget, ...references, ...responseDeps];

          return (
            <tr key={block.name}>
              <td>
                <div className="block-name">
                  <strong>{block.name}</strong>
                  <button
                    type="button"
                    className="tooltip-trigger"
                    aria-label={`Details for ${block.name}`}
                  >
                    i
                    <span className="tooltip-content">{renderBlockTooltip(block)}</span>
                  </button>
                </div>
              </td>
              <td>{block.type}</td>
              <td>
                <span
                  className={`mutability-pill ${block.mutable === false ? 'fixed' : 'mutable'}`}
                >
                  {describeMutability(block)}
                </span>
              </td>
              <td>{describeBehavior(block)}</td>
              <td>
                {allDeps.length > 0 ? (
                  <div className="dependencies-list">
                    {sizeTarget.map((target) => (
                      <span key={target} className="dep-tag size-dep" title="Size field for">
                        &gt; {target}
                      </span>
                    ))}
                    {references.map((ref) => (
                      <span key={ref} className="dep-tag ref-dep" title="References">
                        Ref: {ref}
                      </span>
                    ))}
                    {responseDeps.map((dep, i) => (
                      <span key={i} className="dep-tag response-dep" title="Copied from response">
                        {dep}
                      </span>
                    ))}
                  </div>
                ) : (
                  '-'
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
