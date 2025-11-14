# Fuzzing Engine: Developer Documentation

## 3. Protocol Parsing and Plugins

The fuzzing engine's "intelligence"—its ability to perform structure-aware mutations—is entirely dependent on its knowledge of the protocol being tested. This knowledge is provided by **protocol plugins**.

### The Role of Plugins

A plugin is a self-contained Python file that provides the fuzzing engine with the essential metadata it needs to understand a specific protocol. Each plugin must define a `data_model`, and for stateful protocols, a `state_model`.

The engine's plugin-driven architecture makes it highly extensible. To fuzz a new protocol, a developer simply needs to create a new plugin file that accurately describes it.

### The Data Model

The `data_model` is a Python dictionary that defines the structure of the protocol's messages. It is the single most important piece of information for structure-aware fuzzing.

A `data_model` consists of two main parts:

1.  **`blocks`**: A list of dictionaries, where each dictionary describes a single field in the protocol message in the order they appear.
2.  **`seeds`**: A list of raw byte strings representing valid or interesting messages. These are used as the initial inputs for the mutation engine.

Let's examine a field definition from the example `kevin.py` plugin:

```python
# core/plugins/kevin.py

"blocks": [
    {
        "name": "magic",
        "type": "bytes",
        "size": 4,
        "default": b"KEVN",
        "mutable": False
    },
    {
        "name": "length",
        "type": "uint32",
        "endian": "big",
        "is_size_field": True,
        "size_of": "payload"
    },
    {
        "name": "payload",
        "type": "bytes",
        "max_size": 1024,
        "default": b""
    }
],
```

Each block defines properties of a field:
- **`name`**: A unique identifier for the field.
- **`type`**: The data type (e.g., `uint32`, `bytes`, `string`).
- **`size`** or **`max_size`**: The fixed size or maximum size of the field.
- **`mutable`**: A boolean indicating whether the mutation engine is allowed to change this field. This is crucial for protecting static values like magic headers.
- **`is_size_field`** and **`size_of`**: These special properties create a dependency. Here, the `length` field's value will be automatically calculated based on the actual size of the `payload` field during serialization. You can now pass a list to `size_of` (e.g., `["body", "footer"]`) when a length field spans several consecutive blocks.
- **`response_model`**: Optional schema describing how to parse server replies. It mirrors the `data_model` syntax.
- **`response_handlers`**: Optional list of declarative rules for building follow-up messages using parsed response fields.

### The Protocol Parser

The `ProtocolParser` (`core/engine/protocol_parser.py`) is the component that brings the `data_model` to life. It provides two key functions: `parse` and `serialize`.

-   **`parse(data: bytes)`**: Takes a raw byte string and, using the `data_model`, converts it into a dictionary of fields and their values.
-   **`serialize(fields: dict)`**: Takes a dictionary of fields and converts it back into a raw byte string.

This bidirectional conversion is the core of structure-aware fuzzing. The `StructureAwareMutator` uses `parse` to deconstruct a seed, `mutates` a value in the resulting dictionary, and then uses `serialize` to reconstruct a valid message.

#### Automatic Field Fixing

The most powerful feature of the `ProtocolParser` is its ability to automatically fix dependent fields during serialization. When `serialize()` is called, it first runs a process called `_auto_fix_fields`.

```python
# core/engine/protocol_parser.py

class ProtocolParser:
    # ...
    def _auto_fix_fields(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        fields = fields.copy()

        # Update length fields
        for block in self.blocks:
            if not block.get('is_size_field'):
                continue

            targets = self._normalize_size_of_targets(block.get('size_of'))
            total_size = 0
            for target in targets:
                target_value = fields.get(target, b'')
                total_size += self._calculate_field_length(self._get_block(target), target_value)

            fields[block['name']] = total_size

        # TODO: Update checksum fields
        return fields
```

This method iterates through the blocks in the `data_model`. If it finds a field marked with `is_size_field: True`, it calculates the actual length of the field referenced by `size_of` and updates the length field's value accordingly.

This ensures that even if a mutation changes the size of the `payload`, the `length` field will be correct in the final test case, preserving the structural validity of the message and allowing the fuzzer to bypass simple parsing checks in the target application.

### Response Planning

Protocols that require a server-issued token (e.g., session IDs) can now describe responses explicitly. Define a `response_model` and at least one `response_handler`:

```python
response_handlers = [
    {
        "name": "sync_token",
        "match": {"status": 0x00},
        "set_fields": {
            "command": 0x10,
            "session_id": {"copy_from_response": "session_token"},
        },
    }
]
```

When the orchestrator receives a response, the `ResponsePlanner` parses it, runs every matching handler, and queues follow-up requests built from the request `data_model`. This keeps the handshake/authentication pipeline self-contained inside the plugin.
