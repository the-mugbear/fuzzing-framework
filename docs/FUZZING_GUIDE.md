# Fuzzing Guide

A practical reference to help you speak the same language as the fuzzer, structure campaigns intentionally, and triage findings quickly.

## Terminology Cheat Sheet

| Term | Meaning |
| --- | --- |
| **Seed** | A valid byte sequence that bootstraps the mutation engine. Stored in `data/corpus/seeds`. |
| **Corpus** | All seeds plus interesting mutations and crash reproducers saved during a run. |
| **Session** | A fuzzing campaign bound to a protocol, host, port, execution mode, and mutator selection. |
| **Mutator** | Algorithm that transforms a seed (e.g., `bitflip`, `havoc`, `splice`). Choose them via `enabled_mutators`. |
| **Behavior** | Declarative rule attached to a protocol block (e.g., “increment sequence”, “add constant”). Behaviors run before every send to keep deterministic fields valid. |
| **Agent Mode** | Test cases are executed by remote agents that talk to the target and stream results back to the core. |
| **One-off Test** | Single payload execution via `POST /api/tests/execute`—use it for quick validation or reproduction. |

## Building an Effective Campaign

1. **Instrument the Target**
   - Run the sample target (`make run-target` or `docker compose up target`) and tail its logs so you can see each fuzz case.
   - For custom binaries, expose structured logs or even a basic metrics endpoint—fuzzing is faster when you can spot crashes immediately.

2. **Author/Review the Protocol Plugin**
   - Define immutable headers (`mutable: false`) so core signatures stay intact.
   - Model state transitions and supply at least 3 realistic seeds.
   - Add `behavior` blocks for deterministic fields:
     ```python
     {
         "name": "sequence",
         "type": "uint16",
         "behavior": {"operation": "increment", "initial": 0, "step": 1}
     }
     {
         "name": "checksum",
         "type": "uint8",
         "behavior": {"operation": "add_constant", "value": 0x55}
     }
     ```
     Behaviors are executed automatically in both core and agent modes, so mutators can focus on the truly interesting bytes.

3. **Choose Execution & Mutators**
   - Core mode is simplest; agent mode lets you forward traffic via remote workers/monitors.
   - Use `/api/mutators` to list options and pass `enabled_mutators` when creating the session. Start broad (bitflip + havoc) and tighten once you know which fields trigger bugs.

4. **Run & Observe**
   - Kick off the session, then poll `/api/sessions/<id>/stats` or watch the UI dashboard. Rising `total_tests`, `hangs`, or `anomalies` confirm progress.
   - Monitor target logs, `logs/core-api.log`, and agent logs simultaneously. Each crash is saved under `data/corpus/findings/<id>` with both the repro input and JSON metadata.

5. **Triage & Iterate**
   - Re-run interesting seeds via the one-off endpoint or netcat to confirm determinism.
   - Promote failing inputs to the seed corpus for focused future runs.
   - Update the protocol plugin (new blocks, behaviors, validators) as you learn about the target.

## Stateful Fuzzing Basics

State models are now first-class: when a plugin exposes `state_model`, the orchestrator instantiates
`StatefulFuzzingSession` to keep sequences valid.

1. **Define transitions intentionally** – Include `initial_state`, `states`, and `transitions` with
   `message_type` labels that match the command block's `values` map. Optional `expected_response`
   strings help the runtime validate replies before advancing.
2. **Seed per message type** – Provide at least one seed for every `message_type` so the engine can
   pick the right template when it needs to send CONNECT vs AUTH vs DATA.
3. **Monitor coverage** – Hit `GET /api/sessions/{id}/state_coverage` (or watch the UI state diagram)
   to see which states/transitions have been exercised. Reset or tweak `structure_aware_weight` if
   coverage stalls in early states.
4. **Reset cadence** – The engine periodically calls `reset_to_initial_state()`; adjust
   `max_iterations`/rate limits so resets do not starve deep states.

