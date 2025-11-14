# Protocol Development UI Features - Implementation Plan

**Status**: Proposal
**Created**: 2025-11-13
**Target**: React + TypeScript + Vite SPA

## Executive Summary

This plan outlines the phased implementation of 5 advanced UI features to streamline protocol plugin development. These features transform the fuzzer from a code-first tool into an interactive development environment.

**Estimated Total Effort**: 6-8 weeks (1 engineer)
**Priority Order**: Features 2, 3, 1, 4, 5 (based on value/complexity ratio)

---

## Existing Infrastructure Assessment

### ✅ Already Available

- **Backend**:
  - `ProtocolParser` (`core/engine/protocol_parser.py`) - Parse/serialize binary protocols
  - `PluginManager` - Dynamic plugin loading
  - Plugin validation in `core/engine/plugin_validator.py`
  - FastAPI with structured routing (`core/api/routes/`)

- **Frontend**:
  - React 18 + TypeScript + Vite setup
  - React Router v6 with Layout system
  - Existing `PluginDebuggerPage` component
  - API utility functions and error handling patterns
  - CSS modules for styling

### 🔨 Needs Implementation

- Visual graph/diagram libraries
- Form builders for complex nested data
- Hex editor components
- Real-time WebSocket support (optional, for live updates)
- Additional API endpoints for parse/validate/mutate operations

---

## Feature Breakdown & Implementation Plan

## Phase 1: Foundation (Week 1-2)

### 1.1 Shared Dependencies

**New npm packages**:
```bash
npm install --save \
  react-flow       # State machine diagrams
  monaco-editor    # Code editor with syntax highlighting
  hex-viewer-react # Hex display component
  react-hook-form  # Complex form management
  zod              # Runtime validation
```

**New API Models** (`core/models.py`):
```python
class ParseRequest(BaseModel):
    protocol: str
    hex_data: str  # Hex string or base64

class ParseResponse(BaseModel):
    fields: Dict[str, Any]
    raw_bytes: str  # Hex representation
    warnings: List[str] = []

class ValidationRequest(BaseModel):
    plugin_code: str  # Python source code

class ValidationResult(BaseModel):
    valid: bool
    errors: List[Dict[str, str]]  # {line, message, severity}
    warnings: List[Dict[str, str]]
    plugin_name: Optional[str] = None
```

### 1.2 New API Endpoints

**File**: `core/api/routes/protocol_tools.py`

```python
@router.post("/api/tools/parse", response_model=ParseResponse)
async def parse_packet(request: ParseRequest):
    """Parse hex/base64 packet using protocol data_model"""
    # Uses ProtocolParser.parse()

@router.post("/api/tools/validate-plugin", response_model=ValidationResult)
async def validate_plugin_code(request: ValidationRequest):
    """Static analysis of plugin code"""
    # Uses existing plugin_validator.py

@router.post("/api/tools/generate-plugin")
async def generate_plugin_code(data_model: dict, state_model: dict):
    """Generate Python code from visual models"""
    # Template-based code generation

@router.post("/api/tools/mutate-field")
async def mutate_single_field(protocol: str, fields: dict, mutator: str):
    """Apply specific mutation to parsed fields"""
    # Uses StructureAwareMutator selectively
```

---

## Phase 2: Feature #2 - Live Packet Parser (Week 2-3) ⭐ HIGH PRIORITY

**Value**: Immediate debugging utility for protocol developers
**Complexity**: Low-Medium
**Dependencies**: Phase 1 complete

### UI Components

**New page**: `src/pages/PacketParserPage.tsx`

**Layout**:
```
┌─────────────────────────────────────────────────────────┐
│ Protocol Selector: [dropdown]                           │
├─────────────────────────────────────────────────────────┤
│ Input Panel                                             │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Format: ⚪ Hex  ⚪ Base64                            │ │
│ │ ┌─────────────────────────────────────────────────┐ │ │
│ │ │ Paste packet here:                              │ │ │
│ │ │ 53 54 43 50 00 00 00 05 01 48 45 4c 4c 4f      │ │ │
│ │ └─────────────────────────────────────────────────┘ │ │
│ │ [Parse Button]                                      │ │
│ └─────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│ Output Panel (split view)                               │
│ ┌─────────────────────┬─────────────────────────────┐   │
│ │ Hex View            │ Parsed Fields               │   │
│ │ 00: 53 54 43 50 ◄──┼─ magic: "STCP"              │   │
│ │ 04: 00 00 00 05 ◄──┼─ length: 5                   │   │
│ │ 08: 01           ◄──┼─ cmd: HELLO (0x01)          │   │
│ │ 09: 48 45 4c 4c 4f ◄┼─ payload: "HELLO"           │   │
│ └─────────────────────┴─────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

**Key Features**:
- Bidirectional highlighting (hover field → highlight bytes, vice versa)
- Color-coded byte ranges per field
- Show offsets and byte counts
- Display field metadata (type, endianness, mutability)

**Components to build**:
```typescript
// src/components/HexViewer.tsx
interface HexViewerProps {
  data: Uint8Array;
  highlights: { start: number; end: number; color: string }[];
  onByteHover: (offset: number) => void;
}

