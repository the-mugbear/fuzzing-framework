# Roadmap — MVP → Full Vision for the Portable Proprietary Protocol Fuzzer

Below is a practical, phased roadmap that delivers a usable MVP quickly and then iteratively adds the advanced PRE, state learning, instrumentation, and synthesis features. Each phase lists goals, deliverables, key tasks, dependencies, rough timelines (weeks), suggested roles, acceptance criteria, and risks. Teams can treat each phase as a release or a set of sprints.

## Overview (timeline summary)

## Phase 0: Prep & Discovery — 1 week

Phase 1: MVP (Core + Agent + Mutation Runner + Basic Oracles) — 4 weeks

## Phase 2 — PRE (heuristics) + State Learner (lightweight, heuristics-first) — 8 weeks

## Phase 3 — Dynamic Wrappers & Checksum Synthesis — 8–10 weeks

## Phase 4 — Deep Instrumentation, Snapshot/Emulation & Hybrid Feedback (10–14 weeks)

## Phase 5 — Scalability, CI/UX, LLM Helpers, Ops Hardening — 6–8 weeks
Total (to near-complete vision): ~37–45 weeks (can be parallelized across teams)

Phase 0 — Prep & Discovery (1 week)

Goal: align scope, environments, test targets, and hire/assign roles.
### Deliverables sprint backlog, test harness design (example TCP server + seeded bugs), infra plan for snapshots, security checklist for agent deployment.

### Key tasks

Finalize MVP scope and success criteria.

Create minimal test suite: synthetic protocol servers (TCP, UDP) with seeded vulnerabilities for acceptance testing.

Choose main tech stack: Core (Python FastAPI), mutation engine (Rust or Python), Agent (Go/Rust for static binary).

Setup repo templates, CI pipeline skeleton, and artifact storage plan.

### Roles: Tech lead, product owner, infra engineer, SRE.

### Acceptance: Sprint backlog ready; test harness working locally.

## Phase 1 — MVP (4 weeks)

Goal: deliver containerized Core, a minimal target Agent, mutation-based runner, plugin scaffold, and host-level oracle.

Deliverables

Core container (Docker) with REST API and minimal Web UI (start/stop runs, view results).

Agent binary (Linux) + Docker container variant; TLS auth between Core↔Agent.

Plugin scaffold (single Python file) and CLI to load it.

Mutation-based fuzz runner (seed upload, run control), corpus store, and crash repro packaging (pcap + plugin + metadata).

### Sprint tasks

Implement Core REST API and simple UI (start/run, status, logs).

Implement agent comms over TLS; basic send/receive path to target (socket).

Mutation engine: simple mutators (bitflip, byte replace, length fields).

Crash packaging & repro artifact generation.

Basic tests on synthetic protocol targets.

### Dependencies:


### Roles:

### Acceptance criteria

Can run fuzz session against local test server and produce a reproducible crash artifact.

Plugin loaded at runtime without Core restart.

Agent authenticates with Core and reports CPU/memory/process exit.

### Risks & Mitigations

Agent install resistance → provide Dockerized agent and network-proxy mode.

High false-positive noise → keep triage simple and document manual steps.

Phase 2 — PRE (heuristics) + State Learner (8 weeks)

Goal: teach the fuzzer to infer message fields and simple state sequences using lightweight heuristics and Mealy/L* inference.

Deliverables

PRE (heuristics): field boundary detection from PCAPs, type-guessing (string/int/len/checksum candidates).

CLI scaffold-protocol --pcap seed.pcap that generates a draft plugin from PRE output.

State Learner (L*-style) for inferring simple state graphs (auth→ready→command).

StateModel visualizer (graph export, e.g., DOT/SVG).

Dynamic field copy heuristics (detect candidate session IDs & counters).

Sprint tasks

Implement PRE: clustering of similar messages, boundary heuristics, type heuristics.

Implement simple Mealy learner using alphabet reduction; store discovered transitions in StateModel plugin format.

Build StateModel visualizer UI component.

Add glue to let PRE output populate plugin scaffold; linting + human review step.

Dependencies: Phase 1 endpoint, PCAP test corpus.

### Acceptance

PRE-generated plugin successfully exercises test target with 50% reduction in parser rejections vs blind mutation (metric configurable).

State learner infers the known auth->command sequence from synthetic target.

### Risks

PRE overfits short captures → require minimum corpus size and human-in-loop review.

Phase 3 — Dynamic Wrappers & Checksum Synthesis (8–10 weeks)

Goal: correctly handle dynamic session fields, counters, and integrity checks; enable mutated inputs to pass checks and reach deep code.

Deliverables

Taint-lite mode: response→request mapping heuristics and copy behavior for session fields.

Counter detection and auto-increment strategy.

Checksum synthesis pipeline:

standard algorithm matcher (CRC, Adler, HMAC),

enumerative synthesizer (small program search),

SMT/Solver refinement (Z3) for ambiguous cases,

fallback black-box model if synthesis fails.

Integration of synthesized checksum into protocol plugin (auto-insert function).

Sprint tasks

Build response→request mapping module using frequency and position heuristics.

Implement counter detection algorithms (delta, monotonic).

Implement checksum matcher library and enumerative synthesis engine; add verification tests.

Add UI/CLI controls to accept/reject synthesized algorithm and to re-run tests.

