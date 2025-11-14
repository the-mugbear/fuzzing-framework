# A Blueprint for a Portable and Extensible Proprietary Protocol Fuzzing Framework


## Executive Summary: A Blueprint for a Next-Generation Protocol Fuzzer

**The Problem:** Proprietary network protocols, prevalent in critical domains such as Industrial Control Systems (ICS), IoT devices, and specialized telecommunications or financial software, represent a significant and expanding gap in automated security testing. The closed-source, "black-box" nature of these protocols renders them opaque and largely impervious to traditional, specification-based fuzzing techniques, which work best when protocol semantics are known.
**The Challenge:** A solution designed to effectively fuzz proprietary protocols must overcome a triumvirate of core, interacting challenges:
* **The Syntax Problem:** The fuzzer must comprehend and generate inputs for a protocol's message structure without access to a formal specification.1
* **The State Problem:** The fuzzer must successfully navigate the protocol's state machine, which is often stateful, and correctly handle dynamic fields, session identifiers, and integrity checks that change with each transmission.
* **The Oracle Problem:** The fuzzer must intelligently detect "adverse effects" and logical failures, as many protocol bugs do not result in an obvious, simple crash.
**The Solution:** This report provides the architectural blueprint for a hybrid, stateful, and extensible fuzzing framework. This design is built upon a decoupled, plugin-driven core to ensure portability and simplicity. It leverages automated Protocol Reverse Engineering (PRE) and taint analysis to dynamically learn protocol syntax and state. Finally, it employs a multi-faceted "Intelligent Oracle" system to detect a wide spectrum of non-crash failures, from resource exhaustion to application-specific behavioral anomalies.

## I. A Modern Architectural Framework for Protocol Fuzzing

The foundational design of the fuzzer must directly address the user's core requirements: portability to "reduce deployment pains" and extensibility to "make it simple to alter." These are architectural, not just functional, challenges.

### A. Portability and Deployment: A Decoupled, Containerized Architecture

"Deployment pains" in fuzzing are typically twofold: first, the fuzzer itself has a complex set of dependencies (e.g., specific Python versions, analysis libraries, instrumentation tools); second, the target application has its own, often legacy, environment (e.g., an outdated operating system, specific runtimes).
The proposed solution is a decoupled, microservices-inspired architecture that uses containerization as its core portability primitive.
* **The Fuzzer Core:** The main fuzzing engine—which houses the state management, test case generation, and user interface—will be fully containerized using Docker.2 This approach leverages container isolation to package the fuzzer and all its dependencies into a single, self-contained artifact. This guarantees a consistent, isolated runtime environment 2 and ensures the fuzzer runs identically on any host that supports Docker, eliminating the fuzzer's own dependency issues.
* **The Target Agent:** A minimal, lightweight agent, acting as a "courier", will be the only component deployed on the target host (or a host with network access to the target). This agent's responsibilities are minimal: 1) receive fuzzed inputs from the Core, 2) deliver them to the target (e.g., by writing to a network socket), and 3) report monitoring data (CPU, memory, crash logs) back to the Core.
This decoupled design is the key to portability. Containerization serves as a "bridge", allowing a modern, containerized fuzzer to test a non-containerized, legacy target. This architecture solves the "it works on my machine" problem for the fuzzer itself.

### B. Extensibility: A Plugin-Driven Core for "Simple Alteration"

To "make it simple to alter," the framework must allow users to add new, unknown protocols without rewriting the fuzzer's core. An analysis of existing frameworks provides a path forward:
**Existing Models:** The Peach Fuzzer employs an excellent separation of concerns with its XML-based DataModel (the "what") and StateModel (the "when"). However, its XML implementation is notoriously complex and "poorly documented". Conversely, frameworks like Boofuzz (the successor to Sulley) use programmatic Python scripts to define request "blocks" and link them in a "session" graph. This is far more flexible and intuitive for developers.
**Proposed Hybrid Model:** The proposed solution is a hybrid model that combines Peach's conceptual clarity with Boofuzz's programmatic flexibility. The fuzzer will be architected with an "inverse dependency" plugin model. The core will function as a "Kernel Management Module" that simply loads protocol definitions from an external directory.
A new protocol will be defined in a single, self-contained Python script. This script will programmatically define two key objects:
* **data_model:** A series of block definitions, similar to Sulley's, defining fields, types, and default values.
* **state_model:** A graph-based definition of states and transitions, conceptually similar to Peach's StateModel.
To add a new protocol, the user only needs to create this new Python file and place it in the "protocols" directory. They do not touch the core fuzzer code. This design, which aligns with best practices for extensible framework design, directly meets the "simple to alter" requirement. This architecture also opens a path for future automation: writing this Python definition script is a task that can be significantly assisted by Large Language Models (LLMs), which could generate a draft script from a sample network capture.

