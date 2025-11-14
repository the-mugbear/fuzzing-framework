import React from 'react';
import GuidePage from './GuidePage';

const ProtocolGuide: React.FC = () => {
  const content = (
    <>
      <p>Protocol plugins are the heart of the fuzzer. They teach the fuzzer how to speak the language of your target application.</p>

      <div className="callout">
        <p>This guide provides a high-level overview of protocol plugins. For a detailed, step-by-step guide on how to create your own, please see the <a href="/ui/guides/protocol-authoring">Comprehensive Protocol Authoring Guide</a>.</p>
      </div>

      <section>
        <h2>What is a Protocol Plugin?</h2>
        <p>A protocol plugin is a Python file that defines three key things:</p>
        <ul>
          <li><strong>Data Model</strong>: The structure of the protocol's messages.</li>
          <li><strong>State Model</strong>: The sequence of states the protocol goes through (e.g., authentication, data transfer).</li>
          <li><strong>Response Validator</strong>: A "logic oracle" to detect non-crash bugs.</li>
        </ul>
      </section>

      <section>
        <h2>Why are Plugins Important?</h2>
        <p>Without a plugin, the fuzzer would only be able to send random bytes to the target. This is unlikely to get past the initial parsing stages of the application. A well-defined plugin allows the fuzzer to:</p>
        <ul>
          <li>Generate valid, state-aware messages.</li>
          <li>Bypass initial validation and reach deeper, more interesting code paths.</li>
          <li>Understand the protocol's "grammar" and make intelligent mutations.</li>
        </ul>
      </section>

      <section>
        <h2>Next Steps</h2>
        <p>Ready to build your own plugin? Head over to the <a href="/ui/guides/protocol-authoring">Comprehensive Protocol Authoring Guide</a> to get started.</p>
      </section>
    </>
  );

  return <GuidePage title="Protocol Plugins: An Overview" content={content} />;
};

export default ProtocolGuide;