// src/components/ParsedFieldsView.tsx
interface FieldInfo {
  name: string;
  value: any;
  type: string;
  offset: number;
  size: number;
  mutable: boolean;
}
```

**Backend Work**:
- Implement `/api/tools/parse` endpoint
- Extend `ProtocolParser.parse()` to return offset information
- Add byte-range metadata to parse results

---

## Phase 3: Feature #3 - Plugin Linter & Validator (Week 3-4) ⭐ HIGH PRIORITY

**Value**: Catches errors before fuzzing, reduces debugging time
**Complexity**: Medium
**Dependencies**: Phase 1 complete

### Enhancement to Existing Page

Extend `PluginDebuggerPage.tsx` with validation panel:

```
┌─────────────────────────────────────────────────────────┐
│ Plugin Debugger                                         │
├─────────────────────────────────────────────────────────┤
│ [Load Plugin] [Upload .py] [Validate]                   │
├─────────────────────────────────────────────────────────┤
│ Code Editor                                             │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ 1  data_model = {                                   │ │
│ │ 2      "blocks": [                                  │ │
│ │ 3          {"name": "magic", "type": "bytes", ... } │ │
│ │ ...                                                 │ │
│ └─────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│ Validation Results                                      │
│ ❌ Error (Line 15): size_of field "payload_len" points  │
│    to non-existent field "payloads"                     │
│ ⚠️  Warning (State Model): State "ERROR" has no         │
│    incoming transitions (unreachable)                   │
│ ✅ Info: Found 3 seeds, all parse successfully          │
└─────────────────────────────────────────────────────────┘
```

**Validation Checks** (backend `core/engine/plugin_validator.py`):

Enhance existing validator to check:
- ✅ Python syntax (via `ast.parse()`)
- ✅ Required attributes present (`data_model`, `state_model`)
- ✅ `size_of` references exist
- ✅ Enum values in blocks match state transitions
- ✅ Seeds parse successfully with data_model
- ⚠️ Unreachable states
- ⚠️ Dead-end states (no outgoing transitions)
- ⚠️ Unused message types defined but never referenced

**Components**:
```typescript
// src/components/MonacoEditor.tsx (wrapper around monaco-editor)
interface EditorProps {
  value: string;
  language: 'python' | 'json';
  onChange: (value: string) => void;
  markers?: { line: number; message: string; severity: 'error' | 'warning' }[];
}

// src/components/ValidationPanel.tsx
interface ValidationIssue {
  severity: 'error' | 'warning' | 'info';
  line?: number;
  message: string;
  category: 'syntax' | 'model' | 'seed' | 'state';
}
```

---

## Phase 4: Feature #1 - Interactive Protocol Modeler (Week 5-6)

**Value**: Lowers barrier to entry for non-Python users
**Complexity**: High (complex forms + code generation)
**Dependencies**: Phases 1-3 complete (can leverage parser/validator)

### New Page: `src/pages/ProtocolModelerPage.tsx`

**Tabbed Interface**:

**Tab 1: Data Model Builder**
```
┌─────────────────────────────────────────────────────────┐
│ Data Model                              [+ Add Field]   │
├─────────────────────────────────────────────────────────┤
│ Field 1: magic                              [🗑️]        │
│   Type: [bytes ▼]  Size: [4]  Default: [STCP]          │
│   ☑️ Fixed (non-mutable)                                │
├─────────────────────────────────────────────────────────┤
│ Field 2: length                             [🗑️]        │
│   Type: [uint32 ▼]  Endian: [big ▼]                    │
│   ☑️ Size field for: [payload ▼]                        │
├─────────────────────────────────────────────────────────┤
│ Field 3: payload                            [🗑️]        │
│   Type: [bytes ▼]  Max Size: [1024]                    │
│   Values: [+ Add Enum Value]                            │
└─────────────────────────────────────────────────────────┘
```

**Tab 2: State Machine Editor**
```
┌─────────────────────────────────────────────────────────┐
│ State Model                  [+ Add State] [+ Add Edge] │
├─────────────────────────────────────────────────────────┤
│  Visual Canvas (React Flow)                             │
│      ┌─────┐  CONNECT(0x01)  ┌───────────┐             │
│   ──▶│INIT │─────────────────▶│ CONNECTED │             │
│      └─────┘                  └───────────┘             │
│                                     │ DISCONNECT(0x02)  │
│                                     ▼                    │
│                                 ┌──────┐                │
│                                 │ TERM │                │
│                                 └──────┘                │
└─────────────────────────────────────────────────────────┘
```

**Tab 3: Code Preview**
```python
# Auto-generated from visual model
data_model = {
    "name": "MyProtocol",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4,
         "default": b"STCP", "mutable": False},
        # ...
    ]
}
state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "CONNECTED", "TERM"],
    "transitions": [
        {"from": "INIT", "to": "CONNECTED", "message_type": "CONNECT"},
        # ...
    ]
}
```
[Copy to Clipboard] [Download .py] [Load into Validator]

### Technical Approach

**Form Management**: Use `react-hook-form` + `zod` for validation

```typescript
const fieldSchema = z.object({
  name: z.string().min(1).regex(/^[a-z_][a-z0-9_]*$/),
  type: z.enum(['bytes', 'uint8', 'uint16', 'uint32', ...]),
  size: z.number().int().positive().optional(),
  mutable: z.boolean().default(true),
  size_of: z.string().optional(),
  // ...
});

