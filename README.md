# Proprietary Protocol Fuzzer

Portable, extensible fuzzing stack for proprietary network protocols. The Core orchestrator (FastAPI + web UI) drives the
mutation engine and corpus store, while lightweight agents relay test cases to remote targets and stream telemetry back.
Protocol plugins describe both data/state models so the runtime can generate realistic traffic, apply deterministic
behaviors (sequence numbers, checksums), and now follow state machines end-to-end.

## Highlights
- **State-aware fuzzing** – `core/engine/stateful_fuzzer.py` keeps sessions on valid transitions, periodically resets to
  explore alternatives, and records state coverage.
- **Declarative protocol behaviors** – `core/protocol_behavior.py` increments counters or patches checksums just before
  transmit, keeping targets happy without custom mutators.
- **Hybrid mutation engine** – Byte-level (`bitflip`, `havoc`, `splice`, …) and structure-aware mutations share the
  workload with tunable weights per session.
- **Agents with health telemetry** – `agent/main.py` polls `/api/agents/{id}/next-case`, executes payloads (optionally via
  `--launch-cmd`), and emits CPU/memory/active-test metrics via heartbeats.
- **One-off tests & previews** – `POST /api/tests/execute` reproduces bugs without a full session, while
  `POST /api/plugins/{name}/preview` feeds the UI real parser/mutator output so derived fields stay accurate.
- **Corpus & crash triage** – Seeds, findings, and logs live under `data/` with JSON+MessagePack reports for replay.

## Repository Layout
| Path | Purpose |
| --- | --- |
| `core/api` | FastAPI app (sessions, corpus, plugins, preview, one-off tests) and static UI mounting. |
| `core/engine` | Mutation engine, structure-aware mutator, orchestrator, stateful fuzzing session helpers. |
| `core/plugins` | Protocol plugins (each exposes `data_model`, `state_model`, optional validators). |
| `core/ui` | Single-page dashboard plus guided docs served directly by FastAPI. |
| `agent/` | Remote worker + host monitor that relays inputs to the real target. |
| `data/corpus`, `data/crashes`, `data/logs` | Seeds, findings, and rotated logs persisted from runs. |
| `tests/` | SimpleTCP reference target plus smoke tests (`pytest tests/ -v`). |
| `docs/` & `*.md` | Living documentation (see [Documentation Index](docs/README.md)). |

## Setup & Common Commands
```bash
make install        # Runtime deps
make dev            # + pytest, pytest-asyncio, black, ruff
make run-core       # Launch FastAPI orchestrator (http://localhost:8000)
make run-target     # Start SimpleTCP reference target
make run-agent      # Connect agent to localhost target
make test           # pytest tests/ -v
make docker-up      # Full Docker compose stack (core, agent, target)
make docker-down    # Stop containers; add -v to reset volumes
make docker-logs    # Tail compose logs
```

## Running a Session
1. **Prepare the target** – `make run-target` locally or expose a remote host/port; agents can `--launch-cmd` to babysit
   binaries so crashes are observable.
2. **Start the Core** – `make run-core` (or `make docker-up`). The UI and REST API live at `http://localhost:8000`.
3. **Register an agent (optional)** – `python -m agent.main --core-url ... --target-host ... --poll-interval 1.0`. Core
   mode works out of the box; set `execution_mode = "agent"` in `FuzzConfig` to offload work.
4. **Create a session** – Via UI or API:
   ```bash
   curl -X POST http://localhost:8000/api/sessions \
     -H 'Content-Type: application/json' \
     -d '{
           "protocol": "simple_tcp",
           "target_host": "localhost",
           "target_port": 9999,
           "enabled_mutators": ["bitflip","havoc"],
           "execution_mode": "core",
           "max_iterations": 2000
         }'
   ```
5. **Monitor & triage** – UI charts use `/api/sessions/{id}/stats`, while findings appear under `data/crashes/<uuid>/` as
   `input.bin`, `report.json`, and `report.msgpack` for replay.

## Key Workflows & APIs
- **Mutator selection** – Query `GET /api/mutators`, then pin `enabled_mutators` per session. Hybrid mode weight is set by
  `structure_aware_weight` (0–100) and defaults to 70%.
- **Declarative behaviors** – Attach `behavior` blocks to fixed-width fields inside plugins. Supported operations:
  `increment` (with `initial`, `step`, `wrap`) and `add_constant` (useful for checksums/opcodes). Runtime state is stored
  per session and applied in both core + agent modes.
- **Stateful fuzzing** – Provide a `state_model` with `initial_state`, `states`, and `transitions`. The orchestrator will
  instantiate `StatefulFuzzingSession`, restrict mutations to valid messages for the current state, inspect responses, and
  periodically reset to explore alternate paths.
- **Preview + debugger** – `POST /api/plugins/{plugin}/preview` accepts `{ "mode": "seeds"|"mutations", "count": N }`
  and returns parsed field metadata, computed references, and hex dumps directly from the parser/mutator pipeline. The UI
  uses this to keep derived fields trustworthy.
- **One-off executions** – `POST /api/tests/execute` with a base64 payload to validate reproducers without starting a
  session (core mode only). Responses include verdict, runtime, and captured bytes.
- **Logging & troubleshooting** – Structured logs mirror to stdout and `logs/` (core API, agent). Agent telemetry lines
  `agent_task_enqueued`, `agent_task_assigned`, and `result_submitted` provide breadcrumbs across phases.

## Documentation Index
The repo ships targeted design notes, implementation summaries, and runbooks. Start with `docs/README.md` for a curated
map. Highlights:
- `QUICKSTART.md` – Step-by-step local vs Docker setup.
- `CHEATSHEET.md` – One-page command/API reference.
- `docs/FUZZING_GUIDE.md` – Campaign workflow, terminology, troubleshooting, and practical tips.
- `PROTOCOL_TESTING.md` – Authoring/testing protocol plugins with behaviors and validators.
- `ARCHITECTURE_IMPROVEMENTS_PLAN.md`, `STATEFUL_FUZZING_IMPLEMENTATION.md`, `UI_ENHANCEMENT_PROPOSAL.md`, etc. – In-depth
  design and status docs for major subsystems.

## Project Status
MVP features (Core API, agent, UI, mutation engine, sample protocol/target, Docker workflow) are complete and tested.
Current focus areas include deeper protocol state coverage, richer crash triage, and UI polish—see `roadmap.md` and
`ARCHITECTURE_IMPROVEMENTS_PLAN.md` for active initiatives.
