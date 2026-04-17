---
description: "Run a comprehensive functional code review of the codebase and propose a prioritized improvement plan"
name: "Comprehensive Code Review"
argument-hint: "Optional: focus area (e.g. 'engine', 'api', 'plugins') or leave blank for full review"
agent: "agent"
---

Perform a comprehensive **functional code review** of this codebase${input:focus: and propose a prioritized remediation plan. If a focus area was provided, scope the review to that subsystem but still capture cross-cutting issues that touch it.

## Phase 1 — Understand the architecture

1. Read `AGENTS.md` and `CLAUDE.md` at the root to understand design intent, coding conventions, and module boundaries.
2. Read `core/models.py` and `core/config.py` to anchor the data model and configuration surface.
3. Skim `core/engine/orchestrator.py`, `core/api/server.py`, and `core/plugin_loader.py` to map the critical execution path.
4. Note any README or doc files under `docs/` that describe invariants or expected behaviors.

Do **not** stop here — use this context to inform the deep review below.

## Phase 2 — Deep functional review

For each major subsystem (engine, API routes, corpus store, plugin system, probe, mutators, session management), evaluate:

### Correctness
- Logic errors, off-by-one errors, incorrect conditionals
- Race conditions or shared mutable state in async code
- Incorrect error handling: swallowed exceptions, wrong exception types, misleading error messages
- Data integrity: fields that can be `None` where the code assumes a value, missing validation at system boundaries

### Security (OWASP Top 10 lens)
- Injection risks (command injection, path traversal, unsafe deserialization)
- Broken access control or missing authentication checks on API endpoints
- Sensitive data (credentials, payloads) leaking into logs or responses
- Dependency on user-controlled input without sanitization

### Robustness & reliability
- Missing timeouts or unbounded waits
- Resource leaks (sockets, file handles, threads not cleaned up)
- Inadequate retry / back-off logic
- Crash recovery gaps: what happens if a subprocess or probe dies mid-session?

### Consistency & maintainability
- Naming inconsistencies between models, routes, and DB/store keys
- Duplicated logic that should be shared
- Dead code or unreachable branches
- Violations of the project's stated conventions (snake_case, type hints, async/await, structlog)

### Test coverage gaps
- Paths exercised by zero tests
- Tests that assert the wrong thing or never actually fail

## Phase 3 — Propose a remediation plan

After completing the review, output a structured plan with the following sections:

### Critical (fix before next release)
Issues that cause data loss, security vulnerabilities, incorrect fuzzing results, or crashes under normal use. For each:
- **Issue**: one-sentence description
- **Location**: `file/path.py:line-range`
- **Root cause**: why it happens
- **Fix**: concrete, minimal change required

### High (fix in next sprint)
Issues that degrade reliability or correctness under edge cases, or introduce security risk that is hard to trigger but real.

### Medium (fix when touching the area)
Code quality issues, missing validations, and brittleness that don't cause immediate failures but will cause pain later.

### Low / Nice-to-have
Consistency cleanup, dead code removal, or minor improvements that are low-risk and low-priority.

### Suggested tests to add
List specific test scenarios that would catch the critical and high issues above, with enough detail to implement them.

## Output format

- Use headers and bullet points — no prose paragraphs.
- Link every finding to a file and line range.
- Keep the plan actionable: each entry must have enough context for a developer to act without re-reading the review.
- End with a one-paragraph **executive summary** of the overall health of the codebase.
