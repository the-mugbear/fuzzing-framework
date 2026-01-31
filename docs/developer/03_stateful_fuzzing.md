# 3. Stateful Fuzzing and Orchestration

**Last Updated: 2026-01-30**

This document covers the fuzzer's two primary mechanisms for handling stateful protocols: the `state_model` for automated state exploration, and the `protocol_stack` for explicit, multi-stage orchestration. These features can be used independently or combined for testing highly complex, real-world protocols.

## Part 1: Simple Stateful Fuzzing with `state_model`

For protocols that can be represented as a simple state machine, you can provide a `state_model` in your plugin. This enables the fuzzer to automatically explore the protocol's state graph.

### The `state_model`
The `state_model` is a dictionary that provides a formal description of the protocol's state machine.

```python
state_model = {
    "initial_state": "INIT",
    "states": ["INIT", "CONNECTED", "AUTHENTICATED", "CLOSED"],
    "transitions": [
        { "from": "INIT", "to": "CONNECTED", "message_type": "CONNECT" },
        { "from": "CONNECTED", "to": "AUTHENTICATED", "message_type": "AUTH" },
    ]
}
```
-   **`initial_state`**: The state the fuzzer starts in.
-   **`states`**: A list of all possible states.
-   **`transitions`**: A list of valid transitions. The `message_type` corresponds to a message type that the fuzzer can select from its seed corpus.

### The `StatefulFuzzingSession`
When a plugin with a `state_model` is used, the `FuzzOrchestrator` instantiates a `StatefulFuzzingSession` (`core/engine/stateful_fuzzer.py`). This object is responsible for:

1.  **Tracking State**: Maintaining the current state of the protocol.
2.  **Selecting Valid Messages**: In each iteration, it consults the `state_model` to determine which `message_type`s are valid to send from the current state.
3.  **Guiding Exploration**: It uses fuzzing modes (`random`, `breadth_first`, `depth_first`, `targeted`) to decide which valid transition to take, balancing "happy path" progression with edge-case exploration.
4.  **Tracking Coverage**: It tracks which states have been visited and which transitions have been taken.

This mechanism is excellent for exploring a self-contained state graph where the fuzzer can discover paths automatically.

---

## Part 2: Advanced State Management with Orchestration

Simple state models are insufficient for protocols that require complex handshakes, dynamic data (like session tokens), or persistent connections with keep-alives. These scenarios are handled by **Orchestrated Sessions**.

Orchestration provides explicit, step-by-step control over the fuzzing lifecycle using a `protocol_stack`, a `connection` object, `exports`, `from_context`, and `heartbeat` configurations.

This allows you to, for example:
1.  **`bootstrap`**: Perform a multi-step authentication handshake.
2.  **`export`**: Extract a session token from the login response.
3.  **`fuzz_target`**: Inject that token into all subsequent fuzzing messages.
4.  **`heartbeat`**: Keep the authenticated session alive in the background.

For a complete guide on this powerful feature, see **[Orchestrated Sessions Guide](ORCHESTRATED_SESSIONS_GUIDE.md)** and **[ORCHESTRATED_SESSIONS_ARCHITECTURE.md](ORCHESTRATED_SESSIONS_ARCHITECTURE.md)**.

---

## Part 3: Combining Orchestration and Stateful Fuzzing

These two features are not mutually exclusive; they are designed to work together. **Any stage within a `protocol_stack` can have its own `state_model`.**

This creates a powerful, hierarchical approach to state management:
-   Use the **`protocol_stack`** to handle the high-level, linear sequence of events (connect, authenticate, fuzz, disconnect).
-   Use a **`state_model`** within the `fuzz_target` stage to handle the complex, non-linear application logic that is only accessible *after* the handshake is complete.

### How It Works

1.  The `FuzzOrchestrator` starts an orchestrated session.
2.  The `StageRunner` executes the `bootstrap` stage, performing the handshake and populating the `ProtocolContext` with a session token.
3.  The `StageRunner` moves to the `fuzz_target` stage. It inspects the plugin for this stage (`my_app_logic.py` in the example below).
4.  It discovers that this plugin has a `state_model`.
5.  It instantiates a **new `StatefulFuzzingSession`** specifically for this stage. This session will manage the state exploration of the application's logic (e.g., `READY` -> `READ_FILE` -> `UPDATE_RECORD`).
6.  The main fuzzing loop begins. For each test case, the `FuzzOrchestrator` first injects the `session_token` from the context, and then the `StatefulFuzzingSession` chooses a message type based on its *internal* state graph (`READ_FILE`, etc.) before mutation occurs.

### Example Combined Plugin

**`main_orchestrated_plugin.py`**:
```python
# Defines the high-level sequence
protocol_stack = {
    "name": "AuthenticatedAppFuzzer",
    "stages": [
        {"name": "bootstrap", "plugin": "my_auth_plugin"},
        {"name": "fuzz_target", "plugin": "my_app_logic_plugin"} # This plugin has a state_model
    ]
}
connection = {"persistent": True}
```

**`my_auth_plugin.py`**:
```python
# Handles the handshake, has no state_model
data_model = { ... } # Defines LOGIN message
exports = {"session_token": {"from_field": "response.token"}}
```

**`my_app_logic_plugin.py`**:
```python
# Defines the application logic and its state machine
data_model = {
    "blocks": [
        {"name": "session_token", "from_context": "session_token", "mutable": False},
        {"name": "app_command", "type": "uint8"},
        ...
    ]
}

state_model = {
    "initial_state": "READY",
    "states": ["READY", "READING", "WRITING"],
    "transitions": [
        {"from": "READY", "to": "READING", "message_type": "READ_FILE_CMD"},
        {"from": "READY", "to": "WRITING", "message_type": "WRITE_FILE_CMD"},
        {"from": "READING", "to": "READY", "message_type": "CLOSE_FILE_CMD"},
        # ... and so on
    ]
}
```

In this architecture, you get the best of both worlds: explicit control over the session lifecycle and automated exploration of the complex application logic within that session.