### C. Durable Persistence for Fuzzing Artifacts

Effective fuzzing campaigns generate a vast amount of data, including test cases, execution results, and potential crash artifacts. To enable comprehensive post-mortem analysis, correlation across multiple fuzzing runs, and the ability to replay specific test sequences, a robust and durable persistence layer is essential.

The framework incorporates a dedicated persistence mechanism to store:

*   **Execution History:** Detailed records of each test case sent, the target's response, and the outcome (pass, crash, hang, anomaly). This history is crucial for understanding the fuzzer's exploration path and for debugging target behavior.
*   **Fuzzing Artifacts:** Crash reports, unique findings, and other relevant data generated during a campaign.
*   **Session State:** Information about active and completed fuzzing sessions, their configurations, and high-level statistics.

This durable storage ensures that all valuable data generated by the fuzzer is retained, allowing for offline analysis, sharing of findings, and the ability to resume or reproduce specific scenarios. The design prioritizes non-blocking writes to ensure that data persistence does not impede the high-throughput nature of the fuzzing engine.

## II. Protocol Syntax Acquisition and Modeling for Proprietary Targets

This framework follows a generic four-stage model for protocol fuzzing: 1) protocol syntax acquisition and modeling, 2) test case generation, 3) test execution and monitoring, and 4) feedback information acquisition and utilization. For proprietary targets, Stage 1 is the primary challenge.

### A. The Hybrid Generation Strategy: From "Dumb" to "Smart"

Proprietary fuzzing presents a catch-22 regarding test case generation:
**Mutation-Based Fuzzing** (e.g., bit flipping) is simple and requires only seed files. However, it is "dumb" and highly ineffective against protocols with "multiple data types" and strict structures. The malformed inputs are rejected by the target's parser, preventing the fuzzer from exploring deeper program paths.
**Generation-Based Fuzzing** is "smart" and can generate syntactically valid inputs to bypass parsing. However, it requires a protocol specification or model, which is unavailable for proprietary targets.
The solution is a hybrid, evolving strategy. The fuzzer will not choose one method but will learn to transition from dumb to smart:
**Phase 1 (Dumb):** The fuzzer begins with simple mutation-based fuzzing on a provided seed corpus (e.g., network captures).
**Phase 2 (Learning):** In parallel, the fuzzer's feedback loop (Stage 4) feeds all captured client-server traffic into an automated Protocol Reverse Engineering (PRE) engine.
**Phase 3 (Smart):** As the PRE engine learns the protocol format, it dynamically builds the DataModel. The fuzzer automatically transitions from dumb mutation to "smart," model-aware generation, creating inputs that are semantically valid but contain malicious payloads.

### B. Automated Protocol Reverse Engineering (PRE) as a Feedback Loop

Manual PRE is "impractical," "time-consuming," and "error-prone". Automation is essential. The fuzzer will integrate a PRE module based on the principles of advanced format inference tools like AIFORE.1
**Field Boundary Recognition:** The PRE module will analyze network traces using clustering algorithms and (where possible) byte-level taint analysis to identify "indivisible input fields".1
**Semantic Type Identification:** Using heuristics and trained models, the module will predict the semantic type of each identified field (e.g., magic number, size, offset, string, or checksum).1
This PRE module is the engine of the hybrid fuzzer. The feedback loop is not just for code coverage; it is for format learning. This creates a virtuous cycle:
* Dumb Fuzzing ->
* Generates New Client/Server Responses ->
* PRE Module Analyzes Responses ->
* Refines the DataModel ->
* Enables Smarter, Generation-Based Fuzzing ->
* Reaches Deeper Code Paths ->
* Generates More New Responses ->
* (Repeat)
This "format-based power scheduling" 1 allows the fuzzer to prioritize inputs that discover new format variants, effectively "learning" the proprietary protocol on its own.

## III. Mastering Stateful Fuzzing: From State Machines to Dynamic Wrappers

This section addresses the most complex query: handling protocol state and the "wrappers" (dynamic fields) that define it.

