# Guide to Orchestrated Sessions

**Last Updated: 2026-01-30**

This guide provides a deep dive into **Orchestrated Sessions**, a powerful feature for fuzzing complex, stateful protocols that require multiple steps like handshakes, authentication, or negotiation before the main fuzzing can begin.

## 1. What Are Orchestrated Sessions?

Imagine a protocol where you can't just send fuzzing data. You first have to:
1.  Connect and send a `HELLO` message.
2.  The server replies with a unique `SESSION_TOKEN`.
3.  All subsequent messages must include that exact `SESSION_TOKEN` to be considered valid.

A simple fuzzer would fail because its mutated messages wouldn't have the correct token. An **Orchestrated Session** solves this by letting you define a sequence of actions, or **stages**, that the fuzzer must execute in order.

A typical orchestration looks like this:
-   **`bootstrap` stage**: Perform the initial handshake and **extract** the `SESSION_TOKEN` from the server's response.
-   **`fuzz_target` stage**: **Inject** the captured `SESSION_TOKEN` into every test case before sending it to the target.
-   **`teardown` stage**: (Optional) Send a `LOGOUT` or `FIN` message to gracefully close the session.

## 2. Core Concepts

Orchestration is configured entirely within your protocol plugin using a few key objects.

### The `protocol_stack`
This is the main entry point. It defines the sequence of stages. Each stage points to a protocol plugin that defines the messages for that stage.

```python
# In your main plugin file, e.g., my_orchestrated_protocol.py
protocol_stack = {
    "name": "MyOrchestratedProtocol",
    "stages": [
        {
            "name": "bootstrap",
            "plugin": "my_handshake_plugin" # Defines the HELLO message
        },
        {
            "name": "fuzz_target",
            "plugin": "my_fuzzing_plugin"   # Defines the core protocol to be fuzzed
        }
    ]
}
```

### The `connection` Object
Stateful interactions require a connection that stays open across multiple messages. The `connection` object makes this possible.

```python
connection = {
    "transport": "tcp",
    "persistent": True  # Keep the connection open for the whole session
}
```

### The `ProtocolContext`: Passing Data Between Stages
The `ProtocolContext` is a temporary key-value store for sharing data between stages.

-   `exports`: Defined in a `bootstrap` plugin to **save** a value from a server response into the context.
-   `from_context`: Used in a field definition in a subsequent plugin to **load** a value from the context.

### The `heartbeat` Object: Keeping Sessions Alive
Long-running sessions can be terminated by firewalls or idle timeouts. A `heartbeat` sends periodic background messages to keep the connection alive. It can also make the fuzzer **self-healing** by automatically reconnecting and re-running the bootstrap if the connection is lost.

## 3. Step-by-Step Configuration Example

Let's build the `SESSION_TOKEN` example. We'll need three files:
1.  `my_orchestrated_protocol.py`: The main plugin that defines the stack.
2.  `my_handshake_plugin.py`: The plugin for the `bootstrap` stage.
3.  `my_fuzzing_plugin.py`: The plugin for the `fuzz_target` stage.

### Step 1: The Handshake Plugin (`bootstrap`)

This plugin defines the `HELLO` message and, most importantly, **exports** the token from the server's response.

**`core/plugins/my_handshake_plugin.py`**:
```python
# A simple HELLO message
data_model = {
    "name": "Handshake",
    "blocks": [
        {"name": "cmd", "type": "bytes", "size": 4, "default": b"HELO"},
    ]
}

# This is where the magic happens.
# After sending HELO, the server responds. We parse that response
# and save the 'token' field into the ProtocolContext.
exports = {
    "session_token": {
        "from_field": "response.token", # Assumes the response has a field named 'token'
        "type": "uint32"
    }
}
```
*Note: For the `response.token` to work, the `my_handshake_plugin` would also need a `data_model` for the response, or you can extract bytes directly.*

### Step 2: The Fuzzing Plugin (`fuzz_target`)

