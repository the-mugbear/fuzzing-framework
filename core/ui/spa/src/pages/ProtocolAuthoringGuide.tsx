import React from 'react';
import GuidePage from './GuidePage';

const ProtocolAuthoringGuide: React.FC = () => {
  const content = (
    <>
      <p className="callout">This guide provides a complete walkthrough for creating a robust protocol plugin. A well-defined plugin is the key to a successful fuzzing campaign, enabling the fuzzer to understand the target's language and explore its logic deeply.</p>

      <section>
        <h2>1. Understand the Protocol: The Blueprint</h2>
        <p>Before writing any code, you must become an expert on the protocol. The goal is to create a "blueprint" of the protocol's structure and behavior.</p>
        <ul>
          <li><strong>Reverse Engineer the Message Structure</strong>: Document every field, including its name, type (e.g., `uint32`, `string`), size, and endianness (big or little). Use tools like Wireshark to capture and analyze traffic from a legitimate client. If you have access to the source code, that's even better.</li>
          <li><strong>Map the State Machine</strong>: Does the protocol have a concept of sessions or states? Most do. Draw a diagram showing the different states (e.g., `DISCONNECTED`, `AUTHENTICATING`, `READY`) and the messages that cause transitions between them.</li>
          <li><strong>Collect Valid Examples (Seeds)</strong>: Capture at least 3-5 valid, diverse messages. These will be the starting point for the fuzzer's mutations. Include messages for different states and commands.</li>
        </ul>
      </section>

      <section>
        <h2>2. Define the Data Model: The `data_model`</h2>
        <p>The `data_model` is a Python dictionary that describes the protocol's message structure. It's an ordered list of "blocks," where each block is a field in the message.</p>
        <pre>{`data_model = {
    "name": "MyProtocol",
    "description": "A sample protocol for a simple banking service.",
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"BANK", "mutable": False, "description": "Constant header to identify the protocol."}, 
        {"name": "version", "type": "uint8", "default": 1, "description": "Protocol version number."}, 
        {"name": "command", "type": "uint8", "values": {0x01: "LOGIN", 0x02: "TRANSFER", 0x03: "LOGOUT"}, "description": "The operation to be performed."}, 
        {"name": "length", "type": "uint16", "endian": "big", "is_size_field": True, "size_of": "payload", "description": "Length of the variable payload."}, 
        {"name": "payload", "type": "bytes", "max_size": 512, "description": "Variable-length data for the command."}, 
        {"name": "checksum", "type": "uint32", "behavior": {"operation": "checksum", "algorithm": "crc32", "fields": ["version", "command", "length", "payload"]}, "description": "CRC32 checksum of the message."} 
    ],
    "seeds": [
        b"BANK\x01\x01\x00\x08user:pass", # LOGIN
        b"BANK\x01\x02\x00\x10amount:100,to:123", # TRANSFER
    ],
}`}</pre>
        <p>Mark static fields like headers or signatures as <code>mutable: false</code> to prevent the fuzzer from changing them. For variable-length fields, use <code>is_size_field: True</code> and <code>size_of</code> to tell the fuzzer how to calculate lengths automatically. You can point to a single field (<code>"size_of": "payload"</code>) or pass a list (<code>"size_of": ["payload", "trailer"]</code>) when a length covers multiple consecutive blocks. Keep payload fields generous (<code>max_size</code>) so mutators have room to explore.</p>
      </section>

      <section>
        <h2>3. Parse Responses & Plan Follow-ups</h2>
        <p>Some protocols issue tokens or nonces that must be echoed in the next message. Use an optional <code>response_model</code> to describe server replies and <code>response_handlers</code> to declare how to build follow-up requests.</p>
        <pre>{`response_model = {
    "blocks": [
        {"name": "magic", "type": "bytes", "size": 4, "default": b"BANK"},
        {"name": "status", "type": "uint8", "values": {0x00: "OK", 0xFF: "ERROR"}},
        {"name": "session_token", "type": "uint64"},
    ]
}

response_handlers = [
    {
        "name": "carry_session_token",
        "match": {"status": 0x00},
        "set_fields": {
            "command": 0x10,
            "session_id": {"copy_from_response": "session_token"}
        }
    }
]`}</pre>
        <p>The orchestrator parses every response with <code>response_model</code>, evaluates the handlers, and automatically queues the follow-up requests they describe—perfect for handshake → authenticated pipelines.</p>
      </section>

      <section>
        <h2>4. Add Field Behaviors: The "Protocol Glue"</h2>
        <p>Behaviors are rules that the fuzzer applies <em>before</em> sending each test case. They are the "glue" that keeps the protocol valid enough for the target to accept the message, even after mutation. This is crucial for getting past the initial parsing stages and into deeper application logic.</p>
        <pre>{`{
    "name": "sequence",
    "type": "uint16",
    "behavior": {
        "operation": "increment",
        "initial": 0,
        "step": 1,
        "wrap": 65536
    }
},
{
    "name": "checksum",
    "type": "uint8",
    "behavior": {
        "operation": "add_constant",
        "value": 0x55
    }
}`}</pre>
        <ul>
          <li><strong>`increment`</strong>: Automatically increments a sequence number or counter. The fuzzer tracks the current value for the session.</li>
          <li><strong>`add_constant`</strong>: Adds a constant value to a field. Useful for simple checksums or required values.</li>
          <li><strong>`checksum`</strong>: Calculates a checksum over a list of fields. Supported algorithms include `crc32`, `xor`, and simple `sum`.</li>
        </ul>
        <p>Behaviors require fixed-width blocks (e.g., `uint16`, `uint32`, or `bytes` with a `size`). They run in both core and agent modes and remove the need for complex custom mutators.</p>
      </section>

      <section>
        <h2>5. Model the State Machine: The `state_model`</h2>
        <p>If the protocol is stateful, the `state_model` tells the fuzzer how to navigate the protocol's logic. Without this, the fuzzer would send messages in a random order, and most would be rejected.</p>
        <pre>{`state_model = {
    "initial_state": "DISCONNECTED",
    "states": ["DISCONNECTED", "AUTHENTICATED", "READY"],
    "transitions": [
        {"from": "DISCONNECTED", "to": "AUTHENTICATED", "message_type": "LOGIN", "expected_response": "LOGIN_OK"},
        {"from": "AUTHENTICATED", "to": "READY", "message_type": "TRANSFER", "expected_response": "TRANSFER_OK"},
        {"from": "READY", "to": "READY", "message_type": "DATA"},
        {"from": "READY", "to": "DISCONNECTED", "message_type": "LOGOUT"},
    ]
}`}</pre>
        <p>The `message_type` should correspond to a value in your `command` field's `values` map. The `expected_response` is a substring that the fuzzer looks for in the target's reply to confirm that the transition was successful.</p>
      </section>

      <section>
        <h2>5. Create a Response Validator: The "Logic Oracle"</h2>
        <p>The fuzzer automatically detects crashes and hangs. The optional `validate_response` function is your "logic oracle"—it detects when the target violates the protocol's rules <em>without</em> crashing. This is how you find logic bugs, information leaks, and other non-crash vulnerabilities.</p>
        <pre>{`def validate_response(response: bytes) -> bool:
    # Rule 1: Response must start with the correct magic bytes.
    if not response.startswith(b"BANK"):
        return False # Violation found!

    # Rule 2: An error code in the response indicates a problem.
    if len(response) > 8 and response[8] == 0xFF:
        raise ValueError("Server returned a fatal error code!") # Raise an exception for severe issues.

    return True # Response seems valid.
`}</pre>
        <p>Return <code>False</code> or raise a `ValueError` when the target's response is unexpected or indicates a logical flaw.</p>
      </section>

      <section>
        <h2>6. Test and Refine Your Plugin</h2>
        <p>Testing is an iterative process. Use the tools provided to ensure your plugin is working correctly.</p>
        <ul>
          <li><strong>Plugin Debugger UI</strong>: Use the "Plugin Debugger" tab in the web UI to preview how the fuzzer parses your seeds and generates mutations. This is the best way to verify that your `data_model` and `behaviors` are correct.</li>
          <li><strong>API Endpoints</strong>: Use `curl` to interact with the API directly.
            <ul>
              <li><code>GET /api/plugins/&lt;name&gt;</code>: See if your plugin is loaded correctly.</li>
              <li><code>POST /api/tests/execute</code>: Send a single, specific payload to the target to test its response.</li>
            </ul>
          </li>
          <li><strong>Core Logs</strong>: Watch the `core` service logs for errors related to your plugin.</li>
        </ul>
      </section>

      <section>
        <h2>7. Best Practices and Packing Tips</h2>
        <ul>
          <li><strong>Document Everything</strong>: Use the `description` fields in your `data_model` and add a detailed docstring to the top of your plugin file explaining any quirks or assumptions.</li>
          <li><strong>Sanitize Seeds</strong>: Keep credentials, tokens, and other environment-specific data out of your committed plugin files. Use placeholder values.</li>
          <li><strong>Start Simple, Then Iterate</strong>: Don't try to model the entire protocol at once. Start with a few basic messages and states, get that working, and then expand.</li>
          <li><strong>Promote Findings</strong>: When the fuzzer finds a new crashing input, add it to your `seeds` list to guide future fuzzing runs.</li>
        </ul>
      </section>
    </>
  );

  return <GuidePage title="Comprehensive Protocol Authoring Guide" content={content} />;
};

export default ProtocolAuthoringGuide;
