# 4. Stateful Fuzzing

Many network protocols are stateful. This means the validity of a message, or the server's interpretation of it, depends on the sequence of messages that preceded it. For example, a server might require a client to `LOGIN` before accepting a `SEND_DATA` message. Fuzzing such protocols with random, stateless messages is highly inefficient, as most test cases will be immediately rejected for being out of order, preventing the fuzzer from ever reaching the deeper, more interesting application logic.

The fuzzing engine addresses this challenge with its **stateful fuzzing mode**. This mode uses a state machine defined in a protocol plugin to guide the fuzzing process, ensuring that messages are sent in a logically valid sequence.

## The `state_model`

To enable stateful fuzzing, a protocol plugin must define a `state_model` dictionary alongside its `data_model`. This model provides a formal description of the protocol's state machine.

The `state_model` from the example `kevin.py` plugin provides a clear illustration:

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
        # ... other transitions
    ]
}
```

The `state_model` has three key parts:
-   **`initial_state`**: The state the fuzzer starts in for every new session.
-   **`states`**: A list of all possible states the protocol can be in.
-   **`transitions`**: A list of valid transitions between states. Each transition is a dictionary that defines:
    -   `from`: The source state for the transition.
    -   `to`: The destination state after the transition is successfully completed.
    -   `message_type`: The type of message that triggers this transition. This is a logical name that corresponds to a specific message structure, often identified by a unique value in a "command" field within the `data_model`.

## The `StatefulFuzzingSession`

When a fuzzing session is started for a protocol that has a `state_model`, the `FuzzOrchestrator` instantiates a `StatefulFuzzingSession` (`core/engine/stateful_fuzzer.py`). This specialized session object is responsible for managing the fuzzing process according to the rules of the state machine.

Its key responsibilities are:

1.  **Tracking the Current State**: It maintains a `current_state` variable for the connection to the target, which is initialized to the `initial_state` from the plugin.
2.  **Selecting Valid Messages**: In each iteration of the fuzzing loop, instead of picking a random seed from the entire corpus, it first determines which transitions are valid from the `current_state`. It then selects a message type that can trigger one of those valid transitions.
3.  **Updating State**: After a test case is executed, it updates its internal state based on the message that was sent and the target's response. If the response indicates success, it moves to the `to` state of the transition. If it fails, it may remain in the `from` state or reset the connection entirely.

## State-Aware Test Case Generation

The `StatefulFuzzingSession` fundamentally alters the test case generation process to be state-aware.

1.  **Identify Valid Transitions**: It first consults the `state_model` to find all transitions that are possible from the `current_state`.
2.  **Select a Transition**: It selects one of these valid transitions to attempt. By default, it has a high probability of choosing the "happy path" (the first valid transition listed in the plugin for a given state), as this is often necessary to make progress through the protocol. However, it will occasionally choose other valid transitions to explore alternative paths and edge cases.
3.  **Determine Message Type**: It gets the `message_type` (e.g., "CONNECT") from the selected transition.
4.  **Find a Matching Seed**: It then searches the entire corpus for a seed message that corresponds to this `message_type`. It does this by parsing the seeds and checking the value of their "command" field (or whichever field is used to distinguish message types).
5.  **Mutate and Execute**: Once a matching seed is found, it is passed to the `MutationEngine` to be mutated, just like in a stateless session. The resulting test case is then sent to the target.

This entire process is encapsulated in methods like `get_message_type_for_state` and `find_seed_for_message_type`:

```python
# core/engine/stateful_fuzzer.py - Simplified Logic

class StatefulFuzzingSession:
    def get_next_test_case(self, seeds: List[bytes]) -> Optional[bytes]:
        # 1. Determine the message type to send based on the current state
        message_type = self.get_message_type_for_state()
        if not message_type:
            return None

        # 2. Find a seed that matches this message type
        base_seed = self.find_seed_for_message_type(message_type, seeds)
        if not base_seed:
            # No seed found for this state, maybe log a warning
            return None

        # 3. Mutate the selected seed
        mutated_data = self.mutation_engine.generate_test_case(base_seed)
        return mutated_data

    def get_message_type_for_state(self) -> Optional[str]:
        """
        Intelligently select the next message type to send based on the current state.
        """
        valid_transitions = [t for t in self.state_model['transitions'] if t['from'] == self.current_state]
        if not valid_transitions:
            return None

        # Logic to select a transition (e.g., prioritize happy path)
        selected_transition = self.select_transition(valid_transitions)
        return selected_transition.get("message_type")
```

By strictly following the protocol's state machine, the fuzzer can generate valid sequences of messages. This allows it to bypass the target's initial state validation checks and test the deeper, more complex application logic that would be completely unreachable with a purely random, stateless fuzzing approach. This dramatically increases the efficiency and effectiveness of the fuzzer on stateful targets.