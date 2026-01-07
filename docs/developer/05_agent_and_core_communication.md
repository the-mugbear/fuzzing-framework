# 5. Agent and Core Communication

**Last Updated: 2025-11-25**

To increase the throughput of test cases and scale up the fuzzing process, the engine supports distributing the workload to multiple remote **Agents**. An agent is a separate, lightweight process that is responsible for executing test cases against a specific target.

## Architecture Overview

The distributed fuzzing model is designed to offload the I/O-bound work of sending test cases and waiting for responses from the main fuzzer process. This allows the **Core** to focus on the computationally expensive tasks of test case generation and mutation, while the **Agents** handle the network communication.

The system consists of three main components:
1.  **The `FuzzOrchestrator` (in the Core)**: Generates test cases and enqueues them for an agent.
2.  **The `AgentManager` (in the Core)**: Acts as a central coordinator, managing the pool of registered agents and their work queues.
3.  **The Agent (`agent/main.py`)**: A standalone Python process that polls the `AgentManager` for work, executes the test cases, and reports the results back.

## The Communication Flow

The interaction between the Core and an Agent follows a simple, HTTP-based polling mechanism.

1.  **Agent Registration**: When an agent starts, it makes a `POST` request to the `/api/agents/register` endpoint on the Core API, providing its ID and the target it is configured to test.

2.  **Heartbeats**: The agent sends a periodic `POST` request to `/api/agents/{agent_id}/heartbeat` to let the Core know it is still alive and to report its current telemetry (CPU/memory usage).

3.  **Work Queueing**: In the Core, the `FuzzOrchestrator` generates a test case and passes it to the `AgentManager`, which places it into the appropriate in-memory work queue for the target.

4.  **Agent Polling for Work**: The agent periodically sends a `GET` request to `/api/agents/{agent_id}/next-case`. If a test case is available in the queue, the `AgentManager` returns it in the response.

5.  **Execution and Result Submission**: The agent executes the test case against its target and sends the result back to the Core by making a `POST` request to `/api/agents/{agent_id}/result`.

This polling-based architecture is simple and robust. It decouples the Core from the agents, meaning that agents can connect, disconnect, or crash without bringing down the entire fuzzing campaign.

## Key Components in Detail

### `AgentManager` (`core/agents/manager.py`)

This class is the heart of the distributed system on the Core side.

-   `_agents`: A dictionary that stores the state of all registered agents, keyed by `agent_id`.
-   `_queues`: A dictionary of `asyncio.Queue` objects, one for each target.
-   `_inflight`: A dictionary that tracks test cases that have been sent to an agent but for which a result has not yet been received. This prevents work from being lost.
-   `register_agent()`: Handles new agent registrations.
-   `heartbeat()`: Updates the status of an agent based on a heartbeat.
-   `enqueue_test_case()`: Called by the orchestrator to add work to a queue.
-   `request_work()`: Called by the agent's polling request to get work from a queue.

### Agent (`agent/main.py`)

The agent is a much simpler process. Its main logic is in the `run` method, which starts two main loops:

-   `heartbeat_loop()`: Periodically sends heartbeats to the Core.
-   `work_loop()`: Continuously polls the Core for work, executes any received test cases, and submits the results.

This design allows the Core to manage the complex logic of fuzzing, while the agent remains a simple, focused "worker" responsible only for execution and reporting.