### A. State Machine Inference (Learning the "Grammar")

Knowing the syntax of individual messages (the DataModel) is insufficient. Stateful protocols demand a valid sequence of messages to reach vulnerable code. A fuzzer that sends a "data" packet before an "authentication" packet will fail.
The solution is to integrate a state machine learning component. This component will:
* Operate in black-box mode, sending message sequences and observing server responses.
* Use these observations to algorithmically infer a Mealy machine or Deterministic Finite Automaton (DFA) that models the protocol's behavior.
This learned model becomes the programmatic StateModel in our plugin architecture. The fuzzer now knows what to send (from the DataModel) and when to send it (from the StateModel).
This learned state machine is a dual-use component. It not only guides the fuzzer to deeper states but also serves as a bug-finding oracle itself. As demonstrated in recent research 3, it is possible to:
* Formally define "bug patterns" (e.g., "data access without authentication") as a separate DFA.
* Compute the intersection of the learned Mealy machine and the bug-DFA.
* If this intersection is non-empty, the fuzzer has found a candidate bug sequence that represents a logical flaw in the protocol, which it can then test and validate.3

### B. Handling Dynamic "Wrappers" (Session IDs, Nonces, Checksums)

This is the pinnacle challenge. Many protocols use dynamic "wrappers" like session IDs, sequence numbers, nonces, or integrity checksums. Simple mutation always breaks these, rendering the test case invalid and causing the fuzzer to fail.4 A three-pronged strategy is required to handle these.
**Identification (Dynamic Taint Analysis):**
To handle a dynamic field, the fuzzer must first identify it. This will be achieved with whole-system taint analysis, similar to that used in frameworks like STAFF. The process is as follows:
* The fuzzer "taints" the bytes of a server's response (e.g., a field believed to be a session ID).
* It then monitors the client's memory to track this tainted data.
* When the client constructs its next request, the fuzzer observes which field in the new request is populated with the tainted data.
This automatically discovers the dependency: "Bytes 20-24 of AUTH_RESPONSE are used as bytes 4-8 of DATA_REQUEST." The field is now marked as "dynamic."
**State Management (Copy & Predict):**
Once identified, these dynamic fields are handled specially by the mutation engine:
* **Session IDs/Nonces:** For fields marked "dynamic" by the taint analysis, the fuzzer will not mutate them. Instead, it will copy the correct, live value from the server's last response into the new fuzzed packet.
* **Sequence Numbers:** The fuzzer will identify simple counters (e.g., n+1) and update them accordingly.
* **Prediction:** LLMs can also be integrated to assist in this stage, helping to predict the next required message type in a complex sequence, while the taint-and-copy mechanism handles the content.
**Integrity Checks (Automated Recalculation):**
Checksums (like CRC32 or custom algorithms) are another hard blocker. The fuzzer will:
* **Identify:** Use taint analysis (as in TaintScope) or heuristics to find the checksum field.
* **Synthesize:** Integrate an algorithm synthesis module. This module is fed a set of valid (Message, Checksum) pairs and synthesizes a Python function that implements the checksum algorithm.
* **Execute:** This synthesized function is automatically added to the protocol's plugin. The fuzzing loop then becomes: Mutate Packet Data -> Call Synthesized_Checksum() -> Overwrite Checksum Field -> Send Packet. This allows mutated data to pass integrity checks and reach deep, vulnerable code.

## IV. Transport Layer Considerations (TCP & UDP)

The framework must support both TCP and UDP, which have fundamentally different characteristics and require different fuzzing strategies.

### A. TCP (Connection-Oriented, Stateful Transport)

**Challenges:** is itself a stateful protocol, requiring a 3-way handshake and management of sequence numbers. Fuzzing over a real TCP stack is slow, as each test case may require a full connection teardown and setup to ensure a clean state. Research has also shown that TCP stacks themselves are a rich source of "memory and semantic bugs".
**Design Proposal (Two-Mode Operation):** The fuzzer will offer two transport modes for TCP to manage the trade-off between speed and fidelity:
* **Mode 1: High-Speed (Stack Bypass):** For fuzzing the application logic, the fuzzer harness will bypass the network stack. This can be done by replacing internet sockets with high-speed, local UNIX domain sockets or shared memory. This approach is orders of magnitude faster.
* **Mode 2: High-Fidelity (Full-Stack):** For fuzzing the system's handling of the protocol, the fuzzer will send real network packets. This is much slower but is the only way to find bugs in the interaction between the application and the kernel's TCP stack (e.g., vulnerabilities related to packet reordering or fragmentation).

