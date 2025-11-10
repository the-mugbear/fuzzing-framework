# Fuzzing Guide

A practical reference to help you speak the same language as the fuzzer, structure campaigns intentionally, and triage findings quickly.

## Terminology Cheat Sheet

| Term | Meaning |
| --- | --- |
| **Seed** | A valid byte sequence that bootstraps the mutation engine. Stored in `data/corpus/seeds`. |
| **Corpus** | All seeds plus interesting mutations and crash reproducers saved during a run. |
| **Session** | A fuzzing campaign bound to a protocol, host, port, execution mode, and mutator selection. |
| **Mutator** | Algorithm that transforms a seed (e.g., `bitflip`, `havoc`, `splice`). Choose them via `enabled_mutators`. |
| **Behavior** | Declarative rule attached to a protocol block (e.g., “increment sequence”, “add constant”). Behaviors run before every send to keep deterministic fields valid. |
| **Agent Mode** | Test cases are executed by remote agents that talk to the target and stream results back to the core. |
| **One-off Test** | Single payload execution via `POST /api/tests/execute`—use it for quick validation or reproduction. |

## Building an Effective Campaign

1. **Instrument the Target**
   - Run the sample target (`make run-target` or `docker compose up target`) and tail its logs so you can see each fuzz case.
   - For custom binaries, expose structured logs or even a basic metrics endpoint—fuzzing is faster when you can spot crashes immediately.

2. **Author/Review the Protocol Plugin**
   - Define immutable headers (`mutable: false`) so core signatures stay intact.
   - Model state transitions and supply at least 3 realistic seeds.
   - Add `behavior` blocks for deterministic fields:
     ```python
     {
         "name": "sequence",
         "type": "uint16",
         "behavior": {"operation": "increment", "initial": 0, "step": 1}
     }
     {
         "name": "checksum",
         "type": "uint8",
         "behavior": {"operation": "add_constant", "value": 0x55}
     }
     ```
     Behaviors are executed automatically in both core and agent modes, so mutators can focus on the truly interesting bytes.

3. **Choose Execution & Mutators**
   - Core mode is simplest; agent mode lets you forward traffic via remote workers/monitors.
   - Use `/api/mutators` to list options and pass `enabled_mutators` when creating the session. Start broad (bitflip + havoc) and tighten once you know which fields trigger bugs.

4. **Run & Observe**
   - Kick off the session, then poll `/api/sessions/<id>/stats` or watch the UI dashboard. Rising `total_tests`, `hangs`, or `anomalies` confirm progress.
   - Monitor target logs, `logs/core-api.log`, and agent logs simultaneously. Each crash is saved under `data/corpus/findings/<id>` with both the repro input and JSON metadata.

5. **Triage & Iterate**
   - Re-run interesting seeds via the one-off endpoint or netcat to confirm determinism.
   - Promote failing inputs to the seed corpus for focused future runs.
   - Update the protocol plugin (new blocks, behaviors, validators) as you learn about the target.

## Stateful Fuzzing Basics

State models are now first-class: when a plugin exposes `state_model`, the orchestrator instantiates
`StatefulFuzzingSession` to keep sequences valid.

1. **Define transitions intentionally** – Include `initial_state`, `states`, and `transitions` with
   `message_type` labels that match the command block's `values` map. Optional `expected_response`
   strings help the runtime validate replies before advancing.
2. **Seed per message type** – Provide at least one seed for every `message_type` so the engine can
   pick the right template when it needs to send CONNECT vs AUTH vs DATA.
3. **Monitor coverage** – Hit `GET /api/sessions/{id}/state_coverage` (or watch the UI state diagram)
   to see which states/transitions have been exercised. Reset or tweak `structure_aware_weight` if
   coverage stalls in early states.
4. **Reset cadence** – The engine periodically calls `reset_to_initial_state()`; adjust
   `max_iterations`/rate limits so resets do not starve deep states.

State metadata now flows into the preview endpoint/UI, so you can confirm each generated test case
shows the intended `message_type`, valid state, and transition before launching a full run.

## Practical Tips

- **Good Seeds Trump Raw Speed**: Invest time collecting authentic traffic captures; they produce deeper coverage than synthetic seeds.
- **Use Behaviors for “protocol glue”**: Sequence counters, derived lengths, and checksums should be behaviors, not custom mutators.
- **Layer Monitoring**: CPU/memory spikes plus target logs help distinguish true crashes from benign timeouts.
- **Split Long Campaigns**: Stop sessions periodically to snapshot findings, then restart with fresh mutator mixes.
- **Reproduce Outside the Lab**: When you hit a bug, replay it against staging systems or instrumented targets to confirm impact.

Keep this guide open while fuzzing—the workflow (instrument → model → run → observe → iterate) will quickly become second nature.
