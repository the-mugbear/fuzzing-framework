# Documentation Index

Use this map to jump to the right reference for your task. Files live either at the repo root or under `docs/`.

## Getting Started & Operations
| File | Focus | Notes |
| --- | --- | --- |
| `README.md` | High-level overview, architecture summary, key workflows. | Start here before touching code. |
| `QUICKSTART.md` | Step-by-step setup (Docker + local), session walkthrough. | Mirrors `make` targets and API curls. |
| `CHEATSHEET.md` | One-page command + REST reference. | Includes preview/one-off endpoints. |
| `docs/FUZZING_GUIDE.md` | Campaign workflow, terminology, practical tips. | Updated with stateful fuzzing basics. |
| `AGENTS.md` | Repository guidelines + coding/testing standards. | Source of truth for contributors. |

## Architecture, Protocols & Roadmap
| File | Focus | Notes |
| --- | --- | --- |
| `blueprint.md` | Original architectural blueprint + PRE/oracle vision. | Deep background/context. |
| `rfc.md` | Prioritized engineering RFC (Core, Agent, PRE, milestones). | Defines goals/non-goals. |
| `roadmap.md` | Near/mid/long-term initiatives. | Tracks stateful fuzzing, triage, PRE, etc. |
| `ARCHITECTURE_IMPROVEMENTS_PLAN.md` | Gap analysis for stateful fuzzing + triage. | Proposed upgrades + code refs. |
| `STATEFUL_FUZZING_IMPLEMENTATION.md` | Phase 1 delivery details for state-aware engine. | Includes API/stats additions. |
| `STATE_VISUALIZATION_IMPLEMENTATION.md` | UI work for visualizing state machines and previews. | Complements stateful fuzzing docs. |
| `PROTOCOL_TESTING.md` | Authoring + validating protocol plugins (data/state models, behaviors). | Includes examples + debugging flow. |

## Implementation Reports & Enhancements
| File | Focus | Notes |
| --- | --- | --- |
| `MVP_SUMMARY.md` | Full MVP component rundown (Core, agent, UI, corpus). | Confirms delivered scope. |
| `COMPLETION_REPORT.md` | End-to-end summary of protocol debugger enhancements. | Links to supporting docs/tests. |
| `IMPLEMENTATION_SUMMARY.md` | Deep dive on preview endpoint + UI wiring. | Phase 1 write-up. |
| `MUTATION_TYPES_ENHANCEMENT.md` | Phase 2 for preview explorer (mutation badges/descriptions). | Pair with `COMPLETION_REPORT`. |
| `UI_ENHANCEMENT_PROPOSAL.md` | Forward-looking UI improvements backlog. | Source plan for recent work. |
| `UI_ENHANCEMENTS.md` | Shipped UI changes + screenshots/notes. | Handy for release highlights. |
| `STATEFUL_FUZZING_IMPLEMENTATION.md` | (Also listed above) Implementation report with coverage metrics. | Reference from architecture + reports. |

## Contributor & Tooling Guides
| File | Focus | Notes |
| --- | --- | --- |
| `CLAUDE.md` | Instructions for Claude Code / AI assistants. | Mirrors repo conventions. |
| `PROTOCOL_TESTING.md` | (See above) – doubles as a contributor playbook for plugin authors. |  |
| `docs/PROTOCOL_TESTING.md` | Additional protocol debugging reference hosted with the UI. | Served via `/docs`. |

Need to add or modify documentation? Update the relevant file above and keep this index current so future contributors can
discover the latest guidance quickly.