type FieldConfig = z.infer<typeof fieldSchema>;
```

**State Machine**: Use `react-flow` (node-based graph editor)
- Nodes = states
- Edges = transitions (labeled with message_type)
- Drag-and-drop interface
- Auto-layout algorithms

**Code Generation**: Template-based with Jinja2 or simple string interpolation

```typescript
function generatePluginCode(
  dataModel: FieldConfig[],
  stateModel: StateConfig
): string {
  return `
__version__ = "1.0.0"

data_model = ${JSON.stringify(convertToBackendFormat(dataModel), null, 2)}

state_model = ${JSON.stringify(stateModel, null, 2)}
`.trimStart();
}
```

**Components to Build**:
- `FieldEditor.tsx` - Single field configuration form
- `FieldList.tsx` - Reorderable list with drag handles
- `StateMachineCanvas.tsx` - React Flow wrapper
- `TransitionEditor.tsx` - Modal for editing edge properties
- `CodeGenerator.tsx` - Preview + download

---

## Phase 5: Feature #4 - Interactive Mutation Workbench (Week 7)

**Value**: Test individual mutations before full fuzzing campaign
**Complexity**: Medium-High
**Dependencies**: Phases 2, 3 (needs parser + validation)

### New Page: `src/pages/MutationWorkbenchPage.tsx`

**Layout**:
```
┌─────────────────────────────────────────────────────────┐
│ Mutation Workbench                                      │
├─────────────────────────────────────────────────────────┤
│ Protocol: [simple_tcp ▼]  Seed: [seed_001 ▼]           │
├──────────────────────┬──────────────────────────────────┤
│ Parsed Fields        │ Actions                          │
│ magic: STCP [edit]   │ [🎲 Random Mutation]             │
│ length: 5            │ [⚡ Bit Flip]                     │
│ cmd: 0x01 [edit]     │ [📊 Havoc]                       │
│ payload: HELLO       │ [✂️ Splice with...]              │
│   [edit] ▼           │ [💾 Save as New Seed]            │
├──────────────────────┴──────────────────────────────────┤
│ Serialized Output (live updates)                        │
│ 53 54 43 50 00 00 00 05 01 48 45 4C 4C 4F              │
│ [📋 Copy Hex] [Send to Target]                          │
├─────────────────────────────────────────────────────────┤
│ Target Response                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Status: ✅ Response received (24ms)                  │ │
│ │ 53 54 43 50 00 00 00 02 02 4f 4b                    │ │
│ │ Parsed: {magic: "STCP", cmd: 0x02, payload: "OK"}   │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

**Features**:
- **Manual Editing**: Click field → inline editor → auto-reserialize
- **One-Click Mutations**: Apply specific mutators (BitFlip, Arithmetic, etc.)
- **Live Send**: Dispatch to target and show response
- **Save Interesting Cases**: Add manually crafted packets to corpus

