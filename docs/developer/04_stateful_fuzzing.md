# Fuzzing Engine: Developer Documentation

## 4. Stateful Fuzzing

Many network protocols are stateful, meaning the validity of a message depends on the sequence of messages that preceded it. For example, a server might reject a `DATA` message if a `CONNECT` message has not been sent first. Fuzzing such protocols with random, stateless messages is inefficient, as most test cases will be immediately rejected.

The fuzzing engine addresses this with its **stateful fuzzing** mode, which uses a state machine defined in a protocol plugin to guide the fuzzing process.

### The State Model

Alongside the `data_model`, a plugin can define a `state_model`. This model describes the protocol's state machine.

The `state_model` from `core/plugins/kevin.py` provides a clear example:

```python
# core/plugins/kevin.py

state_model = {
    "initial_state": "INIT",

    "states": ["INIT", "CONNECTED", "AUTHENTICATED", "CLOSED"],

    "transitions": [
        {
            "from": "INIT",
            "to": "CONNECTED",
            "trigger": "connect",
            "message_type": "CONNECT",
        },
        {
            "from": "CONNECTED",
            "to": "AUTHENTICATED",
            "trigger": "authenticate",
            "message_type": "AUTH",
        },
        # ...
    ]
}
```

-   **`initial_state`**: The state the fuzzer starts in.
-   **`states`**: A list of all possible states.
-   **`transitions`**: A list of valid transitions between states. Each transition defines:
    -   `from`: The source state.
    -   `to`: The destination state.
    -   `message_type`: The type of message that triggers this transition. This corresponds to a known value in the `data_model`'s `command` field.

### The StatefulFuzzingSession

When a fuzzing session starts for a protocol with a `state_model`, the `FuzzOrchestrator` creates a `StatefulFuzzingSession` (`core/engine/stateful_fuzzer.py`). This object is responsible for managing the fuzzing process according to the state machine.

Its key responsibilities are:

1.  **Tracking the Current State**: It maintains a `current_state` variable, which is initialized to the `initial_state`.
2.  **Selecting Valid Messages**: In each iteration of the fuzzing loop, instead of picking a random seed, it determines the valid message types for the current state.
3.  **Updating State**: After a test case is executed, it updates its internal state based on the message that was sent and the target's response.

### State-Aware Test Case Generation

The `StatefulFuzzingSession` alters the test case generation process significantly.

1.  **Get Valid Transitions**: It first identifies all valid transitions from its `current_state`.
2.  **Select a Transition**: It selects one of these transitions. By default, it has a high probability of choosing the "happy path" (the first transition listed in the plugin), but it will occasionally choose other valid transitions to explore alternative paths.
3.  **Get Message Type**: It gets the `message_type` (e.g., "CONNECT") from the selected transition.
4.  **Find a Matching Seed**: It then searches the corpus for a seed message that corresponds to this `message_type`. It does this by parsing the seeds and checking the value of their `command` field.
5.  **Mutate and Execute**: This selected seed is then passed to the `MutationEngine`, just like in a stateless session.

This process is encapsulated in the `get_message_type_for_state` and `find_seed_for_message_type` methods:

```python
# core/engine/stateful_fuzzer.py

class StatefulFuzzingSession:
    # ...
    def get_message_type_for_state(self) -> Optional[str]:
        """
        Get the message type to send for current state.
        """
        transition = self.select_transition()
        if not transition:
            return None
        return transition.get("message_type")

    def find_seed_for_message_type(self, message_type: str, seeds: List[bytes]) -> Optional[bytes]:
        """
        Find a seed message that matches the desired message type.
        """
        command_value = self.message_type_to_command.get(message_type)
        # ...
        for seed in seeds:
            try:
                fields = self.parser.parse(seed)
                if fields.get("command") == command_value:
                    return seed
            except Exception:
                continue
        return None
```

By following the protocol's state machine, the fuzzer can generate sequences of valid messages, allowing it to bypass initial validation and test deeper logic within the target application that would be unreachable with a purely random approach.