This plugin defines the core protocol messages to be fuzzed. It uses `from_context` to inject the `session_token` captured in the previous stage.

**`core/plugins/my_fuzzing_plugin.py`**:
```python
data_model = {
    "name": "CoreFuzzingProtocol",
    "blocks": [
        {
            "name": "cmd",
            "type": "bytes",
            "size": 4,
            "default": b"FUZZ"
        },
        {
            "name": "session_token",
            "type": "uint32",
            "from_context": "session_token" # Injects the value from the context
        },
        {
            "name": "fuzzed_payload",
            "type": "bytes",
            "max_size": 1024
        }
    ],
    "seeds": [
        # Seeds for this stage don't need the token; it will be added automatically
        b"FUZZ\x00\x00\x00\x00some_data",
    ]
}
```

### Step 3: The Main Plugin (`protocol_stack`, `connection`, `heartbeat`)

This file ties everything together.

**`core/plugins/my_orchestrated_protocol.py`**:
```python
__version__ = "1.0.0"

# 1. Define the sequence of plugins to run
protocol_stack = {
    "name": "MyOrchestratedProtocol",
    "stages": [
        {"name": "bootstrap", "plugin": "my_handshake_plugin"},
        {"name": "fuzz_target", "plugin": "my_fuzzing_plugin"}
    ]
}

# 2. Specify that the connection should be kept open
connection = {
    "transport": "tcp",
    "persistent": True
}

# 3. (Optional but recommended) Define a heartbeat to keep the session alive
heartbeat = {
    "name": "KeepAlive",
    "interval": 10.0, # Send a ping every 10 seconds
    "message": {
        "blocks": [
            {"name": "cmd", "type": "bytes", "size": 4, "default": b"PING"},
            # The heartbeat can also use the session token!
            {
                "name": "session_token",
                "type": "uint32",
                "from_context": "session_token"
            }
        ]
    },
    "expect_response": True,
    # If the heartbeat fails 3 times, reconnect and re-bootstrap
    "on_failure": {"action": "reconnect", "threshold": 3}
}
```

## 4. Running and Monitoring

1.  **Select the main plugin** (`my_orchestrated_protocol`) in the UI when creating a session.
2.  Click **Start**.
3.  **Monitor the `core` logs**. You should see messages indicating the progression through the stages:
    -   `INFO: [StageRunner] Executing stage: bootstrap`
    -   `INFO: [StageRunner] Stage bootstrap completed successfully.`
    -   `INFO: [ProtocolContext] Exported 'session_token' with value: 12345678`
    -   `INFO: [FuzzOrchestrator] Starting fuzzing for stage: fuzz_target`
    -   `INFO: [HeartbeatScheduler] Starting heartbeat for session...`

## 5. Troubleshooting

-   **`bootstrap` stage fails**:
    -   **Problem**: The session stops before any fuzzing begins. Logs show errors from the `StageRunner`.
    -   **Solution**: Your `bootstrap` plugin is not sending a 100% valid handshake. Isolate the handshake plugin and test it manually against your target. Use `tcpdump` to ensure the bytes on the wire are identical to a known-good client.

-   **Context value is not being injected**:
    -   **Problem**: The target rejects fuzzed messages, complaining of an invalid token.
    -   **Solution**: Check the `core` logs. Did the `export` actually succeed? Ensure the `from_field` in your `exports` object correctly points to a field in the server's response. Check for typos between the key in `exports` and the key in `from_context`.

-   **Heartbeat failures**:
    -   **Problem**: The session dies after a period of inactivity. Logs may show `Heartbeat failed` messages.
    -   **Solution**: Does your heartbeat message itself require context variables (like `session_token`)? Ensure they are being exported correctly. Is the server expecting a PING and you are not sending one? Set `expect_response: false` if the server does not reply to pings.

---
For a complete, working implementation, see the **`orchestrated_example.py`** plugin. For a deeper technical overview, see the **[Orchestrated Sessions Architecture](developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md)** document.