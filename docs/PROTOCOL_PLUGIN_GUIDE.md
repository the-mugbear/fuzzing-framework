# Protocol Plugin Guide

**Last Updated: 2026-01-31**

This guide provides a complete reference for creating, testing, and debugging custom protocol plugins. Plugins are the core of the fuzzer, teaching it how to speak, understand, and intelligently mutate new protocols.

## Table of Contents

1.  [Plugin Concepts](#1-plugin-concepts)
2.  [Creating a Basic Plugin](#2-creating-a-basic-plugin)
    -   The `data_model`
    -   Field Types & Properties
    -   Defining Bit Fields
3.  [Stateful Fuzzing](#3-stateful-fuzzing)
    -   The `state_model`
4.  [Advanced: Orchestrated Sessions](#4-advanced-orchestrated-sessions)
    -   The `protocol_stack`
    -   The `connection` Object
    -   Passing Data with `ProtocolContext` (`exports` and `from_context`)
    -   Heartbeats (`heartbeat` object)
    -   Full Orchestrated Example
5.  [Validation and Logic Bugs](#5-validation-and-logic-bugs)
    -   The `validate_response` Oracle
6.  [Testing and Debugging](#6-testing-and-debugging)
    -   Testing Plugins Locally
    -   Troubleshooting Common Issues

---

## 1. Plugin Concepts

A protocol plugin is a single Python file that defines the structure and behavior of a protocol. The fuzzer discovers and loads these plugins at startup from the following directories:

### Plugin Directory Structure

```
core/plugins/
├── custom/          # Your custom plugins (highest priority)
├── examples/        # Learning-focused reference plugins
│   ├── minimal_tcp.py       # Bare minimum TCP protocol
│   ├── minimal_udp.py       # Bare minimum UDP protocol
│   ├── feature_reference.py # Comprehensive feature showcase
│   ├── orchestrated.py      # Multi-stage protocols
│   ├── stateful.py          # Complex state machines
│   └── field_types.py       # Field type reference
└── standard/        # Production-ready protocols
    ├── dns.py, mqtt.py, modbus_tcp.py, etc.
```

**Where to put your plugins:**
- **`custom/`** - Your custom protocol implementations. Start here.
- **`examples/`** - Reference implementations for learning. Copy and modify.
- **`standard/`** - Production protocols. Don't modify unless contributing.

The loader prioritizes `custom/` > `examples/` > `standard/`, so a plugin in `custom/` will override one with the same name in `examples/`.

A plugin can define several key components:
-   **`data_model`**: (Required) The structural definition of protocol messages.
-   **`state_model`**: (Optional) The state machine for stateful protocols.
-   **`protocol_stack`**: (Optional) For multi-protocol orchestration (e.g., handshake-then-fuzz).
-   **`connection`**: (Optional) Defines persistent connection behavior for stateful sessions.
-   **`heartbeat`**: (Optional) Configures keep-alive messages for long-running sessions.
-   **`validate_response`**: (Optional) A function to detect logical bugs in server responses.

---

## 2. Creating a Basic Plugin

Create a file like `core/plugins/custom/my_protocol.py`. At a minimum, it needs a `data_model`.

### The `data_model`

The `data_model` is a dictionary that describes the fields of a protocol message.

```python
"""
A minimal protocol plugin for a simple request-response protocol.
- Transport: TCP
- Features: Basic structure definition and seeds.
"""
__version__ = "1.0.0"

data_model = {
    "name": "MySimpleProtocol",
    "description": "A protocol with a header, length, and payload.",
    "blocks": [
        {
            "name": "magic",
            "type": "bytes",
            "size": 4,
            "default": b"SIMP",
            "mutable": False, # Keep the magic bytes constant
        },
        {
            "name": "payload_length",
            "type": "uint16",
            "endian": "big",
            "is_size_field": True, # Link this field to the size of another
            "size_of": "payload",
        },
        {
            "name": "payload",
            "type": "bytes",
            "max_size": 2048,
        }
    ],
    "seeds": [
        # A few valid messages to start fuzzing from
        b"SIMP\x00\x08some_cmd",
        b"SIMP\x00\x0c_another_cmd",
    ]
}
```

### Field Types & Properties

-   **`name`**: A unique name for the field.
-   **`type`**: `bytes`, `string`, `uint8`, `uint16`, `uint32`, `uint64`, `int8`, `int16`, `int32`, `int64`, `bits`.
-   **`size`**: (For fixed-size types) The size in bytes.
-   **`max_size`**: (For variable-size types) The maximum expected size. A variable-size field must either be the *last* field in a block or have its size defined by another field.
-   **`default`**: A default value for the field.
-   **`mutable`**: (Default: `True`) If `False`, the fuzzer will not mutate this field. Essential for magic headers, checksums you calculate yourself, etc.
-   **`endian`**: (Default: `big`) `big` or `little` for multi-byte integer types.
-   **`is_size_field`**: (Default: `False`) If `True`, this field's value will be automatically calculated to be the length of the field specified in `size_of`.
-   **`size_of`**: The name of the field whose size is determined by the `is_size_field`.
-   **`size_unit`**: (Default: `bytes`) `bytes`, `bits`, `words` (4 bytes), `dwords` (2 bytes) for `is_size_field`.

### Defining Bit Fields

For protocols with bit-level fields (e.g., TCP/IP headers), use the `bits` type.

```python
# A single byte containing two 4-bit nibbles
{
    "name": "version",
    "type": "bits",
    "size": 4, # Size in bits
    "default": 0x4
},
{
    "name": "ihl",
    "type": "bits",
    "size": 4,
    "default": 0x5
}

# A 13-bit field that crosses a byte boundary
{"name": "fragment_offset", "type": "bits", "size": 13, "default": 0x0}
```

-   Bit fields are packed in MSB-first order by default (`bit_order: "msb"`).
-   For bit fields larger than 8 bits, you can specify `endian: "little"` if needed.
-   The fuzzer automatically handles bit-level mutations.

---

## 3. Stateful Fuzzing

For protocols where the server's response depends on previous requests (e.g., auth -> ready), you can define a `state_model`.

```python
state_model = {
    "initial_state": "DISCONNECTED",
    "states": ["DISCONNECTED", "CONNECTED", "AUTHENTICATED"],
    "transitions": [
        {
            "from": "DISCONNECTED",
            "to": "CONNECTED",
            "trigger": "connect",
            "message_type": "CONNECT_MSG", # Corresponds to a message name/type
            "expected_response": "CONNECT_OK"
        },
        {
            "from": "CONNECTED",
            "to": "AUTHENTICATED",
            "trigger": "authenticate",
            "message_type": "AUTH_MSG",
            "expected_response": "AUTH_OK"
        }
    ]
}
```
The fuzzer can use this model to explore the state machine, trying valid and invalid transitions. See the **[State Coverage Guide](STATE_COVERAGE_GUIDE.md)** for more.

---

## 4. Advanced: Orchestrated Sessions

For many modern protocols, fuzzing requires more than a single connection or state model. You might need to perform a handshake, get a token, and then use that token in subsequent messages, all while keeping the connection alive. This is an **Orchestrated Session**.

### The `protocol_stack`

This is the entry point for orchestration. It defines a sequence of stages to be executed.

```python
protocol_stack = {
    "name": "HandshakeAndFuzzProtocol",
    "stages": [
        {
            "name": "bootstrap",
            "plugin": "my_handshake_protocol" # A plugin defining the handshake
        },
        {
            "name": "fuzz_target",
            "plugin": "my_core_fuzzing_protocol" # The plugin for the main target
        }
    ]
}
```

### The `connection` Object

Orchestrated sessions typically require a persistent connection. The `connection` object tells the fuzzer to keep the connection open for the duration of the session.

```python
connection = {
    "transport": "tcp", # or "udp"
    "persistent": True
}
```

### Passing Data with `ProtocolContext` (`exports` and `from_context`)

Stages need to share data (e.g., session tokens). This is done via the `ProtocolContext`.

**1. Exporting data from a `bootstrap` stage:**
In your handshake plugin, define `exports` to extract data from the server's response.

```python
# In the handshake plugin (e.g., my_handshake_protocol.py)
data_model = { ... }
state_model = { ... }

# After a successful handshake, export the session_id from the response
exports = {
    "session_id": {
        "from_field": "response.token", # Extract from the parsed 'token' field of the response
        "type": "uint32"
    }
}
```

**2. Importing data in the `fuzz_target` stage:**
In your main fuzzing plugin, use `from_context` to inject the value.

```python
# In the main fuzzing plugin (e.g., my_core_fuzzing_protocol.py)
data_model = {
    "blocks": [
        {
            "name": "session_id",
            "type": "uint32",
            "from_context": "session_id" # Inject the value from the context
        },
        # ... other fields to fuzz
    ],
    ...
}
```
The fuzzer will now automatically place the `session_id` obtained during the handshake into every test case before sending it.

### Heartbeats (`heartbeat` object)

For long sessions, firewalls or servers might close idle connections. A `heartbeat` sends periodic keep-alive messages.

```python
heartbeat = {
    "name": "KeepAlive",
    "interval": 5.0, # Send every 5 seconds
    "jitter": 0.5,   # With +/- 0.5s of randomness
    "message": {
        # Define the heartbeat message structure
        "blocks": [
            {"name": "command", "type": "uint8", "default": 0xFF}, # PING
            {
                "name": "session_id",
                "type": "uint32",
                "from_context": "session_id" # Heartbeats can also use context!
            }
        ]
    },
    "expect_response": True, # Does the server send a PONG?
    "on_failure": {
        "action": "reconnect", # If heartbeat fails, try to reconnect
        "threshold": 3         # after 3 consecutive failures.
    }
}
```
The `reconnect` action is powerful: it tells the fuzzer to re-run the `bootstrap` stage to get a new valid session, making the fuzzer self-healing.

### Full Orchestrated Example

See `core/plugins/examples/orchestrated.py` for a working example that ties all these concepts together. For a deeper architectural understanding, read `docs/developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md`.

### Example Plugins Reference

| Plugin | Location | Purpose |
| ------ | -------- | ------- |
| `minimal_tcp` | `examples/minimal_tcp.py` | Bare minimum TCP protocol - start here |
| `minimal_udp` | `examples/minimal_udp.py` | Bare minimum UDP protocol |
| `feature_reference` | `examples/feature_reference.py` | Comprehensive showcase of all features |
| `orchestrated` | `examples/orchestrated.py` | Multi-stage protocol with authentication |
| `stateful` | `examples/stateful.py` | Complex state machine with branching |
| `field_types` | `examples/field_types.py` | Copy-paste field type reference |

---

## 5. Validation and Logic Bugs

The fuzzer automatically detects crashes and hangs. But what about logical bugs, where the server gives a *valid* but *incorrect* response (e.g., a negative bank balance)? The `validate_response` function is your "specification oracle" for this.

```python
def validate_response(response: bytes) -> bool:
    """
    Checks if the server's response violates protocol rules.
    Return True if valid, False if a logical bug is found.
    Raise ValueError for severe issues to provide more detail.
    """
    # Example: Check for business logic bugs
    import struct
    if len(response) < 14:
        return True # Not our concern

    command = response[5]
    if command == 4:  # BALANCE response
        balance = struct.unpack(">i", response[10:14])[0]
        if balance < 0:
            # Found a logic bug! Negative balance should be impossible.
            raise ValueError(f"Negative balance detected: {balance}")

    return True
```
A `False` return or a raised exception will be flagged as an **Anomaly**.

---

## 6. Testing and Debugging

### Testing Plugins Locally

Before starting a long fuzzing run, always test your plugin.

1.  **Load the plugin**: `python -c "from core.plugin_loader import plugin_manager; plugin_manager.load_plugin('your_protocol')"`
2.  **Send seeds to your target**: Use a simple Python script to send the seeds from your `data_model` to your test server and check that you get valid responses. See `test_target.py` in the main `tests` directory for an example.
3.  **Run a short fuzzing session**: Run a session for 60 seconds and check for immediate errors in the `core` logs.

### Troubleshooting Common Issues

-   **Plugin not loading**: Check for Python syntax errors. Check the `core` logs for loading errors.
-   **Session fails immediately**: Check basic connectivity (`nc -zv <host> <port>`). Use `tcpdump` to compare the fuzzer's first packet to a known-good client's packet.
-   **Orchestration `bootstrap` fails**: Check the `core` logs for errors from the `StageRunner`. The `bootstrap` stage must produce a 100% valid interaction. Isolate it and test it manually.
-   **Heartbeat failures**: Does the heartbeat message require a value from the context that isn't being set? Is the `interval` too long or too short?

For more, see the **[User Guide](USER_GUIDE.md)** troubleshooting section.