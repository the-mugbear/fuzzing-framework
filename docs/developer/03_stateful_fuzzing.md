# 3. Stateful Fuzzing

**Last Updated: 2025-11-25**

Many network protocols are stateful. This means the validity of a message, or the server's interpretation of it, depends on the sequence of messages that preceded it. Fuzzing such protocols with random, stateless messages is highly inefficient, as most test cases will be immediately rejected.

The fuzzing engine addresses this challenge with its **stateful fuzzing mode**. This mode uses a state machine defined in a protocol plugin to guide the fuzzing process, ensuring that messages are sent in a logically valid sequence.

## The `state_model`

To enable stateful fuzzing, a protocol plugin must define a `state_model` dictionary. This model provides a formal description of the protocol's state machine.

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
-   **`transitions`**: A list of valid transitions between states. The `message_type` corresponds to a logical message type in the `data_model`, often identified by a unique value in a "command" field.

## The `StatefulFuzzingSession`

When a plugin with a `state_model` is used, the `FuzzOrchestrator` instantiates a `StatefulFuzzingSession` (`core/engine/stateful_fuzzer.py`). This object is responsible for:

1.  **Tracking the Current State**: It maintains the protocol's current state, which is initialized to the `initial_state` from the plugin.
2.  **Selecting Valid Messages**: In each iteration, it determines which messages are valid to send from the current state.
3.  **Path Selection**: It uses a `progression_weight` (typically 80%) to decide whether to follow the "happy path" (the first valid transition listed in the plugin) or explore an alternative but still valid transition. This ensures a balance between making progress through the protocol and exploring edge cases.
4.  **Updating State**: After a test case is executed, it updates its internal state based on the message that was sent and the target's response.
5.  **Tracking Coverage**: It tracks which states have been visited and which transitions have been successfully taken, providing valuable metrics on the effectiveness of the fuzzing campaign.

## State-Aware Test Case Generation

The `StatefulFuzzingSession` alters the test case generation process to be state-aware:

1.  **Identify Valid Transitions**: It consults the `state_model` to find all transitions that are possible from the `current_state`.
2.  **Select a Transition**: It uses the `progression_weight` to select a transition.
3.  **Determine Message Type**: It gets the `message_type` (e.g., "CONNECT") from the selected transition.
4.  **Find a Matching Seed**: It then searches the corpus for a seed that corresponds to this `message_type`. It does this by parsing the seeds and checking the value of their "command" field (or whichever field is used to distinguish message types, based on the plugin's `data_model`).
5.  **Mutate and Execute**: The matching seed is mutated and sent to the target.

### State Reset Mechanism

To ensure broad exploration of the state machine, the `StatefulFuzzingSession` employs a state reset mechanism. It periodically resets its internal state back to the `initial_state`. This prevents the fuzzer from getting "stuck" in a deep part of the state machine and encourages it to explore different paths through the protocol from the beginning.

By strictly following the protocol's state machine, tracking coverage, and periodically resetting its state, the fuzzer can generate valid sequences of messages that test deep and complex application logic that would be unreachable with a purely stateless fuzzing approach.
