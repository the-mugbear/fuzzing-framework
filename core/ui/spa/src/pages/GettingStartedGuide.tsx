import React from 'react';
import GuidePage from './GuidePage';

const GettingStartedGuide: React.FC = () => {
  const content = (
    <>
      <p className="callout">Welcome to the fuzzer! This guide will walk you through the core concepts and your first fuzzing session. The goal of this tool is to automatically discover bugs in network services by sending them unexpected, malformed, or invalid data.</p>

      <section>
        <h2>Quick Launch Checklist: Your First Session</h2>
        <p>Follow these steps to get a feel for the basic workflow. We'll use the provided sample target and protocol.</p>
        <ol>
          <li><strong>Start the Target</strong>: Run <code>make run-target</code> (or <code>docker-compose up target</code>). This launches a simple TCP server that has some intentional bugs. This is the application we will be fuzzing.</li>
          <li><strong>Start the Fuzzer Core</strong>: In a new terminal, run <code>make run-core</code> (or <code>docker-compose up core</code>). This starts the main fuzzer application, including the web UI and the API. Wait for the log message "API listening" before proceeding.</li>
          <li><strong>Configure the Session</strong>: Open the web UI (usually at <a href="http://localhost:8000">http://localhost:8000</a>).
            <ul>
              <li>Select the <strong>simple_tcp</strong> plugin from the dropdown. This plugin tells the fuzzer how to talk to our sample target.</li>
              <li>Set the target to <code>target:9999</code> (if using Docker) or <code>localhost:9999</code> (if running locally).</li>
              <li>Click <strong>Create Session</strong>.</li>
            </ul>
          </li>
          <li><strong>Start Fuzzing</strong>: Find your new session in the "Sessions" list and click the "Start" button. You should see the "System Status" counters on the dashboard start to climb as the fuzzer sends test cases to the target.</li>
          <li><strong>Observe the Target</strong>: Watch the logs of the target service (<code>docker-compose logs -f target</code>). You will see the mutated data that the fuzzer is sending, and you may see the target crash and restart.</li>
        </ol>
      </section>

      <section>
        <h2>Session Workflow Explained</h2>
        <ul>
          <li><strong>Choose a plugin</strong>: This is the most important step. The plugin is the blueprint for the protocol. A good plugin is essential for effective fuzzing.</li>
          <li><strong>Set Rate & Timeout</strong>: The rate limit controls how many test cases are sent per second. For initial debugging of a new protocol, a low rate (5-50) is helpful to see what's happening. For maximum performance, set it to 0 to remove any throttling. The timeout is how long the fuzzer will wait for a response before marking a test case as a "hang."</li>
          <li><strong>Select mutators</strong>: Mutators are the algorithms that generate the malformed data. It's best to keep the defaults while prototyping. The "structure-aware" mutator is special: it uses your protocol definition to make intelligent changes. Only disable it if your data model is incomplete or you want to send purely random data.</li>
          <li><strong>Start/Stop</strong>: Sessions can be paused and resumed at any time. This is useful for analyzing findings without stopping the entire campaign.</li>
        </ul>
      </section>

      <section>
        <h2>Reading the Dashboard</h2>
        <ul>
          <li><strong>Total Tests</strong>: The total number of mutations sent to the target. A healthy session should see this number constantly increasing.</li>
          <li><strong>Crashes</strong>: The fuzzer detected that the target process terminated unexpectedly after a test case. These are high-priority findings.</li>
          <li><strong>Hangs</strong>: The target did not respond within the configured timeout. This could indicate a denial-of-service vulnerability.</li>
          <li><strong>Anomalies</strong>: The `validate_response` function in your protocol plugin (your "logic oracle") returned `False` or raised an exception. This means you've found a bug that isn't a crash or a hang.</li>
        </ul>
      </section>

      <section>
        <h2>Troubleshooting Common Issues</h2>
        <table className="terminology-table">
          <thead>
            <tr><th>Symptom</th><th>What to Try</th></tr>
          </thead>
          <tbody>
            <tr><td>No sessions are listed after creating one.</td><td>Click the "Reload Plugins" button in the UI. Check the `core` service logs for Python errors, which usually indicate a syntax error in a plugin file.</td></tr>
            <tr><td>All tests result in "connection refused."</td><td>Verify the target is running and reachable from the fuzzer. If using Docker, the core service must be on the same Docker network as the target. Use the service name (e.g., `target`) instead of `localhost`.</td></tr>
            <tr><td>The UI is stuck on "Loading protocols..."</td><td>Check that the API is running and accessible from your browser. Look for CORS (Cross-Origin Resource Sharing) errors in your browser's developer console.</td></tr>
            <tr><td>Mutations all look identical to the seeds.</td><td>Ensure that at least one block in your protocol's `data_model` is marked as `mutable: True`. Also, make sure your `seeds` list is not empty.</td></tr>
            <tr><td>The fuzzer isn't finding any crashes.</td><td>This is normal at first! Fuzzing takes time. Ensure your protocol model is accurate enough to get past the initial validation. Try adding more diverse seeds. Check the target's logs to see if it's rejecting all the inputs for a specific reason.</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Core Terminology</h2>
        <table className="terminology-table">
          <thead>
            <tr><th>Seed</th><td>A known-good message that the mutator uses as a starting point. High-quality seeds are critical for deep fuzzing.</td></tr>
            <tr><th>Mutation Strategy</th><td>An algorithm for corrupting a seed (e.g., bit flip, byte flip, havoc, splice). Each is designed to trigger different kinds of bugs.</td></tr>
            <tr><th>Behavior</th><td>A rule applied to a message <em>before</em> it is sent, used for deterministic fields like sequence numbers or fixed offsets. Lengths and checksums are handled by size fields and checksum blocks.</td></tr>
          </thead>
          <tbody>
            <tr><th>State Model</th><td>A map of the protocol's states and the messages that transition between them. Essential for fuzzing stateful protocols.</td></tr>
            <tr><th>Oracle</th><td>A mechanism for detecting bugs. The fuzzer has built-in oracles for crashes and hangs. The `validate_response` function is a user-defined "logic oracle."</td></tr>
            <tr><th>Corpus</th><td>The collection of all seeds, plus any interesting inputs found by the fuzzer during a campaign. The fuzzer uses the corpus to generate new mutations.</td></tr>
            <tr><th>Finding</th><td>A persisted record of a test case that resulted in a crash, hang, or anomaly. Findings contain the exact input needed to reproduce the bug.</td></tr>
          </tbody>
        </table>
      </section>

      <section>
        <h2>Practice Ideas to Deepen Your Understanding</h2>
        <ul>
          <li><strong>Use the Plugin Debugger</strong>: This is the most powerful tool for understanding how the fuzzer sees your protocol. Inspect how seeds are parsed and how different mutations affect the output.</li>
          <li><strong>Upload a Custom Seed</strong>: Create a new, valid message for the `simple_tcp` protocol and upload it via the UI. Confirm that it appears in the Mutation previews. This teaches you how to expand the fuzzer's knowledge.</li>
          <li><strong>Replay a Finding</strong>: Once the fuzzer finds a crash, use the "Replay" button to send the exact same payload again. Watch the target's logs to see the crash happen in real-time.</li>
          <li><strong>Create a New Plugin</strong>: The best way to learn is by doing. Try creating a simple plugin for a well-known protocol like HTTP or Redis. See the <a href="/ui/guides/protocol-authoring">Comprehensive Protocol Authoring Guide</a>.</li>
        </ul>
      </section>
    </>
  );

  return <GuidePage title="Getting Started: A Guided Tour" content={content} />;
};

export default GettingStartedGuide;
