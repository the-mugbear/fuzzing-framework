import React from 'react';
import GuidePage from './GuidePage';

const FuzzingGuide: React.FC = () => {
  const content = (
    <>
      <p>A practical reference to help you speak the same language as the fuzzer, structure campaigns intentionally, and triage findings quickly.</p>

      <section>
        <h2>Terminology Cheat Sheet</h2>
        <table>
          <thead>
            <tr><th>Term</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            <tr><td><strong>Seed</strong></td><td>A valid byte sequence that bootstraps the mutation engine. Stored in <code>data/corpus/seeds</code>.</td></tr>
            <tr><td><strong>Corpus</strong></td><td>All seeds plus interesting mutations and crash reproducers saved during a run.</td></tr>
            <tr><td><strong>Session</strong></td><td>A fuzzing campaign bound to a protocol, host, port, execution mode, and mutator selection.</td></tr>
            <tr><td><strong>Mutator</strong></td><td>Algorithm that transforms a seed (e.g., <code>bitflip</code>, <code>havoc</code>, <code>splice</code>). Choose them via <code>enabled_mutators</code>.</td></tr>
            <tr><td><strong>Behavior</strong></td><td>Declarative rule attached to a protocol block (e.g., “increment sequence”, “add constant”). Behaviors run before every send to keep deterministic fields valid.</td></tr>
            <tr><td><strong>Agent Mode</strong></td><td>Test cases are executed by remote agents that talk to the target and stream results back to the core.</td></tr>
            <tr><td><strong>One-off Test</strong></td><td>Single payload execution via <code>POST /api/tests/execute</code>—use it for quick validation or reproduction.</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Building an Effective Campaign</h2>
        <ol>
          <li>
            <h3>Instrument the Target</h3>
            <ul>
              <li>Run the sample target (<code>make run-target</code> or <code>docker compose up target</code>) and tail its logs.</li>
              <li>For custom binaries, expose structured logs or basic metrics so you spot crashes immediately.</li>
            </ul>
          </li>
          <li>
            <h3>Author/Review the Protocol Plugin</h3>
            <ul>
              <li>Define immutable headers (<code>mutable: false</code>) so signatures stay intact.</li>
              <li>Model state transitions and supply at least three realistic seeds.</li>
              <li>Add <code>behavior</code> blocks for deterministic fields:
                <pre>{`{
    "name": "sequence",
    "type": "uint16",
    "behavior": {"operation": "increment", "initial": 0, "step": 1}
}
{
    "name": "checksum",
    "type": "uint8",
    "behavior": {"operation": "add_constant", "value": 0x55}
}`}</pre>
              </li>
            </ul>
          </li>
          <li>
            <h3>Choose Execution & Mutators</h3>
            <ul>
              <li>Core mode is simplest; agent mode lets you forward traffic via remote workers.</li>
              <li>Use <code>/api/mutators</code> to list options and pass <code>enabled_mutators</code> when creating the session.</li>
            </ul>
          </li>
          <li>
            <h3>Run & Observe</h3>
            <ul>
              <li>Poll <code>/api/sessions/&lt;id&gt;/stats</code> or watch the UI dashboard.</li>
              <li>Monitor target logs, <code>logs/core-api.log</code>, and agent logs at the same time.</li>
            </ul>
          </li>
          <li>
            <h3>Triage & Iterate</h3>
            <ul>
              <li>Re-run interesting seeds via the one-off endpoint or netcat.</li>
              <li>Promote failing inputs to the seed corpus for future runs.</li>
            </ul>
          </li>
        </ol>
      </section>

      <section>
        <h2>Practical Tips</h2>
        <div className="callout">
          <ul>
            <li><strong>Good Seeds Trump Raw Speed:</strong> Authentic traffic captures produce deeper coverage.</li>
            <li><strong>Behaviors for Protocol Glue:</strong> Sequence counters, derived lengths, and checksums belong in behaviors.</li>
            <li><strong>Layer Monitoring:</strong> Combine target logs with CPU/memory metrics.</li>
            <li><strong>Split Campaigns:</strong> Stop sessions periodically to snapshot findings.</li>
            <li><strong>Reproduce Outside the Lab:</strong> Replay crashes against staging systems to confirm impact.</li>
          </ul>
        </div>
      </section>

      <section>
        <h2>Troubleshooting Proprietary Protocols</h2>
        <div className="callout">
          <p>When a fuzzing campaign produces unexpected behavior, hangs, or a low execution rate, the root cause is often a misunderstanding between the fuzzer and the target about the protocol's rules. This is especially common with proprietary, stateful protocols. Here’s a detailed guide to troubleshooting the entire communication flow.</p>
        </div>

        <h3>1. Understanding the Full Communication Lifecycle</h3>
        <p>A typical proprietary protocol session over TCP involves more than just sending a payload. It's a conversation with distinct phases. Mismanaging this lifecycle is the most common reason for a campaign failing.</p>
        <ol>
          <li><strong>Connection Establishment (TCP Handshake)</strong>: The foundational TCP three-way handshake (SYN, SYN-ACK, ACK) must complete successfully.</li>
          <li><strong>Protocol Handshake/Initialization</strong>: After the TCP connection is up, the application-layer protocol often performs its own handshake (e.g., exchanging version information).</li>
          <li><strong>Data Exchange</strong>: The core of the communication, where the fuzzer sends mutated payloads.</li>
          <li><strong>Keep-Alives</strong>: Some protocols require periodic "heartbeat" messages to keep the session alive.</li>
          <li><strong>Graceful Teardown</strong>: Sessions may need to be closed with a specific message sequence (e.g., <code>LOGOUT</code>).</li>
        </ol>

        <h3>2. Is the Connection Per-Packet or Per-Session?</h3>
        <ul>
          <li><strong>Per-Session (Most Common)</strong>: The fuzzer establishes <strong>one</strong> TCP connection and sends <strong>many</strong> test cases over it. This is efficient but requires careful state management. If one test case invalidates the state, all subsequent tests will likely fail.</li>
          <li><strong>Per-Packet (Less Common for TCP)</strong>: The fuzzer establishes a <strong>new</strong> TCP connection for <strong>every single test case</strong>. This is slow but robust, as each test is isolated.</li>
        </ul>
        <p><strong>Should it be configurable?</strong> Yes. In this framework, this is implicitly managed by your protocol plugin. Defining a <code>state_model</code> tells the fuzzer it's a per-session protocol. Not defining one makes it behave more transactionally.</p>

        <h3>3. TCP Session Lifetime and Rate Considerations</h3>
        <p>The test case delivery rate does <strong>not</strong> directly determine when a TCP handshake occurs. A new handshake is only performed when a new connection is established. The TCP session is designed to be long-lived and is only terminated when the session ends, the target closes the connection, a state invalidation occurs, a stateful reset is triggered, or a network error occurs.</p>

        <h3>4. Practical Troubleshooting Steps</h3>
        <ol>
          <li><strong>Capture Ground Truth</strong>: Before fuzzing, use <code>tcpdump</code> or Wireshark to capture a successful, manual interaction with the target using a known-good client. This is your "source of truth."</li>
          <li><strong>Capture Fuzzer Traffic</strong>: Run a short fuzzing campaign and capture the traffic it generates.</li>
          <li><strong>Compare the Captures</strong>: Open both captures in Wireshark and compare them side-by-side. Look for the first point of divergence. Does the fuzzer's handshake complete? Is the initialization sequence correct?</li>
          <li><strong>Use the One-Off Endpoint</strong>: The <code>POST /api/tests/execute</code> endpoint is your best friend for debugging. Send your seeds one by one to see if they elicit the expected response.</li>
          <li><strong>Review the Protocol Plugin</strong>: Check your <code>size_of</code> fields, <code>endian</code> settings, and <code>behavior</code> blocks. Use the Plugin Debugger in the UI to preview mutations.</li>
        </ol>
        <p>By systematically analyzing the entire communication chain, you can pinpoint the exact reason for the fuzzer's struggles. For more details, see the <a href="/core/ui/guides/protocol-authoring-guide.html">Comprehensive Protocol Authoring Guide</a>.</p>
      </section>
    </>
  );

  return <GuidePage title="Fuzzing Guide" content={content} />;
};

export default FuzzingGuide;