### B. UDP (Stateless, Unreliable Transport)

Challenges: Many stateful application protocols (e.g., IoT, SCADA, DTLS) are built on top of stateless UDP. In this model, the application is responsible for handling packet loss, reordering, and re-assembly.
**Design Proposal (Adversarial Transport Simulation):** The unreliability of UDP should be treated as a fuzzing feature. The fuzzer's UDP transport plugin will not be a simple "send" function but an adversarial network simulator. It will maintain a buffer of fuzzed packets and, based on user-configurable "chaos" settings, will:
* **Simulate Packet Loss:** Randomly "forget" to send certain packets.
* **Simulate Reordering:** Change the send order of packets.
* **Simulate Duplication:** Send the same packet multiple times.
This strategy directly attacks the target's reassembly buffers and state management logic, a rich source of vulnerabilities (e.g., memory exhaustion from duplicate packets, or logic flaws from reordered packets).

## V. A Taxonomy of Test Cases for Proprietary Protocols

The fuzzer's test case generator (Stage 2) must be "vulnerability-aware," creating inputs designed to trigger specific, common bug classes.

### A. Targeting Key Vulnerability Classes

The generation engine, guided by the DataModel learned in Stage 1, will create test cases targeting these vulnerabilities:
**Memory Corruption:**
* **Buffer Overflows (Stack & Heap):** This is a primary target. Once a length field is identified in the DataModel, the fuzzer will generate test cases that create a mismatch: length_field < actual_data_size (underflow) and length_field > actual_data_size (overflow).
* **Integer Overflows:** The fuzzer will target all fields identified as 8, 16, 32, or 64-bit integers and inject boundary values (e.g., 0, -1, MAX_INT, MAX_INT + 1).
**Logical & Injection Flaws:**
* **Format String:** For any field identified as a string, the fuzzer will inject format specifiers like %n, %s, and %x.
* **Command Injection:** The fuzzer will inject shell metacharacters (e.g., ;, |, &, $(...)) into string fields.
* **Path Traversal:** The fuzzer will inject ../ and ..\ sequences into fields that may be used as filenames or resource identifiers.
Table 1: Test Case Generation for Common Vulnerability Classes

| Vulnerability Class | Description | Required Knowledge (from DataModel) | Generation Strategy |
|---|---|---|---|
| Stack/Heap Buffer Overflow | Writing data past the end of a buffer. | A length field and its corresponding data buffer. | Generate packet where length_field > len(data_buffer). Send oversized string/blob. |
| Integer Overflow | Causing an integer to wrap around. | Any field identified as an integer (int16, int32, etc.). | Inject boundary values: $0$, $-1$, $2^{16}-1$, $2^{16}$, $2^{32}-1$, $2^{32}$. |
| Format String | Uncontrolled format string passed to a function like printf. | Any field identified as a string. | Inject format specifiers: %s%s%s, %n, %x. |
| Command Injection | Injecting OS commands into a data field. | Any field identified as a string. | Inject shell metacharacters: ;/bin/sh, `` |
| Path Traversal | Accessing files outside of an intended directory. | Any field used as a resource identifier (e.g., filename). | Inject sequences: ../../etc/passwd, ..\\..\\boot.ini. |


### B. A Comprehensive Character Set & Encoding Strategy

