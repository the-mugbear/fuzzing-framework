# 3. Protocol Plugins and Parsing

The fuzzer's "intelligence"—its ability to perform structure-aware mutations and interact with complex, stateful protocols—is entirely dependent on its knowledge of the protocol being tested. This knowledge is provided by **Protocol Plugins**. This document covers how to create these plugins, how the fuzzer parses data based on them, and how to use their advanced features to handle complex protocol logic.

## The Role of Plugins

A protocol plugin is a self-contained Python file located in the `core/plugins/` directory. It acts as a "driver" for the fuzzing engine, providing the essential metadata needed to understand a specific protocol. The engine's plugin-driven architecture makes it highly extensible; to fuzz a new protocol, a developer simply needs to create a new plugin file that accurately describes it.

A plugin can define three key components:
1.  **`data_model`**: A dictionary that defines the structure of the protocol's messages. This is **required**.
2.  **`state_model`**: A dictionary that describes the protocol's state machine. This is **optional** but highly recommended for stateful protocols.
3.  **`validate_response`**: A function that can check for logical bugs in the target's responses. This is **optional**.

## The `data_model`: Describing Protocol Structure

The `data_model` is the single most important part of a plugin. It tells the `ProtocolParser` how to deconstruct a raw byte stream into a meaningful set of fields, and how to reconstruct it after mutation.

A `data_model` consists of two main parts:
-   **`blocks`**: A list of dictionaries, where each dictionary describes a single field in the protocol message in the order they appear.
-   **`seeds`**: A list of raw byte strings representing valid or interesting messages. These are used as the initial inputs for the mutation engine.

### Defining Blocks

Each block in the `blocks` list defines the properties of a single field. Let's examine a comprehensive example:

```python
"blocks": [
    {
        "name": "magic",
        "type": "bytes",
        "size": 4,
        "default": b"KEVN",
        "mutable": False  # Protects this field from mutation
    },
    {
        "name": "length",
        "type": "uint32",
        "endian": "big",
        "is_size_field": True,
        "size_of": "payload" # Links this field to the size of the 'payload' field
    },
    {
        "name": "payload",
        "type": "bytes",
        "max_size": 1024,
        "default": b""
    },
    {
        "name": "sequence_num",
        "type": "uint16",
        "behavior": {
            "operation": "increment",
            "initial": 0,
            "step": 1
        }
    }
]
```

Key properties for a block include:
-   **`name`**: A unique string identifier for the field.
-   **`type`**: The data type (e.g., `uint8`, `uint16`, `uint32`, `uint64`, `bytes`, `string`).
-   **`size`** or **`max_size`**: The fixed size or maximum size of the field in bytes.
-   **`endian`**: For multi-byte integer types, specifies the byte order (`big` or `little`).
-   **`default`**: A default value for the field.
-   **`mutable`**: A boolean indicating whether the mutation engine is allowed to change this field. This is crucial for protecting static values like magic headers or command identifiers.
-   **`is_size_field`**: A boolean that marks this field as a length prefix for another field.
-   **`size_of`**: A string or list of strings specifying which other field(s) this length field describes.
-   **`behavior`**: A dictionary defining a deterministic behavior for this field (see below).
-   **`response_model`**: An optional schema to describe how to parse server replies.
-   **`response_handlers`**: An optional list of rules for building follow-up messages based on server responses.

## The `ProtocolParser`: Bringing the `data_model` to Life

The `ProtocolParser` (`core/engine/protocol_parser.py`) is the component that uses the `data_model` to perform its magic. It provides two key methods:

-   **`parse(data: bytes)`**: Takes a raw byte string and converts it into an ordered dictionary of fields and their values.
-   **`serialize(fields: dict)`**: Takes a dictionary of fields and converts it back into a raw byte string.

This bidirectional conversion is the core of structure-aware fuzzing. The `StructureAwareMutator` uses `parse` to deconstruct a seed, mutates a value in the resulting dictionary, and then uses `serialize` to reconstruct a valid message.

## Advanced Logic: Calculated Fields and Behaviors

