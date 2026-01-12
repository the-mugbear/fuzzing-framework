# State Coverage and Targeted Fuzzing Guide

This guide covers the new state coverage tracking and targeted fuzzing features added to the fuzzing framework.

## Overview

The framework now provides real-time visibility into state machine coverage for stateful protocols and allows you to focus fuzzing efforts on specific states or use different exploration strategies.

## Key Features

### 1. Real-Time State Coverage Tracking

Every fuzzing session now tracks:
- **Current State**: Which protocol state the fuzzer is currently in
- **State Coverage**: How many times each state has been visited
- **Transition Coverage**: Which state transitions have been exercised
- **Field Mutation Counts**: Which protocol fields have been mutated

### 2. Fuzzing Modes

Choose different strategies for exploring protocol state machines:

#### **Random Mode** (Default)
```json
{"fuzzing_mode": "random"}
```
- Standard fuzzing behavior
- Random state exploration
- Good for general testing
- Reset interval: 100 iterations

#### **Breadth-First Mode**
```json
{"fuzzing_mode": "breadth_first"}
```
- Ensures all states are explored evenly
- Prioritizes least-visited states
- Good for achieving full coverage quickly
- Reset interval: 20 iterations (frequent resets)
- **Use case**: Initial protocol exploration, finding all reachable states

#### **Depth-First Mode**
```json
{"fuzzing_mode": "depth_first"}
```
- Follows deep execution paths
- Stays in sequences longer before resetting
- Good for finding complex bugs requiring specific state sequences
- Reset interval: 500 iterations (rare resets)
- **Use case**: Finding bugs in late-stage protocol logic

#### **Targeted Mode**
```json
{
  "fuzzing_mode": "targeted",
  "target_state": "AUTHENTICATED"
}
```
- Navigates to a specific state and focuses testing there
- Uses BFS pathfinding to reach target state
- Concentrates mutations on messages valid in target state
- Reset interval: 300 iterations
- **Use case**: Deep testing of specific protocol features (auth handlers, file transfer, etc.)

### 3. Coverage Visibility

Coverage data is exposed through multiple channels:

#### **API Endpoint**
```bash
GET /api/sessions/{session_id}
```

Response includes:
```json
{
  "current_state": "AUTHENTICATED",
  "state_coverage": {
    "INIT": 250,
    "CONNECTED": 180,
    "AUTHENTICATED": 95,
    "DATA_SENDING": 20,
    "ERROR": 5
  },
  "transition_coverage": {
    "INIT->CONNECTED": 180,
    "CONNECTED->AUTHENTICATED": 95,
    "AUTHENTICATED->DATA_SENDING": 20
  },
  "field_mutation_counts": {
    "payload": 450,
    "command": 500,
    "length": 320
  }
}
```

#### **UI Dashboard**
The dashboard sessions table now displays:
- Current state in Status column
- Coverage percentage: "Coverage: 5/8 states (63%)"
- Target state (when using targeted mode): "→ AUTHENTICATED"

#### **Computed Properties**
The `FuzzSession` model includes helper properties:
```python
session.coverage_percentage  # Returns 0.0-100.0
session.unexplored_states   # List of states never visited
```

## Usage Examples

### Example 1: Explore All States Quickly

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "my_protocol",
    "target_host": "target",
    "target_port": 9999,
    "fuzzing_mode": "breadth_first",
    "max_iterations": 1000
  }'
```

**Result**: All reachable states will be visited within the first few hundred iterations, giving you a complete state coverage map.

### Example 2: Deep Test Authentication Logic

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "my_protocol",
    "target_host": "target",
    "target_port": 9999,
    "fuzzing_mode": "targeted",
    "target_state": "AUTHENTICATED",
    "max_iterations": 10000
  }'
```

**Result**: The fuzzer will navigate to the AUTHENTICATED state and spend 10,000 iterations testing messages valid in that state, maximizing the chance of finding auth-related bugs.

### Example 3: Find Complex Multi-Step Bugs

```bash
curl -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "protocol": "my_protocol",
    "target_host": "target",
    "target_port": 9999,
    "fuzzing_mode": "depth_first",
    "max_iterations": 5000
  }'
```

**Result**: The fuzzer will follow long state sequences, good for finding bugs that only trigger after a specific sequence of operations.

### Example 4: Monitor Coverage in Real-Time

```bash
# Start a session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol":"branching_protocol","target_host":"target","target_port":9999,"fuzzing_mode":"breadth_first"}' \
  | jq -r '.id')

curl -X POST http://localhost:8000/api/sessions/$SESSION_ID/start

# Monitor coverage every 5 seconds
while true; do
  curl -s http://localhost:8000/api/sessions/$SESSION_ID | \
    jq '{current_state, total_tests, coverage: .state_coverage}'
  sleep 5
done
```

