# Fuzzing Campaign Guide

This guide provides a practical framework for running an effective fuzzing campaign. It covers core concepts, campaign strategy, and how to troubleshoot common issues when dealing with complex network protocols.

## Core Fuzzing Concepts

To use the fuzzer effectively, it's helpful to understand its terminology.

| Term | Meaning |
| --- | --- |
| **Seed** | A valid sample message for your protocol. Seeds are the starting points for mutation. A good set of seeds is critical for a successful campaign. |
| **Corpus** | The entire collection of test cases the fuzzer knows about. It includes the initial seeds and any new, interesting inputs (like crash-causing mutations) discovered during a session. |
| **Session** | A single fuzzing campaign against a specific target, using a chosen protocol plugin and configuration. |
| **Mutator** | An algorithm that alters a seed to create a new test case (e.g., `bitflip`, `havoc`). The fuzzer combines different mutators to create a diverse range of inputs. |
| **Behavior** | A rule in a protocol plugin that automatically updates a field before a message is sent. This is essential for "protocol glue" like sequence numbers or checksums. |
| **Finding** | A test case that caused an interesting and reproducible event, such as a crash, a hang, or a logical error detected by a validator. |

## The Fuzzing Workflow: A Strategic Approach

A successful fuzzing campaign is an iterative process of learning about your target and refining your approach. Follow this workflow for best results.

### 1. Preparation & Reconnaissance

Before you start fuzzing, you need to understand your target.

*   **Gather Ground Truth**: Use a real client to interact with your target application and capture the traffic using a tool like `tcpdump` or Wireshark. This captured traffic (`.pcap` file) is your "source of truth." It provides you with high-quality seeds and a clear understanding of the protocol's handshake and message flow.
*   **Instrument the Target**: If possible, run the target application with logging enabled. Being able to see how the target reacts to each test case is invaluable for debugging. For custom binaries, consider adding structured logging.

### 2. Modeling the Protocol

This is the most important step. You need to teach the fuzzer the language of your target protocol by creating a **protocol plugin**.

*   **Start with the Basics**: Create a new plugin file in `core/plugins/`. Define the `data_model` with the basic structure of your protocol's messages. Use your captured traffic to ensure fields, types, and sizes are correct.
*   **Protect Static Fields**: Mark any fields that must not change (like magic headers) as `mutable: False`. This prevents the fuzzer from generating a flood of obviously invalid messages.
*   **Define Behaviors**: For any fields that change in a predictable way (sequence numbers, timestamps, length fields, checksums), define them in the `data_model` using `is_size_field` or a `behavior` block. This is critical for maintaining a valid session with the target.
*   **Model the State**: If your protocol is stateful (e.g., requires a login), define the `state_model`. This tells the fuzzer the correct sequence of messages, allowing it to test deep application logic.

For a complete guide on creating plugins, see the **[Protocol Testing Guide](PROTOCOL_TESTING.md)**.

### 3. The Initial Fuzzing Session

Your first session is about validation and baseline testing.

*   **Choose Your Mutators**: Start with a broad mix of mutators. A good starting point is a `hybrid` mode that uses both `bitflip` and `havoc` to generate a mix of subtle and aggressive mutations.
*   **Run and Observe**: Start the session and watch the dashboard and your target's logs. Are test cases being executed? Are there any immediate errors? A high rate of initial errors often points to a problem in the protocol model.
*   **Analyze Early Findings**: If you get crashes right away, that's great! Use the one-off execution endpoint (`/api/tests/execute`) to replay the crash-causing input and confirm that the bug is reproducible.

### 4. Iteration and Refinement

Fuzzing is a cycle of discovery and improvement.

*   **Promote Interesting Inputs**: If you find a test case that explores a new part of the application or triggers a non-crashing but interesting behavior, add it to your plugin's `seeds`. This will guide the fuzzer to explore that area more deeply in future sessions.
*   **Refine Your Protocol Model**: As you learn more about the target from its responses and behavior, update your protocol plugin. You may discover new fields, states, or behaviors that you didn't know about initially.
*   **Adjust Your Strategy**: If you're not finding bugs, try changing your approach. Use different mutators. If the protocol is stateful, try fuzzing different state transitions more aggressively.

## Troubleshooting Common Problems

When a fuzzing campaign isn't working, it's usually due to a misunderstanding between the fuzzer and the target about the protocol.

### Problem: No tests are being executed, or all tests fail immediately.

This almost always indicates a problem with the initial connection or handshake.

1.  **Check Basic Connectivity**: From the fuzzer's environment, can you connect to the target? Use `nc -zv <target_host> <target_port>` to verify. A "Connection Refused" error means the port is closed or a firewall is blocking it.
2.  **Compare with Ground Truth**: Use `tcpdump` to capture the traffic from your fuzzer and compare it to the traffic from a known-good client. Do the first few packets match exactly? If not, your protocol plugin's initial seeds or behaviors are incorrect.
3.  **Per-Session vs. Per-Packet**: Most TCP protocols are **per-session**, meaning one connection is used for many messages. If your target closes the connection after every message, it might be a **per-packet** protocol. This is less common but important to identify. If your session fails after the first few tests, it's likely a state-invalidation issue—the fuzzer is sending a "poison" packet that ruins the rest of the session. This is a strong indicator that you need to improve your `state_model`.

### Problem: The fuzzer isn't finding any bugs.

*   **Your Seeds Are Too Simple**: The fuzzer can only mutate the data you give it. If your seeds only cover a small part of the protocol's functionality, the fuzzer will be limited. Add more diverse and complex seeds based on real-world traffic.
*   **Your Protocol Model is Incomplete**: If you haven't correctly modeled lengths, checksums, or state transitions, the target may be silently rejecting most of your test cases at an early validation stage, and the fuzzer never reaches the interesting code.
*   **The Target is Actually Robust!**: It's possible! But it's more likely that you need to refine your approach to get deeper into the application.

By following this strategic workflow and systematically troubleshooting issues, you can dramatically increase the effectiveness of your fuzzing campaigns.