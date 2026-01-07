# Plugin Authoring Guide

**Last Updated: 2025-11-25**

This guide provides a complete, in-depth walkthrough of how to create a custom protocol plugin for the fuzzer. A well-crafted plugin is the key to an effective fuzzing campaign, as it teaches the fuzzer the "language" of your target protocol.

This guide is for developers who want to extend the fuzzer to support new protocols. It assumes a basic understanding of Python and the protocol you intend to test.

## 1. The Anatomy of a Plugin

A protocol plugin is a single Python file in the `core/plugins/` directory that defines up to three key components:

1.  **`data_model` (Required)**: A dictionary that describes the structure of your protocol's messages.
2.  **`state_model` (Optional)**: A dictionary that defines the protocol's state machine, for stateful protocols.
3.  **`validate_response` (Optional)**: A function that acts as a "specification oracle," checking for logical bugs in the target's responses.

## 2. The `data_model`: Describing Protocol Structure

The `data_model` is the single most important part of a plugin. It tells the `ProtocolParser` how to deconstruct a raw byte stream into a meaningful set of fields, and how to reconstruct it after mutation. This enables structure-aware fuzzing.

A `data_model` consists of two main parts:
-   **`blocks`**: A list of dictionaries, where each dictionary describes a single field in the protocol message in the order they appear.
-   **`seeds`**: A list of raw byte strings representing valid or interesting messages. These are used as the initial inputs for the mutation engine.

### Defining Blocks

Each block in the `blocks` list defines the properties of a single field.

| Property | Type | Description |
| --- | --- | --- |
| `name` | `str` | **Required.** A unique name for the field. |
| `type` | `str` | **Required.** The data type (e.g., `uint8`, `uint16`, `uint32`, `bytes`, `string`). |
| `size` | `int` | The fixed size of the field in bytes. Required for fixed-size `bytes` fields. |
| `max_size` | `int` | The maximum size of a variable-length `bytes` or `string` field. |
| `endian` | `str` | For multi-byte integers, the byte order: `big` or `little`. |
| `default` | any | A default value for the field. |
| `mutable` | `bool` | If `False`, this field will be protected from mutation. Defaults to `True`. **Crucial for static fields like magic headers.** |
| `values` | `dict` | An optional mapping of integer values to string descriptions (e.g., for command enums). |

**Example Field Definitions:**

```python
"blocks": [
    # A static 4-byte magic header that should not be mutated.
    {
        "name": "magic",
        "type": "bytes",
        "size": 4,
        "default": b"BANK",
        "mutable": False
    },
    # A 1-byte command field.
    {
        "name": "command",
        "type": "uint8",
        "default": 1,
        "values": { 1: "CONNECT", 2: "AUTH", 3: "TRANSFER" }
    },
    # A variable-length payload.
    {
        "name": "payload",
        "type": "bytes",
        "max_size": 1024
    }
]
```

### The `ProtocolParser`: Bringing the `data_model` to Life

The `ProtocolParser` (`core/engine/protocol_parser.py`) is the component that uses the `data_model` to perform its magic. It provides two key methods:

-   **`parse(data: bytes)`**: Takes a raw byte string and converts it into an ordered dictionary of fields and their values.
-   **`serialize(fields: dict)`**: Takes a dictionary of fields and converts it back into a raw byte string.

This bidirectional conversion is the core of structure-aware fuzzing. The `StructureAwareMutator` uses `parse` to deconstruct a seed, mutates a value in the resulting dictionary, and then uses `serialize` to reconstruct a valid message.

### Advanced Logic: Calculated Fields and Behaviors

The fuzzer can automatically manage fields that have deterministic or calculated values, such as length prefixes, checksums, and sequence numbers. This ensures that even after mutation, the test cases remain valid enough to be accepted by the target.

#### Automatic Size Calculation

To define a length prefix, use the `is_size_field` and `size_of` properties. When `serialize()` is called, it automatically calculates the actual length of the target field(s) and updates the length field's value.