State metadata now flows into the preview endpoint/UI, so you can confirm each generated test case
shows the intended `message_type`, valid state, and transition before launching a full run.

## Practical Tips

- **Good Seeds Trump Raw Speed**: Invest time collecting authentic traffic captures; they produce deeper coverage than synthetic seeds.
- **Use Behaviors for “protocol glue”**: Sequence counters, derived lengths, and checksums should be behaviors, not custom mutators.
- **Layer Monitoring**: CPU/memory spikes plus target logs help distinguish true crashes from benign timeouts.
- **Split Long Campaigns**: Stop sessions periodically to snapshot findings, then restart with fresh mutator mixes.
- **Reproduce Outside the Lab**: When you hit a bug, replay it against staging systems or instrumented targets to confirm impact.

Keep this guide open while fuzzing—the workflow (instrument → model → run → observe → iterate) will quickly become second nature.

## Troubleshooting Proprietary Protocols

When a fuzzing campaign produces unexpected behavior, hangs, or a low execution rate, the root cause is often a misunderstanding between the fuzzer and the target about the protocol's rules. This is especially common with proprietary, stateful protocols. Here’s a detailed guide to troubleshooting the entire communication flow.

### 1. Understanding the Full Communication Lifecycle

A typical proprietary protocol session over TCP involves more than just sending a payload. It's a conversation with distinct phases. Mismanaging this lifecycle is the most common reason for a campaign failing.

**The phases are typically:**
1.  **Connection Establishment (TCP Handshake)**: The foundational TCP three-way handshake (SYN, SYN-ACK, ACK) must complete successfully. If the fuzzer attempts to send data before this is done, the target's OS will reject the packets.
2.  **Protocol Handshake/Initialization**: After the TCP connection is up, the application-layer protocol often performs its own handshake. This might involve exchanging version information, negotiating capabilities, or authenticating.
3.  **Data Exchange**: The core of the communication, where the fuzzer sends mutated payloads intended to trigger application logic.
4.  **Keep-Alives**: Some protocols require periodic "heartbeat" messages to keep the session alive. If these are not sent, the target may close the connection prematurely.
5.  **Graceful Teardown**: Sessions may need to be closed with a specific message sequence (e.g., `LOGOUT`, `FIN`). An abrupt TCP FIN or RST might be interpreted by the target as an error.

### 2. Is the Connection Per-Packet or Per-Session?

This is a critical distinction that dictates how the fuzzer must behave.

-   **Per-Session (Most Common)**: The fuzzer establishes **one** TCP connection and sends **many** test cases (mutated packets) over it. The connection remains open until the session is explicitly torn down or the target closes it. This is efficient but requires careful state management. If one test case puts the session into an invalid state, all subsequent tests in that connection will likely fail.

    *   **Troubleshooting Tip**: If you see a high rate of errors after the first few tests, it’s likely a state-invalidation issue. The fuzzer is sending a "poison" packet that makes the rest of the conversation moot. Use the `StatefulFuzzingSession` and define your protocol's `state_model` carefully. The engine’s automatic `reset_to_initial_state()` is designed to recover from this by closing the bad connection and starting fresh.

-   **Per-Packet (Less Common for TCP)**: The fuzzer establishes a **new** TCP connection for **every single test case**. It connects, sends one packet, receives a response, and disconnects. This is slow due to the overhead of the TCP handshake for every test, but it is stateless and robust. Each test case is perfectly isolated.

    *   **Troubleshooting Tip**: If your target seems to close the connection after every transaction, it might operate this way. You can force this behavior in the fuzzer by configuring the session to have a `max_iterations` of 1 and enabling a high reset rate, though this is inefficient. A better approach is to check if the protocol has a "close" or "end" flag in its header that you can model.

**Should it be configurable?**

Yes, ideally. While the fuzzer's core engine manages connections based on the state model, the ability to control this behavior is key. In this framework, this is implicitly managed:
-   By defining a `state_model` in your protocol plugin, you are telling the fuzzer it's a **per-session** protocol.
-   By *not* defining a `state_model`, the fuzzer treats each test more transactionally, though it may still reuse the connection for performance.

