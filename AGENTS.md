# Repository Guidelines

## Project Structure & Module Organization
`core/` hosts the FastAPI orchestrator (`core/api`), mutation engine (`core/engine`), protocol plugins (`core/plugins`), and UI (`core/ui`). The forwarding probe lives in `probe/`, while reusable corpora and crash artifacts sit in `data/`. The Target Manager lives in `target_manager/` and manages dynamic test server lifecycles. Sample targets and integration helpers live in `tests/`. Devops assets (Makefile, Dockerfile*, docker-compose.yml, requirements.txt) stay at the root.

## Build, Test, and Development Commands
`make install` installs runtime deps; `make dev` adds pytest, pytest-asyncio, black, and ruff. Use `make run-core` to start the API and `make run-probe` to connect to the core. Test targets are started dynamically via the Target Manager (`python -m target_manager`). Container workflows rely on `make docker-build`, `make docker-up`, and `make docker-logs`. Validate changes with `make test` (alias of `pytest tests/ -v`). Use `./start.sh` for an interactive startup menu.

## Execution Modes & Probe Workflow
Sessions default to core-side execution. Set `execution_mode` to `probe` in the `FuzzConfig` payload to stream work to remote workers; the orchestrator refuses to start if no probe is registered for that target. Probes poll `/api/probes/{id}/next-case`, run the payload, and reply via `/api/probes/{id}/result`. Use the CLI flags `--poll-interval` to throttle pull cadence and `--launch-cmd` to boot and monitor a local binary (Linux process groups vs. Windows `CREATE_NEW_PROCESS_GROUP`). Heartbeats now include CPU, memory, and the number of inflight tests so the UI can surface unhealthy hosts.

## Mutators & One-off Tests
Surface available mutators with `GET /api/mutators` and pass `enabled_mutators` (e.g., `["bitflip","havoc"]`) inside `FuzzConfig` to restrict the mutation engine. For targeted debugging, hit `POST /api/tests/execute` with a base64 payload to run single-shot tests without opening a session; the response contains the verdict, execution time, and any bytes captured from the target. Probe-mode one-offs intentionally return `400` until we add asynchronous tracking, so use core mode for now.

## Declarative Field Behaviors
Plugins can attach a `behavior` map to any fixed-width block to enforce deterministic operations before every transmission. For example:

```python
{
    "name": "sequence",
    "type": "uint16",
    "behavior": {"operation": "increment", "initial": 0, "step": 1}
}
```

Supported operations today:
1. `increment` – writes the current counter value (with optional step/wrap) and advances state.
2. `add_constant` – adds a constant to the field just before send (useful for checksums or opcode tweaks).

The runtime stores per-session state, applies these behaviors in both core and probe modes, and the UI surfaces them when a protocol is selected so contributors know which fields are controlled automatically.

## Coding Style & Naming Conventions
Python 3.11+, 4-space indentation, and type hints on exported functions are required. Run `black .` before committing and keep `ruff` clean—CI mirrors `make dev`. Files and functions use snake_case, classes use PascalCase, and protocol plugin modules must expose `data_model`, `state_model`, and optional validators with descriptive names.

## Testing Guidelines
Store regression tests under `tests/` with filenames `test_*.py`. Favor pytest fixtures for reusable sockets or mock targets, and capture failing seeds under `data/corpus/` with clear prefixes. Use the Target Manager to start reference targets before fuzzing; failures triaged into `data/crashes/` should include reproduction notes or simplified payloads.

## Recording Changes in CHANGELOG.md
All code changes, bug fixes, new features, and modifications **must** be documented in `CHANGELOG.md`. The changelog follows the [Keep a Changelog](https://keepachangelog.com/en/1.0.0/) format.

### Entry Format
Each entry should include:
- **Category header**: `### Added`, `### Changed`, `### Fixed`, `### Deprecated`, `### Removed`, or `### Security` with date (`- YYYY-MM-DD`)
- **Bold summary**: Brief description of what changed
- **File paths with line numbers**: `(path/to/file.py:line-range)`
- **Detailed bullet points**: What was broken/added, how it was fixed/implemented, impact
- **Impact statement**: How this affects users or the system
- **Testing notes**: How to verify the change works correctly

### Example Entry
```markdown
### Fixed - 2026-01-26

- **Fixed bit-field endianness in serialization** (`core/engine/protocol_parser.py:132-166`)
  - Multi-byte little-endian bit fields were being serialized as big-endian
  - Modified `_serialize_fields_to_bytes` to use `_serialize_bits_field` for multi-byte LE fields
  - Impact: Round-trip consistency for little-endian multi-byte bit fields
  - Testing: Parse and re-serialize a little-endian 12-bit field, verify bytes match
```

### When to Update
Update `CHANGELOG.md` whenever you:
- Implement a new feature or component
- Fix a bug (especially critical or high-priority bugs)
- Modify existing behavior
- Add or change configuration options
- Refactor significant code sections
- Complete a work session with multiple changes

### Placement
Add new entries under the `## [Unreleased]` section at the top of the file, grouped by category and date.

## Commit & Pull Request Guidelines
Git history uses short, imperative subjects (`Fix .gitignore…`). Keep summaries ≤50 chars, capitalized, and add wrapped bodies when rationale is non-obvious. Reference issues (`Refs #42`) and mention new CLI flags or protocol files. PRs must describe the fuzzing surface touched, list manual test commands, attach UI screenshots when applicable, and link any crash artifacts necessary for reviewers to replay findings.

## Security & Configuration Tips
Treat `core/config.py` as the canonical place for timeouts, ports, and feature flags. Never embed target credentials inside plugins; parameterize them through environment variables or probe CLI flags (`--core-url`, `--target-host`, `--target-port`). Scrub proprietary payloads from corpora before committing and prefer sanitized examples under `data/corpus/example_*`.

## Logging & Troubleshooting
Structured logs flow both to stdout and `logs/`. Look at `logs/core-api.log` for session/orchestrator issues and `logs/probe.log` on each worker host for transport problems. For test-server logs, use the full-screen **Log Viewer** in the SPA (`/ui/logs/:targetId`) which provides real-time streaming with level-based filtering, text search, and auto-scroll. Probe telemetry (`probe_task_enqueued`, `probe_task_assigned`, `result_submitted`) provides an end-to-end breadcrumb trail for stubborn failures; include relevant snippets when opening PRs.