## UI Workflow

### Creating a Session with Targeting

1. Navigate to the Dashboard
2. Click "▶ Advanced Targeting Options" to expand
3. Select a fuzzing mode:
   - **Random**: Standard fuzzing
   - **Breadth-First**: Explore all states evenly
   - **Depth-First**: Follow deep paths
   - **Targeted**: Focus on specific state
4. If using Targeted mode, enter the state name (e.g., "AUTHENTICATED")
5. Click "Create Session"

### Monitoring Coverage

In the sessions table, you'll see:
- **Status column**: Current state (e.g., "State: AUTHENTICATED")
- **Stats column**: Coverage percentage (e.g., "Coverage: 5/8 states (63%)")
- **Target column**: Arrow showing target state if applicable (e.g., "→ AUTHENTICATED")

## Implementation Details

### Architecture

**State Tracking Flow**:
```
StatefulFuzzingSession (in-memory state machine)
    ↓ (real-time sync)
FuzzSession model (API-exposed data)
    ↓ (JSON response)
UI Dashboard (live display)
```

**Coverage Update Frequency**: Every test case execution (real-time)

**Reset Logic**:
- Breadth-first: Reset every 20 iterations to explore uniformly
- Depth-first: Reset every 500 iterations to follow deep paths
- Targeted: Reset every 300 iterations (or when terminal state reached)
- Random: Reset every 100 iterations

### Field Mutation Tracking

When using structure-aware mutations, the fuzzer tracks which fields are being mutated:

```python
# In mutation engine
field_mutated = structure_mutator.last_mutated_field
session.field_mutation_counts[field_mutated] += 1
```

This helps identify:
- Which fields are being tested
- Mutation distribution across protocol fields
- Untouched fields (potential blind spots)

## Troubleshooting

### "State coverage is empty"

**Cause**: Protocol doesn't have a state_model or the state machine hasn't transitioned yet

**Solution**:
1. Verify protocol has `state_model` with transitions
2. Let the session run for at least 50-100 iterations
3. Check session `error_message` for connection issues

### "Targeted mode not reaching target state"

**Cause**: Target state may be unreachable from initial state

**Solution**:
1. Check protocol's state model to verify path exists
2. Ensure seeds exist for required message types
3. Check logs for "no_path_to_target_state" warnings
4. Try breadth-first mode first to see which states are reachable

### "Field mutations not tracked"

**Cause**: Using byte-level mutations instead of structure-aware

**Solution**:
1. Set `mutation_mode` to "structure_aware" or "hybrid"
2. Ensure protocol has proper `data_model` with field definitions
3. Field tracking only works with structure-aware mutations

## Best Practices

### 1. Start with Breadth-First
Always begin with breadth-first mode to understand the protocol's state space:
```json
{"fuzzing_mode": "breadth_first", "max_iterations": 500}
```
This reveals all reachable states and helps you identify interesting targets.

### 2. Target High-Value States
Once you know the state space, target states with complex logic:
- Authentication handlers
- File upload/download states
- Error recovery states
- Administrative/privileged states

### 3. Combine with Max Iterations
Use `max_iterations` with targeted mode for focused campaigns:
```json
{
  "fuzzing_mode": "targeted",
  "target_state": "FILE_TRANSFER",
  "max_iterations": 50000
}
```

### 4. Monitor Unexplored States
Use the API to find states that are never reached:
```bash
curl -s http://localhost:8000/api/sessions/$SESSION_ID | \
  jq '.state_coverage | to_entries | map(select(.value == 0)) | .[].key'
```

These may indicate:
- Dead code in the target
- Missing seeds for certain message types
- Unreachable states due to validation logic

### 5. Field Coverage Analysis
Check which fields are being mutated:
```bash
curl -s http://localhost:8000/api/sessions/$SESSION_ID | \
  jq '.field_mutation_counts | to_entries | sort_by(.value) | reverse'
```

Low-count fields may need more focus or specialized mutation strategies.

## Future Enhancements (Recommended)

Based on this implementation, here are suggested improvements:

1. **State Coverage Visualization**: Graph-based UI showing state machine with coverage heatmap
2. **Path Recording**: Track and replay specific state sequences that led to crashes
3. **Coverage-Guided Fuzzing**: Automatically adjust fuzzing mode based on coverage stagnation
4. **Field-Level Targeting**: Allow specifying `mutable_fields: ["payload", "command"]` to focus on specific fields
5. **Transition Triggers**: Allow triggering specific transitions for precise state navigation
6. **Export Coverage Reports**: Generate coverage reports in standard formats (JSON, CSV, HTML)

## See Also

- `docs/PROTOCOL_PLUGIN_GUIDE.md` - Creating protocol plugins
- `blueprint.md` - Overall architecture
- API documentation at `/api/docs` (when server is running)
