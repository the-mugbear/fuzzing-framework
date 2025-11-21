# Protocol Plugin Authoring Guide

This guide provides a complete, in-depth walkthrough of how to create a custom protocol plugin for the fuzzer. A well-crafted plugin is the key to an effective fuzzing campaign, as it teaches the fuzzer the "language" of your target protocol.

This guide is for developers who want to extend the fuzzer to support new protocols. It assumes a basic understanding of Python and the protocol you intend to test.

## 1. The Anatomy of a Plugin

A protocol plugin is a single Python file in the `core/plugins/` directory that defines up to three key components:

1.  **`data_model` (Required)**: A dictionary that describes the structure of your protocol's messages.
2.  **`state_model` (Optional)**: A dictionary that defines the protocol's state machine, for stateful protocols.
3.  **`validate_response` (Optional)**: A function that acts as a "specification oracle," checking for logical bugs in the target's responses.

## 2. Creating the `data_model`

The `data_model` is the most critical part of the plugin. It tells the fuzzer how to parse and serialize messages, enabling structure-aware fuzzing.

### Step 1: Define the Message Structure (`blocks`)

The `blocks` key contains a list of dictionaries, where each dictionary represents a single field in your protocol's message, in the order they appear.

```python
data_model = {
    "name": "YourProtocol",
    "description": "A description of your protocol.",

    "blocks": [
        # Field definitions go here
    ],

    "seeds": [
        # Seed data goes here
    ]
}
```

### Step 2: Define Each Field

Each block in the `blocks` list can have several properties:

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

### Step 3: Define Calculated Fields and Behaviors

Many protocols have fields whose values depend on other fields (like length prefixes) or that change in predictable ways (like sequence numbers). The fuzzer can manage these automatically.

#### Length Prefixes

To define a length prefix, use the `is_size_field` and `size_of` properties.

```python
{
    "name": "length",
    "type": "uint32",
    "endian": "big",
    "is_size_field": True,     # Marks this as a length field.
    "size_of": "payload"       # Tells the fuzzer this field's value is the length of the "payload" field.
                               # You can also use a list: ["field1", "field2"]
}
```
When the fuzzer mutates the `payload`, it will automatically recalculate its length and update the `length` field before sending the message.

#### Behaviors

Behaviors are for fields that follow a deterministic pattern. Define a `behavior` dictionary inside the field's block.

```python
{
    "name": "sequence",
    "type": "uint16",
    "behavior": {
        "operation": "increment",   # The operation to perform.
        "initial": 0,               # The starting value.
        "step": 1,                  # The value to increment by on each message.
        "wrap": 65536               # The value at which to wrap around to `initial`.
    }
}
```
The only currently supported `operation` is `increment`. This is ideal for sequence numbers.

### Step 4: Provide High-Quality Seeds

The `seeds` list should contain several examples of valid, real-world messages for your protocol. The fuzzer will use these as the starting point for mutation.

*   **Provide Variety**: Include seeds for different message types and states.
*   **Use Real Data**: If possible, capture traffic from a real client and use it to create your seeds.

```python
"seeds": [
    # A valid CONNECT message
    b"BANK\x01\x00\x00\x00\x00\x00",
    # A valid AUTH message
    b"BANK\x02\x00\x00\x00\x10admin:password123",
    # A valid TRANSFER message
    b"BANK\x03\x00\x00\x00\x08\x00\x00\x03\xe8TO:1234"
]
```

## 3. Defining Stateful Interactions

If your protocol is stateful, you must define a `state_model` to guide the fuzzer.

```python
state_model = {
    "initial_state": "DISCONNECTED",

    "states": [ "DISCONNECTED", "CONNECTED", "AUTHENTICATED" ],

    "transitions": [
        {
            "from": "DISCONNECTED",
            "to": "CONNECTED",
            "message_type": "CONNECT" # Corresponds to command value 1
        },
        {
            "from": "CONNECTED",
            "to": "AUTHENTICATED",
            "message_type": "AUTH"    # Corresponds to command value 2
        }
    ]
}
```
The `message_type` in each transition should correspond to a logical message type in your `data_model` (often based on a "command" field). This allows the fuzzer to send messages in the correct order.

