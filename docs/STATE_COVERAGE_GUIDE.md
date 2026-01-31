# State Coverage and Targeted Fuzzing Guide

**Last Updated: 2026-01-30**

This guide covers the state coverage tracking and targeted fuzzing features. These tools give you real-time visibility into state machine exploration and allow you to focus fuzzing efforts on specific parts of a stateful protocol.

## 1. Overview of State-Aware Fuzzing

For any protocol with a `state_model` defined in its plugin, the fuzzer can track its progress through the state machine. This enables several key capabilities:
-   **Coverage Tracking**: See which states and transitions have been visited.
-   **Targeted Fuzzing**: Focus fuzzing on a specific, high-value state.
-   **Exploration Strategies**: Choose how the fuzzer explores the state graph (e.g., broadly or deeply).

## 2. State Coverage in Orchestrated Sessions

When using an **Orchestrated Session** with a `protocol_stack`, state coverage is tracked on a **per-stage basis**.

-   The active `state_model` is the one defined in the plugin for the *currently executing stage*.
-   The `bootstrap` stage might have its own simple state model (e.g., `CONNECTING` -> `CONNECTED`).
-   The `fuzz_target` stage will have the primary state model that you are interested in for coverage analysis.
-   The UI and API will always show the state coverage for the currently active stage.

This means you can have a simple, linear state model for your handshake, and a complex, branching state model for your main application logic, and the fuzzer will track them independently as it moves through the stages.

## 3. Fuzzing Modes (Exploration Strategies)

You can control how the fuzzer explores the state machine by setting the `fuzzing_mode` when creating a session.

#### **`random`** (Default)
-   Standard fuzzing behavior with random state exploration.
-   Good for general-purpose, long-running sessions.

#### **`breadth_first`**
-   Prioritizes visiting the least-explored states.
-   **Use Case**: Excellent for initial discovery. Run for a short period to quickly map out all reachable states in the protocol.

#### **`depth_first`**
-   Attempts to follow long sequences of transitions before resetting.
-   **Use Case**: Ideal for finding complex bugs that only manifest after a specific, deep sequence of operations.

#### **`targeted`**
-   Focuses all fuzzing effort on a single, specified state. The fuzzer will automatically navigate to the `target_state` and then spend all its iterations fuzzing messages and transitions valid in that state.
-   **Use Case**: Deep-testing a specific, high-value feature of your target, such as an authentication process or a file transfer state.
-   **In an Orchestrated Session**, the `target_state` must be a state within the `state_model` of your `fuzz_target` plugin.

## 4. Monitoring Coverage

Coverage data is exposed through the API and the web UI.

### API Endpoint

The main session endpoint includes all coverage data:
`GET /api/sessions/{session_id}`

```json
{
  "current_state": "AUTHENTICATED",
  "state_coverage": {
    "INIT": 250,
    "CONNECTED": 180,
    "AUTHENTICATED": 95
  },
  "transition_coverage": {
    "INIT->CONNECTED": 180,
    "CONNECTED->AUTHENTICATED": 95
  },
  "field_mutation_counts": {
    "payload": 450,
    "command": 500
  }
}
```

### UI Dashboard
-   The **State Graph** visualization in the session detail view provides a live, graphical representation of the state machine, with nodes colored by visit count and the current state highlighted.
-   In an Orchestrated Session, this graph automatically updates to show the state machine of the current stage.

## 5. Usage Examples

### Example 1: Explore All States Quickly
Set `"fuzzing_mode": "breadth_first"`. This will give you a complete map of all reachable states.

### Example 2: Deep Test Authentication Logic
```json
{
  "fuzzing_mode": "targeted",
  "target_state": "AUTHENTICATED"
}
```
The fuzzer will navigate to the `AUTHENTICATED` state and spend all its time testing messages valid in that state.

## 6. Troubleshooting

-   **"State coverage is empty"**: Your plugin may not have a `state_model`, or the session may not have run long enough to transition. In an orchestrated session, check that the *current stage's plugin* has a `state_model`.
-   **"Targeted mode not reaching target state"**: The state might be unreachable. Use `breadth_first` mode first to confirm a path to the target state exists.
-   **"Field mutations not tracked"**: Field-level tracking requires structure-aware mutation modes (`structure_aware` or `hybrid`). It does not work with `byte_level_only`.

## 7. Best Practices

1.  **Start with `breadth_first`**: Always begin a campaign with a short `breadth_first` run to map the protocol's state space and identify interesting states to target later.
2.  **Target High-Value States**: Once you have a map, use `targeted` mode to focus on states with complex logic: authentication, file transfers, configuration changes, etc.
3.  **Validate `bootstrap` First**: In an orchestrated session, your `fuzz_target` coverage data is only meaningful if the `bootstrap` stage is succeeding reliably. Ensure your handshake is stable before diving deep into state coverage analysis of the main application.
4.  **Monitor Unexplored States**: Use the API or UI to see which states have a visit count of zero. These "unexplored" states may indicate dead code in the target, or a missing seed or transition in your protocol plugin.

---
## See Also
-   [Protocol Plugin Guide](PROTOCOL_PLUGIN_GUIDE.md)
-   [Orchestrated Sessions Guide](ORCHESTRATED_SESSIONS_GUIDE.md)
