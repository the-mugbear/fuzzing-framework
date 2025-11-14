# Proprietary Protocol Fuzzer

Portable, extensible fuzzing stack for proprietary network protocols. The Core orchestrator (FastAPI + web UI) drives the
mutation engine and corpus store, while lightweight agents relay test cases to remote targets and stream telemetry back.
Protocol plugins describe both data/state models so the runtime can generate realistic traffic, apply deterministic
behaviors (sequence numbers, checksums), and now follow state machines end-to-end.

## Highlights
- **State-aware fuzzing** – The fuzzer can follow a protocol's rules, like ensuring a `LOGIN` message is sent before a `SEND_DATA` message. It learns these rules from a `state_model` you define in a plugin, allowing it to test stateful interactions effectively.
- **Declarative protocol behaviors** – Automatically handles fields that change in predictable ways, like incrementing sequence numbers or recalculating checksums. This keeps messages valid without you needing to write custom code.
- **Hybrid mutation engine** – Combines simple, fast byte-level mutations (like flipping bits) with intelligent, structure-aware mutations that respect the protocol's grammar. The balance between these two strategies is tunable for each session.
- **Agents with health telemetry** – You can distribute the fuzzing workload across multiple 'agents' (workers), which can run on different machines. These agents execute test cases and report back health metrics like CPU and memory usage.
- **One-off tests & previews** – A powerful debugging feature that lets you send a single, specific test case to the target to reproduce a bug. The previewer also shows how the fuzzer will parse and mutate your messages before you even start a session.
- **Corpus & crash triage** – Every crash is automatically saved with the exact input that caused it, making bugs easy to reproduce and analyze. The collection of all known test cases is kept in the 'corpus'.

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
4. **Create a session** – Via UI or API. The API endpoint accepts a JSON payload with several options:
   - `protocol`: The name of the protocol plugin to use (e.g., `"simple_tcp"`).
   - `target_host`: The hostname or IP address of the target application.
   - `target_port`: The port number of the target application.
   - `enabled_mutators`: A list of which mutation algorithms to use (e.g., `["bitflip", "havoc"]`).
   - `execution_mode`: `"core"` to run locally or `"agent"` to distribute to workers.
   - `max_iterations`: The number of test cases to run before the session stops.

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

### Mutator Selection
- **List available mutators**: `GET /api/mutators`
- **Control mutators per session**: Use the `enabled_mutators` array when creating a session.
- **Hybrid Mode**: The balance between byte-level and structure-aware mutations is controlled by `structure_aware_weight` (a percentage from 0 to 100, default is 70).

### Declarative Behaviors
- Attach a `behavior` block to any fixed-width field in a plugin's `data_model`.
- **Supported operations**:
    - `increment`: Automatically increments a field's value with each message. Configurable with `initial`, `step`, and `wrap` values.
    - `add_constant`: Adds a constant value to a field. Useful for checksums or opcodes.

### Stateful Fuzzing
- To enable, provide a `state_model` in your protocol plugin with an `initial_state`, a list of `states`, and a list of `transitions`.
- The fuzzer will then automatically follow the state machine, sending valid message sequences.

### Preview and Debugging
- **Preview mutations**: `POST /api/plugins/{plugin}/preview` shows how the fuzzer will parse and mutate messages, which is invaluable for debugging a new plugin.
- **One-off execution**: `POST /api/tests/execute` lets you send a single, specific payload to the target to validate a finding or test a hypothesis without a full session.

### Logging and Troubleshooting
- All components produce structured logs to `stdout` and to the `logs/` directory.
- Look for `agent_task_enqueued`, `agent_task_assigned`, and `result_submitted` log entries to trace a test case through the distributed system.

## Documentation Index
The repository contains a suite of documentation to help you get started and dive deep into the fuzzer's architecture. For a complete and curated list of documents, please see the **[Documentation Index](docs/README.md)**.

Key documents include:
- [QUICKSTART.md](QUICKSTART.md): A step-by-step guide to get the fuzzer running in 5 minutes.
- [docs/FUZZING_GUIDE.md](docs/FUZZING_GUIDE.md): A practical guide to fuzzing concepts, campaign strategy, and troubleshooting.
- [docs/PROTOCOL_TESTING.md](docs/PROTOCOL_TESTING.md): A complete, in-depth guide to creating, testing, and validating custom protocol plugins.
- [docs/developer/](docs/developer/): A collection of deep-dive documents explaining the architecture of each of the fuzzer's subsystems.

## Project Status
MVP features (Core API, agent, UI, mutation engine, sample protocol/target, Docker workflow) are complete and tested.
Current focus areas include deeper protocol state coverage, richer crash triage, and UI polish—see `roadmap.md` and
`ARCHITECTURE_IMPROVEMENTS_PLAN.md` for active initiatives.
