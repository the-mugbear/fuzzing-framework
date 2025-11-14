# RFC: Portable Proprietary Protocol Fuzzer — Prioritized Engineering Plan

## Title
Portable & Extensible Proprietary Protocol Fuzzing Framework — Prioritized Engineering RFC

## Authors
Ken Charles (draft) — Architecture & Implementation Leads TBD

## Date
2025-11-05

---

## 1. Executive Summary (1-paragraph)
This RFC defines a prioritized engineering plan to implement a portable, plugin-driven, learning-based protocol fuzzing framework for proprietary network protocols. It captures the architecture, modular components (Core, Target Agent, PRE, State Learner, Oracles), prioritized milestones, acceptance criteria, risks, and required integrations (emulation/snapshot, DBI, sanitizers). The objective is an MVP in which users can deploy a Core container and a minimal agent to run mutation-based fuzzing and collect reproducible findings; follow-on milestones add PRE, state learning, checksum synthesis, and deep instrumentation.

---

## 2. Goals & Non-goals
**Goals (must satisfy):**
- Provide a containerized Core and minimal Target Agent for rapid deployment.
- Support mutation-based fuzzing with seed corpus and corpus management.
- Provide plugin format (single Python file) for protocol DataModel + StateModel.
- Basic host-level oracle (CPU/memory/crash) + crash repro artifact generation.

**Non-goals (explicit):**
- Not shipping a fully automated PRE + DBI taint system in MVP.
- Not attempting to fuzz production devices without explicit safeguards.

---

## 3. High-level Architecture (one-page)

```mermaid
flowchart LR
  subgraph Core[Core Container]
    A[Orchestrator / UI / API]
    B[Mutation & Generation Engine]
    C[Protocol Plugins Dir]
    D[PRE Service (optional)]
    E[State Learner]
    F[Corpus Store]
    G[Analyzer & Triage]
  end

  subgraph Network
    X[Target Network / Device]
  end

  subgraph Agent[Target Agent]
    AG[Receiver]
    AG2[Executor -> sends to Target]
    MON[Host Monitor]
    LOG[Log & Repro Upload]
  end

  A -->|control| AG
  B -->|fuzzed inputs| AG
  D -->|learned models| C
  AG2 --> X
  X --> AG (responses)
  AG --> F
  MON --> A
  G --> A
```

**Notes:**
- Core communicates to Agent over TLS-authenticated channel. Agent can be deployed or replaced by a network-only Probe (PCAP/proxy) when agent install is impossible.
- Plugins live in `protocols/` as a single Python script implementing `data_model` and `state_model` plus optional `validate_response()`.

---

## 4. Prioritized Milestones (MVP → M2 → M3)

### MVP (4 weeks) — deliverables & acceptance
- **Deliverables:**
  - Core container (Docker) exposing REST API + simple web UI.
  - Minimal Target Agent (Linux) as signed binary and Docker flavor.
  - Mutation-only fuzzing runner with seed corpus upload, run control, and basic host-level resource monitoring (CPU/mem/process exit).
  - Plugin scaffold (Python) + example plugin for a trivial TCP protocol.
  - Corpus store, crash repro packaging (pcap + plugin + minimal run metadata).
- **Acceptance Criteria:**
  - Able to fuzz a local TCP server in snapshot or agent mode and produce reproducible crash artifact.
  - Plugin can be loaded at runtime without restarting Core.

### M2 (8–12 weeks) — learning & statefulness
- **Deliverables:**
  - Lightweight PRE: field boundary heuristics and data-type guessing from pcap.
  - State Learner (L*-style Mealy inference) with exportable StateModel and StateModel visualization.
  - Dynamic field handling (copy-only for session IDs & counters detection heuristics).
  - Corpus deduplication by (coverage-state) signature and basic minimization tool.
- **Acceptance Criteria:**
  - PRE produces draft data_model from sample pcap; plugin scaffold can be auto-filled by CLI.
  - State learner can infer simple auth→command sequences for a test protocol.

### M3 (12–20 weeks) — deep instrumentation & synthesis
- **Deliverables:**
  - Optional DBI taint integration (DynamoRIO / Frida hooks) for high-fidelity dynamic analysis.
  - Checksum synthesis pipeline: library matching → enumerative synthesis → SMT-guided refinement.
  - Snapshot/emulation integration (QEMU + fast-reset) for embedded firmware.
  - Multi-signal feedback: coverage (if instrumented) + state coverage + anomaly score.
- **Acceptance Criteria:**
  - Successfully synthesize a CRC-like function for a sample protocol and use it during fuzz runs.
  - QEMU snapshot mode completes 1M test cases in <N hours (benchmark target to be defined).

---

