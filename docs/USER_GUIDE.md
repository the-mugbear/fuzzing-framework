# Fuzzing Campaign Guide

**Last Updated: 2025-11-25**
...
For a complete guide on creating plugins, see the **[Plugin Authoring Guide](PLUGIN_AUTHORING_GUIDE.md)**.

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