Forcing a per-packet behavior can be a powerful debugging tool. If a campaign works in per-packet mode but fails in per-session mode, you have confirmed the issue is related to state management within the session.

### 3. Diving into the TCP Handshake

While the fuzzer and the underlying OS handle the TCP handshake automatically, problems can still arise.

-   **Firewall/Network ACLs**: The most basic issue. Is the target host and port even reachable from where the fuzzer (or its agent) is running? Use `nc -zv <target_host> <target_port>` or `telnet <target_host> <target_port>` from the fuzzer's environment to confirm connectivity. A "Connection Refused" error means the port is closed or a firewall is blocking it. A timeout suggests the packets are being dropped.
-   **SYN Floods & Rate Limiting**: Some targets have built-in protection against rapid, repeated connection attempts. If you are running in a highly parallelized or per-packet mode, the target might temporarily ban the fuzzer's IP address. Check the target's logs for security warnings.
-   **TLS/SSL Handshake**: If the protocol is encrypted, the TCP handshake is followed by a TLS handshake. A failure here can be due to:
    -   Mismatched TLS versions (e.g., fuzzer offers TLS 1.3, server only supports 1.2).
    -   Invalid or untrusted certificates.
    -   Missing Client Certificate Authentication.
    Currently, the fuzzer does not have native support for TLS. You would need to use an external tool or wrapper (like `stunnel`) to handle the TLS layer.

### 4. Practical Troubleshooting Steps

When you suspect a protocol communication issue, follow this workflow:

1.  **Capture Ground Truth**: Before fuzzing, use `tcpdump` or Wireshark to capture a successful, manual interaction with the target using a known-good client.
    ```bash
    # On the target machine or a machine that can connect to it
    sudo tcpdump -i any -w successful_interaction.pcap host <target_host> and port <target_port>
    ```
    This `pcap` file is your "source of truth." Analyze it in Wireshark to understand every byte of the handshake, initialization, and data exchange.

2.  **Capture Fuzzer Traffic**: Run a short fuzzing campaign (e.g., 10-20 tests) and capture the traffic it generates.
    ```bash
    sudo tcpdump -i any -w fuzzer_interaction.pcap host <target_host> and port <target_port>
    ```

3.  **Compare the Captures**: Open both `pcap` files in Wireshark and compare them side-by-side. Look for the first point of divergence.
    -   Does the fuzzer's TCP handshake complete?
    -   Does the fuzzer send the exact same initial bytes as the known-good client? (Check your plugin's `seeds` and `behavior` blocks).
    -   How does the target respond differently? Does it send a TCP RST? An application-level error message? Or does it simply stop responding?

4.  **Use the One-Off Endpoint**: The `POST /api/tests/execute` endpoint is your best friend for debugging. It lets you send a single, precise payload and see the raw response.
    -   Send your protocol's `seeds` one by one. Do they all elicit the expected response?
    -   Manually craft a payload that mimics the first message from your `successful_interaction.pcap` and send it.
    -   If a finding is generated, use its `reproducer_data` with this endpoint to confirm it fails deterministically.

5.  **Review the Protocol Plugin**:
    -   Are `size_of` fields pointing to the correct block?
    -   Is `endian` (big/little) correct for all multi-byte integers?
    -   Are `behavior` blocks for sequence numbers or checksums configured correctly? Use the preview endpoint (`/api/plugins/{name}/preview`) to see how behaviors modify the payload before it's sent.
    -   For stateful protocols, are the `transitions` in your `state_model` accurate? Does the `expected_response` string correctly match what the server sends back?

By systematically analyzing the entire communication chain from the network up to the application layer, you can pinpoint the exact reason for the fuzzer's struggles and adjust your protocol plugin accordingly. For more details on plugin authoring, see the [Protocol Testing Guide](PROTOCOL_TESTING.md).