The fuzzer can automatically manage fields that have deterministic or calculated values, such as length prefixes, checksums, and sequence numbers. This ensures that even after mutation, the test cases remain valid enough to be accepted by the target.

### Automatic Size Calculation

Many protocols use length-prefixing. The fuzzer handles this automatically using the `is_size_field` and `size_of` properties.

When `serialize()` is called, it first runs `_auto_fix_fields`. This method scans the `data_model` for any block marked with `"is_size_field": True`. It then calculates the actual serialized length of the target field(s) (specified in `size_of`) and updates the length field's value accordingly.

**Example:**
If a mutation changes a `payload` to be 20 bytes long, the `_auto_fix_fields` method will automatically set the value of the corresponding `length` field to `20` before serialization. The `size_of` property can also be a list of fields (e.g., `["field1", "field2"]`) to calculate a length over multiple consecutive blocks.

### Checksum Calculation (Future)

The documentation previously mentioned a `TODO` for checksums. While not yet implemented as a declarative feature like `size_of`, the current architecture is designed to support it. The plan is to add a `checksum_of` property, which would work similarly to `size_of`, allowing a plugin to specify the fields to be included in a checksum calculation and the algorithm to use (e.g., CRC32, Fletcher-16).

### Declarative Behaviors

Behaviors are rules attached to a field that apply a deterministic transformation just before the test case is sent. This is perfect for fields that must change in a predictable way, like an incrementing sequence number.

**Example:**
```python
{
    "name": "sequence",
    "type": "uint16",
    "behavior": {
        "operation": "increment",
        "initial": 0,
        "step": 1,
        "wrap": 65536
    }
}
```
This `behavior` block tells the fuzzer to treat this field as a counter. It will start at 0, increment by 1 for each message sent in a session, and wrap around to 0 after reaching 65535.

## Declarative Response Handling

Many protocols require a client to react to server responses (e.g., using a server-provided session token in subsequent requests). The fuzzer can handle these scenarios declaratively using `response_model` and `response_handlers`, eliminating the need for custom logic.

This is managed by the `ResponsePlanner` (`core/engine/response_planner.py`).

### How It Works

1.  **Define Response Structure (`response_model`)**: A plugin can optionally define a `response_model` within its `data_model`. This model has the same `blocks` structure as the main `data_model` and tells the engine how to parse messages *received from* the server.

2.  **Define Handlers (`response_handlers`)**: The plugin also defines a list of `response_handlers`. Each handler is a rule with a `match` condition and a `set_fields` action.

3.  **Process Response**: When the fuzzer receives a response from the target, the `ResponsePlanner` parses it using the `response_model`. It then finds the first handler where the `match` condition is met by the parsed response fields. Finally, it constructs a new message to send, starting with the default fields of a request and overwriting them based on the `set_fields` action.

The `set_fields` action is powerful because it can copy values directly from the server's response into the next message.

### Example: Handling a Session Token

Imagine a protocol where the client sends a `LOGIN` message and the server replies with a `LOGIN_SUCCESS` message containing a session token.

```python
# In the plugin file

# Describes the server's response message
response_model = {
    "blocks": [
        {"name": "status", "type": "uint8"},
        {"name": "session_token", "type": "uint32"}
    ]
}

# Describes how to react to the response
response_handlers = [
    {
        "name": "handle_login_success",
        "match": {"status": 0x00},  # If status is 0 (success)
        "set_fields": {
            "command": "GET_DATA",  # Send a GET_DATA command next
            "token": {"copy_from_response": "session_token"} # Copy the token
        }
    }
]

# Main data_model for client-sent messages
data_model = {
    "blocks": [
        {"name": "command", "type": "string"},
        {"name": "token", "type": "uint32", "default": 0},
        # ... other fields
    ],
    "response_model": response_model,
    "response_handlers": response_handlers
}
```

With this configuration, when the server replies with a success status, the `ResponsePlanner` will automatically generate a `GET_DATA` message with the `token` field correctly populated from the server's response. This allows the fuzzer to proceed with complex, stateful interactions that depend on server-provided data, all without writing any imperative logic.