# Fuzzing Engine: Developer Documentation

## 6. Advanced Logic: Size Calculation and Response Handling

Beyond basic mutation, the fuzzing engine incorporates several "intelligent" features that allow it to interact with complex protocols. These features are primarily driven by special declarations within a plugin's `data_model`. This document covers two key mechanisms: automatic size calculation and declarative response handling.

### Automatic Size Calculation

Many protocols use length-prefixing, where one field in a message header specifies the size of a variable-length field that follows. The fuzzer must correctly update this length field whenever a mutation changes the size of the payload; otherwise, the target will reject the message at the parsing stage, preventing deeper testing.

The engine handles this automatically using the `is_size_field` and `size_of` properties in the `data_model`.

#### How It Works

When the `ProtocolParser` serializes a test case from a dictionary of fields back into bytes, it first runs a process called `_auto_fix_fields`. This method ensures all dependent fields are correctly calculated before the final message is constructed.

1.  **Identify Length Fields**: The parser scans the `data_model` for any block marked with `"is_size_field": True`.
2.  **Identify Target Fields**: For each length field, it looks at the `size_of` property. This property can be a single field name (e.g., `"payload"`) or a list of field names (e.g., `["body", "footer"]`).
3.  **Calculate Total Size**: The parser then calculates the serialized length of each target field.
4.  **Update Length Field**: The sum of these lengths is written into the length field.

Here is the core logic from `core/engine/protocol_parser.py`:

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
            for target_field in targets:
                target_block = self._get_block(target_field)
                # ...
                target_value = fields.get(target_field, ...)
                total_size += self._calculate_field_length(target_block, target_value)

            fields[block['name']] = total_size
        # ...
        return fields
```

#### Example

Consider this `data_model`:

```python
"blocks": [
    # ...
    {
        "name": "length",
        "type": "uint32",
        "is_size_field": True,
        "size_of": "payload"
    },
    {
        "name": "payload",
        "type": "bytes",
        "max_size": 1024
    }
]
```

If a mutation changes the `payload` to be `b"some new data"`, which is 14 bytes long, the `_auto_fix_fields` method will automatically set the value of the `length` field to `14` before serialization. This ensures the final message is always structurally valid with respect to its length prefixes.

### Declarative Response Handling

Many protocols require a client to react to server responses. For example, a server might send a session token that must be included in all subsequent client messages. To handle these scenarios without writing custom code for every protocol, the engine provides a declarative mechanism using `response_model` and `response_handlers`.

#### How It Works

The `ResponsePlanner` (`core/engine/response_planner.py`) is responsible for processing server responses and generating follow-up messages.

1.  **Define Response Structure**: A plugin can optionally define a `response_model` in its `data_model`. This model has the same structure as the main `blocks` definition and tells the engine how to parse messages *received from* the server. If it's not defined, the engine assumes responses have the same layout as requests.

2.  **Define Handlers**: The plugin also defines a list of `response_handlers`. Each handler is a rule that consists of a `match` condition and a `set_fields` action.

3.  **Process Response**: When the fuzzer receives a response from the target, the `ResponsePlanner` does the following:
    a.  It parses the raw response bytes using the `response_model`.
    b.  It iterates through the `response_handlers` and finds the first one where the `match` condition is met by the parsed response fields.
    c.  It then constructs a new message to send. It starts with the default fields of a request message and then overwrites them based on the `set_fields` action.

The `set_fields` action is powerful because it can copy values directly from the server's response.

```python
# core/engine/response_planner.py

class ResponsePlanner:
    # ...
    def plan(self, response_bytes: Optional[bytes]) -> List[Dict[str, Any]]:
        # ...
        parsed_response = self.response_parser.parse(response_bytes)
        # ...
        for handler in self.handlers:
            if not self._matches(handler.get("match", {}), parsed_response):
                continue

            payload = self._build_payload(handler, parsed_response)
            # ...

    def _build_payload(self, handler: Dict[str, Any], parsed_response: Dict[str, Any]) -> Optional[bytes]:
        set_fields = handler.get("set_fields", {})
        # ...
        fields = deepcopy(self.default_fields)
        for field_name, spec in set_fields.items():
            fields[field_name] = self._resolve_field_value(spec, parsed_response)

        return self.request_parser.serialize(fields)

    @staticmethod
    def _resolve_field_value(spec: Any, parsed_response: Dict[str, Any]) -> Any:
        if isinstance(spec, dict):
            if "copy_from_response" in spec:
                return parsed_response.get(spec["copy_from_response"])
        return spec
```

#### Example

Imagine a protocol where the client sends a `LOGIN` message and the server replies with a `LOGIN_SUCCESS` message containing a session token. All future messages must include this token.

Here's how you would define this in a plugin:

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

With this configuration, when the server replies with a success status, the `ResponsePlanner` will automatically generate a `GET_DATA` message with the `token` field correctly populated from the server's response. This allows the fuzzer to proceed with stateful interactions that depend on server-provided data, all without writing any imperative logic.