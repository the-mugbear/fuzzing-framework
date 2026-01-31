# 5. Agent and Core Communication

**Last Updated: 2026-01-30**

To scale the fuzzing process and increase test case throughput, the fuzzer supports distributing workloads to multiple remote **Agents**. An agent is a separate, lightweight process responsible for executing test cases against a specific target.

## Architecture Overview

The distributed fuzzing model offloads the I/O-bound work of sending test cases and monitoring responses from the main Core process. This allows the **Core** to focus on computationally intensive tasks like test case generation and mutation, while **Agents** handle network communication and execution.

The system comprises three main components:
1.  **The `FuzzOrchestrator` (in the Core)**: Generates test cases and enqueues them for an agent. For orchestrated sessions, it dispatches the entire session configuration to the agent.
2.  **The `AgentManager` (in the Core)**: A central coordinator managing registered agents and their work queues.
3.  **The Agent (`agent/main.py`)**: A standalone Python process that polls the `AgentManager` for work, executes test cases, and reports results back.

## Communication Flow

The interaction between the Core and an Agent follows a simple, HTTP-based polling mechanism.

1.  **Agent Registration**: An agent registers with the Core via `POST /api/agents/register`, providing its ID and target configuration.
2.  **Agent Heartbeats**: The agent sends periodic `POST` requests to `/api/agents/{agent_id}/heartbeat` to signal it's alive and report telemetry (CPU/memory).
3.  **Work Queueing**:
    -   **Simple Sessions**: The `FuzzOrchestrator` generates a test case and places it into the appropriate work queue for the target, managed by the `AgentManager`.
    -   **Orchestrated Sessions**: The `FuzzOrchestrator` dispatches the *entire orchestrated session configuration* to the agent when it's first started. Subsequent test cases are then generated and executed entirely on the agent for that session.
4.  **Agent Polling for Work**: The agent polls the Core (`GET /api/agents/{agent_id}/next-case`). If work is available (either a simple test case or an orchestrated session to start), the `AgentManager` returns it.
5.  **Execution and Result Submission**: The agent executes the test case(s) against its target and sends the result(s) back to the Core via `POST /api/agents/{agent_id}/result`.

This polling-based architecture is robust and decouples the Core from agents, allowing them to connect, disconnect, or crash without bringing down the entire fuzzing campaign.

## Key Components in Detail

### `AgentManager` (`core/agents/manager.py`)
This class manages the distributed system on the Core side. It maintains `_agents` (registered agents) and `_queues` (work queues for each target). It also tracks `_inflight` test cases to prevent work loss.

### Agent (`agent/main.py`)
The agent is a much simpler process. Its `run` method orchestrates two main loops:
-   **`heartbeat_loop()`**: Periodically sends agent heartbeats to the Core.
-   **`work_loop()`**: Continuously polls the Core for work.

## Agents and Orchestrated Sessions

Agents are fully capable of executing **Orchestrated Sessions**. When an agent receives an orchestrated session configuration from the Core:

1.  **Local Orchestration**: The agent itself instantiates the `StageRunner`, `ConnectionManager`, and `HeartbeatScheduler` locally for that specific session.
2.  **`ProtocolContext` Management**: The agent manages the `ProtocolContext` locally for the session, handling `exports` from `bootstrap` stages and `from_context` injections during the `fuzz_target` stage.
3.  **Session Heartbeats**: If configured, the session-specific heartbeat is initiated and managed by the agent to keep the connection with the target alive.

This design means the agent performs the full orchestrated fuzzing lifecycle directly against the target, while still reporting summary results back to the Core. The Core primarily acts as a dispatcher and centralized results aggregator for orchestrated sessions running on agents.

## Agent Heartbeats vs. Session Heartbeats

It's important to distinguish between two types of heartbeats:

-   **Agent Heartbeat**: Sent by the agent to the Core (`/api/agents/{agent_id}/heartbeat`) to signal its operational status and report telemetry. This indicates the agent process itself is healthy.
-   **Session Heartbeat**: Configured within an orchestrated session's plugin, sent by the agent *to the target* to keep a persistent connection alive (e.g., a periodic PING). This ensures the fuzzing session remains active and authenticated.

Both serve critical but distinct functions in maintaining a robust distributed fuzzing environment.
