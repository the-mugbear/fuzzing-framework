# Fuzzing Campaign Guide

**Last Updated: 2026-01-31**

This guide provides a strategic framework for running effective fuzzing campaigns. Following these steps will help you move from initial setup to discovering and analyzing vulnerabilities.

## The Fuzzing Workflow: A Strategic Overview

A successful fuzzing campaign is an iterative process, not a one-shot effort. The workflow generally follows these stages:

1.  **Protocol Modeling**: Create a high-fidelity model of the protocol you're targeting.
2.  **Target Setup**: Configure the target application for fuzzing, ensuring you have adequate monitoring and logging.
3.  **Initial Session**: Run a baseline fuzzing session to validate your setup and gather initial data.
4.  **Iteration & Refinement**: Use the results from your initial session to refine your protocol model, seeds, and fuzzing strategy.
5.  **Analysis**: Triage and analyze findings to identify root causes and assess their impact.

## 1. Protocol Modeling & Seed Selection

The quality of your protocol plugin is the single most important factor in a successful fuzzing campaign.

*   **Start with the Spec**: Begin with the official protocol specification, if one exists.
*   **Capture Real Traffic**: Use `tcpdump` or Wireshark to capture traffic between a legitimate client and the target. This is your ground truth. Identify message types, session establishment, and teardown sequences.
*   **Create High-Quality Seeds**: Your initial seeds should be a collection of valid messages that cover as much of the protocol's functionality as possible. A diverse seed corpus is essential for guiding the fuzzer to interesting parts of the target application.

For a complete guide on creating plugins, see the **[Protocol Plugin Guide](PROTOCOL_PLUGIN_GUIDE.md)**.

## 2. Fuzzing Stateful and Multi-Protocol Targets

Modern protocols are often more complex than a simple request-response pattern. They may require an authentication handshake, a capabilities exchange, or other setup steps before the core commands can be fuzzed. This fuzzer handles these scenarios using **Orchestrated Sessions**.

### What is an Orchestrated Session?

An Orchestrated Session executes a series of protocol stages in sequence. A typical setup might be:
1.  **`bootstrap`**: Performs a handshake, logs in, and retrieves a session token.
2.  **`fuzz_target`**: Uses the session token from the `bootstrap` stage to fuzz the core application logic.
3.  **`teardown`**: Gracefully logs out or closes the session.

This allows the fuzzer to work with complex, stateful targets that would otherwise reject fuzzing traffic.

### Keeping Sessions Alive with Heartbeats

Long-running stateful sessions can be terminated by firewalls or the target itself due to inactivity. To prevent this, you can configure a **heartbeat**. The fuzzer will send a periodic keep-alive message in the background, ensuring the connection remains open and the session state is preserved.

If a connection is dropped, the heartbeat mechanism can even trigger a **reconnect**, automatically re-running the `bootstrap` stage to establish a new, valid session before resuming fuzzing.

For a detailed guide on setting up these advanced features, see the **[Orchestrated Sessions Guide](ORCHESTRATED_SESSIONS_GUIDE.md)**.

## 3. The Initial Fuzzing Session

Your first session is about validation and baseline testing.

*   **Choose Your Mutators**: Start with a broad mix of mutators. A good starting point is a `hybrid` mode that uses both `bitflip` and `havoc`.
*   **Run and Observe**: Start the session and watch the dashboard and your target's logs. Are test cases being executed? Are there any immediate errors?
*   **Analyze Early Findings**: If you get crashes right away, use the one-off execution endpoint (`/api/tests/execute`) to replay the crash-causing input and confirm that the bug is reproducible.

## 4. Iteration and Refinement

Fuzzing is a cycle of discovery and improvement.

*   **Promote Interesting Inputs**: If you find a test case that explores a new part of the application or triggers a non-crashing but interesting behavior, add it to your plugin's `seeds`.
*   **Refine Your Protocol Model**: As you learn more about the target, update your protocol plugin. You may discover new fields, states, or behaviors.
*   **Adjust Your Strategy**: If you're not finding bugs, try changing your approach. Use different mutators. If the protocol is stateful, try fuzzing different state transitions more aggressively.

## Troubleshooting Common Problems

### Problem: No tests are being executed, or all tests fail immediately.

This almost always indicates a problem with the initial connection or protocol model.

1.  **Check Basic Connectivity**: Use `nc -zv <target_host> <target_port>` to verify the port is open.
2.  **Compare with Ground Truth**: Use `tcpdump` to compare the fuzzer's traffic to traffic from a known-good client. Do the first few packets match exactly?
3.  **Per-Session vs. Per-Packet**: Most TCP protocols are **per-session** (one connection for many messages). If your target closes the connection after every message, it might be a **per-packet** protocol. This requires a different approach where a persistent connection is not used.

### Problem: Orchestrated Session fails at the `bootstrap` stage.

This means your initial handshake or login is failing.
1.  **Check the `core` logs**: The logs will contain detailed error messages from the `StageRunner`. Look for validation errors or timeouts.
2.  **Isolate the `bootstrap` logic**: The `bootstrap` stage runs before any fuzzing begins. The messages it sends should be 100% valid. Manually send the *exact same* byte sequence defined in your plugin's `bootstrap` stage to the target and analyze the response. Does it match what the plugin expects?
3.  **Check `exports`**: If your `bootstrap` stage is supposed to `export` a value (like a session token) for the next stage, ensure the response from the server actually contains that value and your parsing logic is correct.

### Problem: The fuzzer isn't finding any bugs.

*   **Your Seeds Are Too Simple**: The fuzzer can only mutate the data you give it. Add more diverse and complex seeds based on real-world traffic.
*   **Your Protocol Model is Incomplete**: If you haven't correctly modeled lengths, checksums, or state transitions, the target may be silently rejecting most of your test cases at an early validation stage.
*   **The Target is Actually Robust!**: It's possible! But it's more likely that you need to refine your approach to get deeper into the application.

By following this strategic workflow and systematically troubleshooting issues, you can dramatically increase the effectiveness of your fuzzing campaigns.