Dependencies: PRE + StateModel from Phase 2, solver libraries.

Roles: Systems engineer (1), synthesis/solver engineer (1), backend (1), QA (1).

Acceptance

For sample protocols that use a checksum, synth pipeline finds correct function and generated fuzz inputs pass the integrity checks and exercise new code paths.

Dynamic session fields are recognized and properly copied for at least 80% of cases in controlled tests.

Risks

Synthesis cost/time → add timeouts and fallbacks; require human review for complex custom algorithms.

Phase 4 — Deep Instrumentation, Snapshot/Emulation & Hybrid Feedback (10–14 weeks)

Goal: enable high-fidelity feedback (coverage), enable firmware/embedded snapshotting for fast reset, and integrate DBI-based taint for lab targets.

Deliverables

Optional DBI integrations: DynamoRIO / Frida wrappers for taint and coverage collection.

Snapshot/emulation harness (QEMU + snapshot manager) with Core integration for fast resets.

Power scheduling combining coverage (edge/PC), state coverage, and oracle anomaly scoring.

Corpus deduplication/minimization using combined coverage+state signatures.

Performance improvements: mutation engine optimization (Rust), throughput metrics.

Sprint tasks

Wrap DynamoRIO or Frida in worker service that streams coverage to Core.

Implement QEMU harness: snapshot creation, restore, and hooks for input injection.

Implement hybrid power scheduler that weights testcases by coverage+state novelty+anomaly.

Implement corpus minimizer and dedupe.

Dependencies: Phase 1–3 features, QEMU images and test firmware.

Roles: Instrumentation engineer (1–2), infra (1), backend (1), QA (2).

Acceptance

DBI-run yields higher unique-coverage and more actionable crashes on lab targets vs non-instrumented runs.

QEMU snapshot mode achieves targeted TCPSend/sec for benchmark; snapshot reset time under target.

Risks

Complexity and licensing of DBI tools; make optional and documented.

Phase 5 — Scalability, LLM Helpers, UX, CI & Ops Hardening (6–8 weeks)

Goal: make the product operationally robust, add developer productivity helpers, and polish UX for wider adoption.

Deliverables

CI/CD integration: reproducible runs from PRs, report artifacts, scheduling.

LLM-powered scaffold-protocol improvements: better drafts, comment suggestions, and interactive editing.

Dashboard: coverage vs states vs anomalies; repro & triage workspace.

Operational hardening: signed agent releases, role-based access, safemode/default rate-limits.

Documentation, runbooks, and training materials for operators.

Sprint tasks

Implement CI job templates and API endpoints for programmatic runs.

Integrate an LLM (configurable) to produce better plugin drafts, plus UI to accept/reject changes.

UX improvements and usability testing; add triage flows for security teams.

Harden agent install, add audit logging, and RBAC.

Dependencies: prior phases complete; LLM API keys.

Roles: Product UX (1), Backend (1), Security engineer (1), Docs (1).

Acceptance

Team can run a nightly, reproducible fuzzing pipeline producing reports; LLM-generated scaffolds reduce plugin authoring time by a measurable amount in user tests.

Risks

LLM hallucinations — always require human review and limit exposure to sensitive data.

## Cross-Phase Items (ongoing)

Security / Legal: build templates for authorization, consent, safe-mode, and admin approval across all phases.

Telemetry & Metrics: define KPIs and automatic dashboards from day 1 (TTFR, states discovered, corpus size growth).

Testing: maintain the synthetic test suite and add real-world sample targets as available.

Backups & Reproducibility: store artifacts (pcap, plugin, state graph, agent logs) immutable for each finding.

## Suggested Team Structure & Roles

Technical Lead / Architect (1) — cross-phase coordination, acceptance criteria.

Backend Engineers (2–3) — Core API, orchestration, data model.

Systems / Instrumentation Engineers (1–2) — Agent, DBI, QEMU integration.

Algorithms / ML Engineer (1) — PRE, state learner, synthesis.

Frontend / UX (1) — dashboard, visualizers.

QA / SRE (1–2) — infra, test harness, performance.

Security/Compliance (0.5) — reviews & ops hardening.

Docs / DevRel (0.5) — docs, training, plugin examples.

Teams can parallelize Phases 2 & 3 to some extent (PRE and dynamic field work) but keep Phase 1 stable as the integration baseline.

## Sample 12-week release plan (detailed sprint-by-sprint for first 3 months)

Week 1 (Prep): Phase 0 complete. Repos, CA, test harness ready.
Week 2–5 (MVP): Core container + Agent + Mutation engine + UI. Deliverable demo and acceptance.
Week 6–9 (PRE core): PRE heuristics + scaffold CLI + State Learner prototype. Preview in UI.
Week 10–12 (Dynamic wrappers / checksum start): Response→request mapping + checksum matcher lib + counters detection; integrate into runs.

(After week 12, continue into Phase 3/4 items.)

Acceptance Criteria (summary)

MVP: reproducible crash artifact from a fuzz run against a synthetic TCP server; agent ↔ core TLS comms; plugin loaded dynamically.

PRE: seed.pcap → draft plugin with reduced parse rejections and a visual StateModel.

Checksum: synthesized or matched checksum functions used in-run to bypass integrity checks and reach new code paths.

DBI/QEMU: optional instrumented runs show improved crash discovery metrics vs non-instrumented baseline.