```python
{
    "name": "length",
    "type": "uint32",
    "endian": "big",
    "is_size_field": True,     # Marks this as a length field.
    "size_of": "payload"       # Tells the fuzzer this field's value is the length of the "payload" field.
}
```
If a mutation changes the `payload`, the `length` field will be automatically updated before serialization. `size_of` can also be a list of fields (e.g., `["field1", "field2"]`) to calculate a length over multiple blocks.

#### Declarative Behaviors

Behaviors are rules attached to a field that apply a deterministic transformation just before the test case is sent. This is perfect for fields that must change in a predictable way, like an incrementing sequence number.

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
This `behavior` block tells the fuzzer to treat this field as a counter. It will start at 0, increment by 1 for each message sent in a session, and wrap around after reaching 65535.

### Providing High-Quality Seeds

The `seeds` list should contain several examples of valid, real-world messages for your protocol.

-   **Provide Variety**: Include seeds for different message types and states.
-   **Use Real Data**: Capture traffic from a real client to create your seeds.

```python
"seeds": [
    b"BANK\x01\x00\x00\x00\x00\x00",
    b"BANK\x02\x00\x00\x00\x10admin:password123",
]
```

## 3. Defining Stateful Interactions (`state_model`)

If your protocol is stateful, you must define a `state_model` to guide the fuzzer.

```python
state_model = {
    "initial_state": "DISCONNECTED",
    "states": [ "DISCONNECTED", "CONNECTED", "AUTHENTICATED" ],
    "transitions": [
        {
            "from": "DISCONNECTED",
            "to": "CONNECTED",
            "message_type": "CONNECT"
        },
        {
            "from": "CONNECTED",
            "to": "AUTHENTICATED",
            "message_type": "AUTH"
        }
    ]
}
```
The `message_type` in each transition should correspond to a logical message type in your `data_model`. This allows the fuzzer to send messages in the correct order.

### Handling Server-Sent Data (`response_model` and `response_handlers`)

For protocols that require the client to use data from the server (e.g., a session token), you can model this declaratively. This is managed by the `ResponsePlanner` (`core/engine/response_planner.py`).

1.  **`response_model`**: Add a `response_model` to your `data_model` to describe the structure of the server's replies.
2.  **`response_handlers`**: Add a `response_handlers` list. Each handler is a rule that tells the fuzzer how to react to a specific response.

**Example**:
```python
data_model = {
    # ...
    "blocks": [
        {"name": "command", "type": "uint8"},
        {"name": "token", "type": "uint32", "default": 0}
    ],
    "response_model": {
        "blocks": [
            {"name": "status", "type": "uint8"},
            {"name": "session_token", "type": "uint32"}
        ]
    },
    "response_handlers": [
        {
            "name": "handle_login_success",
            "match": {"status": 0x00},
            "set_fields": {
                "command": 3,
                "token": {"copy_from_response": "session_token"}
            }
        }
    ]
}
```
This allows the fuzzer to handle complex, interactive protocols without any custom code.

## 4. Creating a Specification Oracle (`validate_response`)

You can add a `validate_response` function to your plugin to check for logical bugs in the target's responses that wouldn't cause a crash.

```python
def validate_response(response: bytes) -> bool:
    """
    Checks if the server's response violates protocol rules.
    Returns True if valid, False if a logical bug is found.
    Can also raise a ValueError for severe violations.
    """
    import struct
    if len(response) < 8: return False
    declared_length = struct.unpack(">I", response[4:8])[0]
    actual_length = len(response) - 8
    if declared_length != actual_length:
        return False # Logical bug: malformed response
    return True
```

## 5. Testing and Debugging Your Plugin

An incorrect plugin is worse than no plugin at all.

1.  **Verify Plugin Loads**: Restart the fuzzer and check the `/api/plugins/your_protocol` endpoint.
2.  **Test Your Seeds**: Use a simple Python script to send each of your seeds to the target and verify the responses.
3.  **Use the Preview Endpoint**: Use the `/api/plugins/your_protocol/preview` endpoint to see how the fuzzer parses a message.
4.  **Run a Short Fuzzing Session**: Run a session for a few minutes and check for immediate errors.

By following this structured approach, you can create a robust and effective protocol plugin that enables the fuzzer to find deep and interesting bugs in your target application.