### Backend Endpoints

```python
@router.post("/api/tools/mutate-field")
async def mutate_field(
    protocol: str,
    fields: Dict[str, Any],
    mutator_type: str,  # "bitflip", "arithmetic", "havoc", etc.
    field_name: Optional[str] = None  # Target specific field
) -> Dict[str, Any]:
    """Apply mutation and return new fields + serialized bytes"""

@router.post("/api/tools/send-test-case")
async def send_single_test_case(
    target_host: str,
    target_port: int,
    data: bytes,
    timeout_ms: int = 1000
) -> Dict[str, Any]:
    """Send single packet, return response and metadata"""
```

**Components**:
- `EditableFieldTable.tsx` - Inline editing with type-aware inputs
- `MutatorSelector.tsx` - Buttons for each mutator type
- `ResponseViewer.tsx` - Hex + parsed response display

---

## Phase 6: Feature #5 - State Machine Walker (Week 8)

**Value**: Interactive testing of stateful protocols
**Complexity**: High (requires session state management)
**Dependencies**: All previous phases

### New Page: `src/pages/StateMachineWalkerPage.tsx`

**Layout**:
```
┌─────────────────────────────────────────────────────────┐
│ State Machine Walker                                    │
├─────────────────────────────────────────────────────────┤
│ Target: localhost:9999         [▶ Start Session]        │
├─────────────────────────────────────────────────────────┤
│ Current State: INIT                                     │
│                                                         │
│      ┌──────┐                                           │
│   ──▶│ INIT │ (you are here)                            │
│      └──────┘                                           │
│         │                                               │
│         ├──[Send CONNECT]──────▶ CONNECTED              │
│         └──[Send TERMINATE]────▶ TERM                   │
├─────────────────────────────────────────────────────────┤
│ Available Actions:                                      │
│ [Execute: CONNECT (0x01)]                               │
│ [Execute: TERMINATE (0xFF)]                             │
├─────────────────────────────────────────────────────────┤
│ Event Log                                               │
│ 14:23:01 - Session started                              │
│ 14:23:05 - Sent: CONNECT (53 54 43 50...)              │
│ 14:23:05 - Received: CONNECT_OK (53 54 43 50...)       │
│ 14:23:05 - State: INIT → CONNECTED ✅                   │
└─────────────────────────────────────────────────────────┘
```

**State Management**:
- Track current FSM state in frontend
- Maintain TCP connection (or reconnect per message)
- Validate transitions match state_model expectations

**Backend**:
```python
class WalkerSession:
    """Persistent session for state machine walking"""
    session_id: str
    protocol: str
    current_state: str
    target_conn: Optional[socket.socket]
    history: List[StateTransition]

@router.post("/api/walker/sessions")
async def create_walker_session(protocol: str, target: str, port: int)

@router.post("/api/walker/sessions/{id}/execute")
async def execute_transition(session_id: str, message_type: str)
```

**Components**:
- `StateMachineDiagram.tsx` - React Flow with current state highlighted
- `TransitionButtons.tsx` - Dynamic buttons based on current state
- `EventLog.tsx` - Scrollable log with timestamps

---

## Technical Considerations

### State Management Strategy

For complex features (Modeler, Workbench), consider:

**Option A: Local Component State** (Current approach)
- ✅ Simple, no dependencies
- ❌ Doesn't scale to cross-component sharing

**Option B: Context API**
```typescript
// src/contexts/ProtocolEditorContext.tsx
const ProtocolEditorContext = createContext<{
  dataModel: FieldConfig[];
  stateModel: StateConfig;
  updateField: (id: string, updates: Partial<FieldConfig>) => void;
}>()
```
- ✅ Good for feature-specific state
- ✅ No extra libraries

**Option C: Zustand** (Recommended for Phase 4+)
```bash
npm install zustand
```
```typescript
// src/stores/protocolStore.ts
export const useProtocolStore = create<ProtocolState>((set) => ({
  fields: [],
  addField: (field) => set((state) => ({
    fields: [...state.fields, field]
  })),
}));
```
- ✅ Minimal boilerplate
- ✅ DevTools integration
- ✅ Scales to complex apps

### Styling Approach

Current: CSS modules (`.css` files imported per component)

**Recommendation**: Continue with CSS modules + CSS variables

```css
/* src/styles/tokens.css */
:root {
  --color-success: #10b981;
  --color-error: #ef4444;
  --color-warning: #f59e0b;
  --spacing-unit: 8px;
}
```