Invalid handling of character encodings is a major, often-overlooked vulnerability class. The fuzzer's mutation engine must include a dedicated "Encoding" mutator.
**Legacy Encodings (EBCDIC):**
**Target:** Mainframe systems and legacy applications.
Problem: EBCDIC and ASCII are fundamentally different encoding schemes.5 For example, the character 'A' is 0x41 in ASCII but 0xC1 in EBCDIC. A blank space is 0x20 in ASCII but 0x40 in EBCDIC.
Solution: The fuzzer will have an "EBCDIC-aware" mode. When targeting a mainframe, it will translate its standard attack strings (e.g., ../etc/passwd) into their EBCDIC byte representations before transmission.
**Unicode-Based Attacks (UTF-8/UTF-16):**
Problem: Naive validation code often fails to correctly handle the complexities of Unicode, leading to security bypasses.
Solution: The fuzzer will have a dedicated mutator for generating invalid and ambiguous Unicode sequences:
* **Overlong UTF-8 Sequences:** These are non-canonical representations of a character. For example, the slash / (U+002F, or 0x2F as a byte) can be "overlong" represented in 2 bytes as 0xC0 0xAF. A weak security filter looking for 0x2F will miss it, but a post-validation decoder will canonicalize it back to /, leading to a bypass.
* **Invalid Surrogate Pairs:** The fuzzer will send unpaired high or low surrogates (e.g., 0xD800 without a following low surrogate) to test the decoder's error handling.
* **"Best-Fit" Mapping:** This subtle attack fuzzes with characters that are "safe" in one character set but map to "dangerous" characters (like \ or ") during a "best-fit" conversion to a different encoding.
* **Endianness:** The fuzzer will send UTF-16LE data to a parser expecting UTF-16BE, and vice-versa, to test for mishandling.
Table 2: Comprehensive Character and Encoding Sets for Fuzzing Inputs

| Encoding Class | Description | Target System | Specific Test Cases (Byte Sequences) |
|---|---|---|---|
| ASCII | Standard 7-bit character set. | All | Inject non-printable control chars ($0x00$-$0x1F$, $0x7F$), high-bit chars ($0x80$-$0xFF$). |
| EBCDIC 5 | IBM mainframe character set. | Mainframe systems, legacy banking apps. | Send ASCII payloads translated to EBCDIC (e.g., A = 0xC1, 1 = 0xF1). |
| UTF-8 | Variable-width Unicode encoding. | All modern web and network services. | Overlong: 0xC0 0xAF (for /). 0xE0 0x80 0x80 (for NUL). Invalid: 0xC0 0xC1 (invalid sequences). |
| UTF-16 | 16-bit (variable) Unicode encoding. | Windows systems, Java, COBOL. | Invalid Surrogates: 0xD800 (unpaired high). Endian Mismatch: Send UTF-16LE (0x41 0x00) to a BE parser. |


## VI. The Intelligent Oracle: Detecting Non-Crash Failures

This section directly addresses the query on "intelligent for monitoring for failures" when a crash is not obvious. A fuzzer is only as good as its "oracle"—its mechanism for detecting failure. A simple check for a process crash is insufficient. A multi-layered "Intelligent Oracle" system is proposed.

### A. **Host-Level System Monitoring (The "Adverse Effects" Monitor):**

This is a black-box oracle that instruments the environment of the target, not the target itself.6 The "Target Agent" (from Section I) will be responsible for this monitoring.
**Resource Monitoring:**
**CPU Usage:** The agent will monitor the target process's CPU utilization. A sustained spike to 100% following a test case is a strong indicator of an infinite loop or heavy resource contention.
**Memory Consumption:** The agent will track the process's memory usage. A steady, non-returning increase in memory consumption after repeated test cases indicates a memory leak.6
**Crash & State Monitoring:**
**Silent Crashes:** The agent will monitor OS event logs and crash dump directories (e.g., for memory.dmp files) to detect crashes that are silently restarted by a parent process.
**Hardware Oracles:** For embedded/IoT targets, the agent plugin will support hardware-level monitoring. Observing "power consumption" or "core temperatures" can serve as a proxy for failures like reboots (power cycle) or infinite loops (thermal spike).6

**Compiler-Level Instrumentation (The "High-Fidelity" Oracle):**

This is a "grey-box" oracle. When the user has source code, this is the most powerful detection method. The fuzzer's build-chain must support compiling the target with:
**AddressSanitizer (ASan):** A fast memory error detector. ASan is the most critical tool for this oracle, as it uses compile-time instrumentation to turn subtle, non-crashing memory errors (like use-after-free, buffer overflows, and memory leaks) into immediate, deterministic, and highly descriptive crashes.
**UndefinedBehaviorSanitizer (UBSan):** Detects undefined behavior such as integer overflows, invalid shifts, and null pointer dereferences.
**MemorySanitizer (MSan):** Detects reads of uninitialized memory.
This instrumentation provides the highest-fidelity feedback, transforming "adverse effects" into detectable crashes.

### C. **Application-Specific Behavioral Monitoring (The "Logical" Oracle):**

This final oracle layer is designed to catch logical bugs, not just memory-corruption bugs.
**State Anomaly Detection:**
The state machine learned in Section III.A is re-used here as a baseline for "normal" behavior.6 The fuzzer knows what valid state transitions look like. If an input causes an invalid state transition or a "behavioral shift" (e.g., an authenticated session is suddenly dropped to an unauthenticated state), the oracle flags this as a logical failure. This uses anomaly detection to build a "profile of nominal execution" and flags any "contextual anomaly" that deviates from it.
**The "Specification Oracle":**
This is the ultimate oracle for domain-specific, logical bugs. The fuzzer's plugin architecture will allow the user (a domain expert) to provide an optional validate_response(response) Python function. This is an "application-specific oracle" that can check for semantic correctness.
Example:
A user testing a financial protocol wants to ensure a fuzzed "GetBalance" request never returns a negative value. They provide this simple check:
Python
```python
def validate_response(response):
  if response.msg_type == 'BALANCE_INFO' and response.balance_field < 0:
    # This is not a crash, but it is a critical logic bug.
    raise LogicalFailure("Negative balance returned")
```

This simple, extensible check allows the fuzzer to find critical application flaws that no generic, automated tool could ever detect.
Table 3: A Comparative Framework of Failure Detection Oracles

| Oracle Type | Bug Class Detected | Overhead | Requirements |
|---|---|---|---|
| Process Exit Code | Obvious crashes (e.g., Segfault). | Low | None. |
| Crash Dump Analysis | Silent/background crashes, detailed crash info. | Low | Admin access, debug symbols. |
| Resource Monitor (CPU) | Infinite loops, Denial of Service (DoS). | Medium | Target agent with host access. |
| Resource Monitor (Memory) | Memory leaks, resource exhaustion. | Medium | Target agent with host access. |
| Hardware Monitor (Power) | Reboots, physical crashes, infinite loops (thermal).6 | High | Hardware sensor (e.g., for IoT). |
| Sanitizers (ASan, UBSan) | Use-after-free, buffer overflows, leaks, integer overflows. | High | Source code and recompilation. |
| State Anomaly Detection | Logic flaws, auth bypass, invalid state transitions. | Medium | Learned State Machine. |
| Specification Oracle | Semantic/business logic flaws (e.g., "negative balance"). | Low | User-provided validation script. |


## VII. Conclusion and Recommendations

The challenge of securing proprietary network protocols is, in reality, a threefold problem of syntax, state, and failure detection. The architectural blueprint presented in this report provides a comprehensive, learning-based solution to all three.
* **For Syntax:** This design moves beyond the static "mutation vs. generation" debate. It proposes a hybrid, learning engine that uses automated Protocol Reverse Engineering as a core feedback loop, allowing the fuzzer to evolve from dumb mutation to smart generation as it learns the protocol's grammar.
* **For State:** This framework tackles stateful complexity head-on. It combines black-box state machine learning to understand protocol "grammar" with dynamic taint analysis to identify and manage "wrappers" like session IDs and nonces. It further automates the reverse engineering of integrity checks, synthesizing checksum functions on the fly.
* **For Failure Detection:** The proposed "Intelligent Oracle" is a layered system that moves far beyond simple crash detection. It combines black-box host monitoring (for leaks and loops), grey-box sanitizers (for memory safety), and application-aware behavioral analysis (for logic flaws).
This modular, container-based and plugin-driven architecture directly addresses the need for portability and extensibility. By designing a system that learns the protocol and adapts its oracles, it provides a viable and powerful path forward for discovering vulnerabilities in the "black-box" systems that underpin modern critical infrastructure.
## Works cited
* [AIFORE: Smart Fuzzing Based on Automatic Input Format ... - USENIX](https://www.usenix.org/system/files/usenixsecurity23-shi-ji.pdf)
* [Are Containers Only for Microservices? Myth Debunked | Docker](https://www.docker.com/blog/are-containers-only-for-microservices-myth-debunked/)
* [Automata-Based Automated Detection of State Machine Bugs in ...](https://www.ndss-symposium.org/wp-content/uploads/2023-68-paper.pdf)
* [SATFuzz: A Stateful Network Protocol Fuzzing Framework from a ...](https://www.mdpi.com/2076-3417/12/15/7459)
* [Character sets and code pages - IBM](https://www.ibm.com/docs/en/cobol-zos/6.4.0?topic=structure-character-sets-code-pages)
* [Monitoring the fuzz target - Revenge of the Bug - Coders Kitchen](https://www.coderskitchen.com/monitoring-fuzz-target/)