### Handling Server-Sent Data (`response_model` and `response_handlers`)

Some protocols require the client to use data provided by the server (e.g., a session token). You can model this declaratively.

1.  **`response_model`**: Add a `response_model` to your `data_model` to describe the structure of the server's replies. It follows the same format as `blocks`.
2.  **`response_handlers`**: Add a `response_handlers` list to your `data_model`. Each handler is a rule that tells the fuzzer how to react to a specific response.

**Example**: A server sends a session token upon successful login.

```python
data_model = {
    # ... blocks for client-sent messages ...
    "blocks": [
        {"name": "command", "type": "uint8"},
        {"name": "token", "type": "uint32", "default": 0}
        # ...
    ],

    # Model for the server's response
    "response_model": {
        "blocks": [
            {"name": "status", "type": "uint8"},
            {"name": "session_token", "type": "uint32"}
        ]
    },

    # Rules for reacting to the response
    "response_handlers": [
        {
            "name": "handle_login_success",
            "match": {"status": 0x00},  # If the response status is 0 (success)
            "set_fields": {
                # Construct the next message to send
                "command": 3, # Next command is TRANSFER
                # Copy the token from the server's response into our next message
                "token": {"copy_from_response": "session_token"}
            }
        }
    ]
}
```
This powerful feature allows the fuzzer to handle complex, interactive protocols without any custom code.

## 4. Creating a Specification Oracle (`validate_response`)

You can add a `validate_response` function to your plugin. This function acts as a "specification oracle," checking for logical bugs in the target's responses that wouldn't cause a crash.

```python
def validate_response(response: bytes) -> bool:
    """
    Checks if the server's response violates protocol rules.
    Returns True if valid, False if a logical bug is found.
    Can also raise a ValueError for severe violations.
    """
    # Example: Check if a length field in the response is correct.
    import struct
    if len(response) < 8: return False
    declared_length = struct.unpack(">I", response[4:8])[0]
    actual_length = len(response) - 8
    if declared_length != actual_length:
        # This is a logical bug! The server sent a malformed response.
        return False

    # Example: Check for business logic bugs.
    # A balance inquiry should never return a negative number.
    if response[0] == 0x10: # Balance response command
        balance = struct.unpack(">i", response[8:12])[0]
        if balance < 0:
            raise ValueError(f"Negative balance detected: {balance}")

    return True
```

## 5. Testing and Debugging Your Plugin

An incorrect plugin is worse than no plugin at all. Thoroughly test your plugin before starting a long fuzzing campaign.

### Step 1: Verify the Plugin Loads

After creating your plugin file, restart the fuzzer and check the API:
```bash
curl http://localhost:8000/api/plugins/your_protocol
```
If you get a 404 error, check the fuzzer's logs for syntax errors in your plugin file.

### Step 2: Test Your Seeds

Use a simple Python script to connect to your target and send each of your seeds. Does the target respond as expected?

```python
# test_target.py
import socket
from core.plugin_loader import plugin_manager

# ... (load plugin, connect to target) ...

for seed in protocol.data_model['seeds']:
    sock.sendall(seed)
    response = sock.recv(4096)
    # ... print and validate the response ...
```
*(See the full `test_target.py` script in the original document for a complete example.)*

### Step 3: Use the Preview Endpoint

The preview endpoint is your best friend for debugging. It shows you how the fuzzer parses a message and how it might mutate it.

```bash
curl -X POST http://localhost:8000/api/plugins/your_protocol/preview \
  -H "Content-Type: application/json" \
  -d '{"data": "BASE64_ENCODED_SEED_DATA"}'
```
Check the output to ensure fields are being parsed correctly and that `mutable: False` is being respected.

### Step 4: Run a Short Fuzzing Session

Run a session for just a few minutes.
-   Does the `total_tests` count increase? If not, there's a fundamental problem with the connection or the initial messages.
-   Do all tests result in crashes? This usually means the target is not running or is immediately closing the connection. Check your seeds and the target's logs.

By following this structured approach, you can create a robust and effective protocol plugin that enables the fuzzer to find deep and interesting bugs in your target application.