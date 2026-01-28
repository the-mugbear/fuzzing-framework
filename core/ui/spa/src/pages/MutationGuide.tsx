import React from 'react';
import GuidePage from './GuidePage';

const MutationGuide: React.FC = () => {
  const content = (
    <>
      <p className="callout">Mutation strategies are the engines of discovery in fuzzing. They are the algorithms that take a valid input (a "seed") and corrupt it in specific ways to create a test case. This guide explains each strategy, what it does, and what kinds of bugs it's designed to find.</p>

      <section>
        <h2>Two Families of Mutation</h2>
        <p>The fuzzer uses two main types of mutation strategies that work together:</p>
        <ul>
          <li><strong>Structure-Aware Mutations</strong>: These are "smart" mutations that use your protocol's `data_model`. They make changes that are likely to be accepted by the target's parser, allowing the fuzzer to test deeper application logic.</li>
          <li><strong>Byte-Level Mutations</strong>: These are "dumb" mutations that operate directly on the raw bytes of a seed. They are excellent for finding memory corruption bugs, parsing errors, and integer overflows.</li>
        </ul>
        <p>A fuzzing session uses a mix of both, with the ratio controlled by the "Structure-Aware Weight" setting.</p>
      </section>

      <section>
        <h2>Strategy Details</h2>
        <div className="strategy-grid">
          <div className="strategy-card structure">
            <div className="strategy-badge structure">Structure-Aware</div>
            <h3>How it works:</h3>
            <p>This strategy leverages the `data_model` you defined in your protocol plugin. It intelligently modifies fields, knowing their type, size, and purpose. For example, it will replace a `string` field with another string, or an `integer` field with another integer. It works alongside behaviors for deterministic fields, while size fields and checksum blocks keep derived values consistent.</p>
            <h3>Good for finding:</h3>
            <p>Logic bugs, authentication bypasses, and vulnerabilities in the application's business logic. It's the key to getting past the initial parsing and into the heart of the application.</p>
            <div className="strategy-example"><pre>{`# The fuzzer adds data to the payload and automatically updates the length field.
Before: len=0x5 | payload="HELLO"
After : len=0xA | payload="HELLO, WORLD"`}</pre></div>
          </div>
          <div className="strategy-card byte">
            <div className="strategy-badge byte">Bit Flip</div>
            <h3>How it works:</h3>
            <p>Toggles one or more random bits in the data (i.e., changes a 0 to a 1, or a 1 to a 0). This is a very subtle form of corruption.</p>
            <h3>Good for finding:</h3>
            <p>Bugs caused by unexpected flag combinations, subtle parsing errors, and vulnerabilities in custom binary encodings.</p>
            <div className="strategy-example"><pre>{`# The third bit of the character 'A' (01000001) is flipped.
'A' (0x41) -> 'C' (0x43)`}</pre></div>
          </div>
          <div className="strategy-card byte">
            <div className="strategy-badge byte">Byte Flip</div>
            <h3>How it works:</h3>
            <p>Replaces one or more bytes with completely random values. This is a more aggressive form of corruption than a bit flip.</p>
            <h3>Good for finding:</h3>
            <p>Classic buffer overflows, parsing errors, and crashes when handling invalid opcodes or magic headers.</p>
            <div className="strategy-example"><pre>{`# The second byte of the magic header "STCP" is replaced with a random byte.
"STCP" -> "S\x9A\x43\x50"`}</pre></div>
          </div>
          <div className="strategy-card byte">
            <div className="strategy-badge byte">Arithmetic</div>
            <h3>How it works:</h3>
            <p>Finds integer-like fields (2, 4, or 8 bytes) and adds or subtracts small integer values from them. It treats the bytes as if they were a number.</p>
            <h3>Good for finding:</h3>
            <p>Integer overflow and underflow bugs, which can lead to buffer overflows or logic errors. For example, adding 1 to a length field of `0xFFFF` might wrap it around to `0x0000`, causing the application to miscalculate a buffer size.</p>
            <div className="strategy-example"><pre>{`# Adds a value to a 2-byte sequence number.
Sequence: 0x001A -> 0x011A`}</pre></div>
          </div>
          <div className="strategy-card byte">
            <div className="strategy-badge byte">Interesting Values</div>
            <h3>How it works:</h3>
            <p>Replaces integer fields with a list of "interesting" boundary values, such as 0, -1, `MAX_INT`, `MIN_INT`, etc.</p>
            <h3>Good for finding:</h3>
            <p>Edge-case bugs, division-by-zero errors, and integer overflows. It's a more targeted way of finding the same kinds of bugs as the Arithmetic strategy.</p>
            <div className="strategy-example"><pre>{`# Replaces a 4-byte length field with common boundary values.
Length: 0x0000000A -> 0xFFFFFFFF or 0x80000000`}</pre></div>
          </div>
          <div className="strategy-card byte">
            <div className="strategy-badge byte">Havoc</div>
            <h3>How it works:</h3>
            <p>This is a "chaos" strategy. It applies a random sequence of other byte-level mutations (bit flips, byte flips, inserts, deletes, shuffles) to the input. It's designed to create highly corrupted and unexpected inputs.</p>
            <h3>Good for finding:</h3>
            <p>Complex parsing bugs and crashes in fragile, poorly-written code that can't handle unexpected data.</p>
            <div className="strategy-example"><pre>{`# A random chain of operations is applied to the input.
ops = [insert 8 bytes, delete 4 bytes, shuffle 16 bytes]`}</pre></div>
          </div>
          <div className="strategy-card byte">
            <div className="strategy-badge byte">Splice</div>
            <h3>How it works:</h3>
            <p>Takes two different seeds from the corpus and combines them, for example by taking the header from one and the payload from another. This can create novel and interesting test cases that are still partially valid.</p>
            <h3>Good for finding:</h3>
            <p>State machine confusion bugs, logic errors, and vulnerabilities where the application makes incorrect assumptions based on a combination of message types.</p>
            <div className="strategy-example"><pre>{`# Combines an AUTH message with a DATA message.
Seed 1: [AUTH][user=admin]
Seed 2: [DATA][query=SELECT *]
Result: [AUTH][query=SELECT *]`}</pre></div>
          </div>
        </div>
      </section>
    </>
  );

  return <GuidePage title="A Deep Dive into Mutation Strategies" content={content} />;
};

export default MutationGuide;