## 5. Component Design Notes
- **Core:** Orchestrator written in Python (FastAPI) for plugin loading + run control. Mutation engine should be a separate process (Rust optional) to allow high-throughput loops.
- **Protocol Plugin API (Python):**
  - `data_model` — declarative block types + example seeds
  - `state_model` — graph of named states and transitions (callable hooks allowed)
  - `validate_response(response)` — optional user-provided oracle
- **Agent:** Minimal runtime (Go or Rust for static binary) that accepts test cases, forwards to target endpoint (socket/serial), and collects resource metrics.
- **PRE:** Heuristic baseline that creates candidate fields via clustering and boundary detection; users can opt-in to DBI-assisted PRE.

---

## 6. Security & Operational Safeguards
- Mutual TLS with short-lived certs for Core↔Agent.
- Agent least-privilege, signed artifacts, and tamper-evident logs.
- Safe-mode default: no disk writes or destructive commands allowed; rate-limits on destructive actions.
- Audit trail for all fuzz sessions; automatic alerting for repeated outages.

---

## 7. Testing Strategy & Benchmarks
- **Unit:** Plugin loader, agent comms, mutators, corpus triage.
- **Integration:** Local containerized server + agent + Core fuzz run producing repros.
- **Performance:** Measure TCPSend/sec in mutation mode; target 1K+ inputs/sec in stack-bypass mode.
- **Effectiveness:** Track number of unique states discovered, crashes, and logical anomalies across canonical benchmarks (e.g., small test suite of synthetic protocols).

---

## 8. Success Metrics & KPIs
- Time-to-first-repro (TTFR) for a seeded vuln < 8 hours in MVP on local lab.
- Percentage reduction in invalid/malformed responses after PRE transitions (goal: 50% fewer parse rejections).
- Unique states discovered per 24h run (baseline TBD).

---

## 9. Risks & Mitigations
- **High complexity:** Keep heavy features (DBI, SMT) optional and modular.
- **False positives from logical oracles:** Require triage, severity scoring, and human-in-loop validation.
- **Operational outages:** Enforce safe-mode and admin consent flows.

---

## 10. Next Steps (immediate)
1. Approve MVP scope and staffing (1 backend eng, 1 systems/instrumentation eng, 1 frontend/UX).
2. Implement Core + Agent minimal proof-of-concept (2–4 weeks).
3. Prepare test harness (simple TCP server with seeded bugs) and run acceptance tests.

---

### Appendix A — Plugin scaffold (example)
```python
# protocols/example_protocol.py
data_model = [
  # block definitions (field name, type, size, default)
]

state_model = {
  # graph: 'INIT' -> 'AUTH' -> 'READY'
}

def validate_response(response):
  # optional user check
  return True
```

---

---

## 11. Persistence Layer

The persistence layer is responsible for storing all test case execution records, providing durability for fuzzing sessions and enabling detailed post-mortem analysis, correlation, and test case replay.

### 11.1. Implementation

The initial in-memory persistence model has been replaced by a more robust SQLite-based solution, managed by the `ExecutionHistoryStore` component located in `core/engine/history_store.py`.

Key characteristics of the implementation include:

- **SQLite Backend:** A single SQLite database file (`data/correlation.db`) is used as the persistent store.
- **Asynchronous Writes:** To avoid blocking the high-throughput fuzzing loop, database writes are handled asynchronously. Execution records are placed in a non-blocking in-memory queue. A background writer task consumes records from this queue and performs batched writes to the database.
- **In-Memory Caching:** A `deque` is used to maintain a memory cache of the most recent test executions. This allows the UI to query for recent tests quickly without needing to hit the database, ensuring a responsive user experience.

### 11.2. Schema

The primary table is `executions`, which stores a comprehensive record for each test case:

- **Identifiers:** `session_id`, `sequence_number`, `test_case_id`
- **Timestamps:** `timestamp_sent`, `timestamp_response` for correlation and performance measurement.
- **Payload Data:** Size, hash, a preview, and the raw payload blob.
- **Protocol Context:** Protocol name, message type, and the state of the state machine at the time of sending.
- **Results:** The test case result (`PASS`, `CRASH`, `HANG`, etc.), response size, and a preview of the response.

### 11.3. Current Status & Known Issues

The SQLite persistence layer is functional but has several known issues in its current implementation:

- **Agent Executions Not Recorded:** Test cases that are dispatched to and executed by an agent are not currently recorded in the database. This is a critical gap that prevents the history of agent-based sessions from being analyzed or replayed.
- **Response Data Not Stored:** The `response_data` column in the `executions` table is not populated, meaning the full raw response from the target is not being saved.
- **No Retry on Write Failure:** If a batch write to the database fails, the records in that batch are currently dropped. A retry mechanism or dead-letter queue should be implemented to prevent data loss.

---

*End of RFC*