For complex layouts (Modeler, Walker): Consider CSS Grid + Flexbox

### Testing Strategy

**Unit Tests**: Component logic (React Testing Library)
```typescript
// src/components/__tests__/FieldEditor.test.tsx
test('validates field name format', () => {
  render(<FieldEditor />);
  // ...
});
```

**Integration Tests**: API interactions (MSW for mocking)
```typescript
// src/pages/__tests__/PacketParserPage.test.tsx
test('parses hex input and displays fields', async () => {
  server.use(
    rest.post('/api/tools/parse', (req, res, ctx) => {
      return res(ctx.json({ fields: { magic: 'STCP' }}))
    })
  );
  // ...
});
```

**E2E Tests**: Full workflows (Playwright)
- Create protocol → Validate → Parse packet → Run mutation

---

## Deployment & Rollout

### Incremental Rollout

1. **Phase 2 (Parser)**: Ship as standalone tool, gather feedback
2. **Phase 3 (Validator)**: Enhance existing debugger page
3. **Phases 1, 4, 5**: Bundle as "Protocol Development Suite" release

### Feature Flags

Use environment variables to gate features:
```typescript
// vite.config.ts
define: {
  __FEATURE_MODELER__: JSON.stringify(process.env.VITE_ENABLE_MODELER === 'true'),
}
```

### Documentation

Each feature needs:
- User guide with screenshots (`docs/guides/`)
- Developer API reference
- Video walkthrough (record with OBS, host on GitHub)

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| **Complexity creep in Modeler** | Start with MVP (basic field types only), iterate |
| **React Flow learning curve** | Prototype in sandbox first, check docs |
| **Monaco Editor bundle size** | Lazy load with `React.lazy()` |
| **Backend validation performance** | Cache plugin AST, use `ast.parse()` only on changes |
| **State Machine Walker session management** | Use short-lived sessions (5min timeout), auto-cleanup |

---

## Success Metrics

**Adoption**:
- 50%+ of new plugins created using Modeler (vs. hand-coded)
- Parser used in 80%+ of plugin development sessions

**Quality**:
- 30% reduction in plugin validation errors during fuzzing
- 50% reduction in "protocol doesn't parse" issues

**Efficiency**:
- Average time to create new plugin: 30min → 10min
- Time to debug parsing issues: 20min → 5min

---

## Appendix: API Endpoint Summary

### New Endpoints Required

| Endpoint | Method | Purpose | Phase |
|----------|--------|---------|-------|
| `/api/tools/parse` | POST | Parse hex/base64 packet | 2 |
| `/api/tools/validate-plugin` | POST | Validate plugin code | 3 |
| `/api/tools/generate-plugin` | POST | Generate Python from models | 4 |
| `/api/tools/mutate-field` | POST | Apply specific mutation | 5 |
| `/api/tools/send-test-case` | POST | Send single packet to target | 5 |
| `/api/walker/sessions` | POST | Create walker session | 6 |
| `/api/walker/sessions/{id}/execute` | POST | Execute state transition | 6 |
| `/api/walker/sessions/{id}` | GET | Get current walker state | 6 |
| `/api/walker/sessions/{id}` | DELETE | Close walker session | 6 |

### Enhanced Models

Extend `core/models.py`:
```python
class ParseRequest(BaseModel): ...
class ParseResponse(BaseModel): ...
class ValidationRequest(BaseModel): ...
class ValidationResult(BaseModel): ...
class MutationRequest(BaseModel): ...
class WalkerSession(BaseModel): ...
class StateTransition(BaseModel): ...
```

---

## Next Steps

1. **Review & Approval**: Discuss priorities and timeline with stakeholders
2. **Prototype Phase 2**: Build Parser page in 2-3 days to validate approach
3. **Backend Prep**: Implement `/api/tools/*` endpoints in parallel
4. **UI Library Spike**: Test React Flow + Monaco integration (1 day)
5. **Kickoff Phase 1**: Install dependencies, set up base components

---

## Questions for Discussion

1. **Priority**: Do you agree with the order (2→3→1→4→5)?
2. **Scope**: Should we implement all features, or start with 2-3 MVPs?
3. **Timeline**: Is 6-8 weeks acceptable, or should we trim features?
4. **UI Libraries**: Any objections to React Flow / Monaco?
5. **Authentication**: Do any features need auth/permissions?

---

**Document Owner**: Claude Code
**Last Updated**: 2025-11-13
**Status**: Awaiting Approval
