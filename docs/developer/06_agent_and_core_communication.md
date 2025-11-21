# 6. Agent and Core Communication

To increase the throughput of test cases and scale up the fuzzing process, the engine supports distributing the workload to multiple remote **Agents**. An agent is a separate, lightweight process, potentially running on a different machine, that is responsible for executing test cases against a specific target. This document explains the architecture of this distributed system.

## Architecture Overview

The distributed fuzzing model is designed to offload the I/O-bound work of sending test cases and waiting for responses from the main fuzzer process. This allows the **Core** to focus on the computationally expensive tasks of test case generation and mutation, while the **Agents** handle the network communication with the target.

The system consists of three main components:
1.  **The `FuzzOrchestrator` (in the Core)**: When a session is in `AGENT` mode, the orchestrator generates test cases but does not execute them. Instead, it enqueues them for an agent.
2.  **The `AgentManager` (in the Core)**: This component acts as a central coordinator. It manages the pool of registered agents and maintains a work queue for each target.
3.  **The Agent (`agent/main.py`)**: A standalone Python process that polls the `AgentManager` for work, executes the test cases it receives, and reports the results back.

## The Communication Flow

The interaction between the Core and an Agent follows a simple, HTTP-based polling mechanism.

1.  **Agent Registration**:
    *   When an agent starts, it makes a `POST` request to the `/api/agents/register` endpoint on the Core API.
    *   In this request, it sends its own metadata, including the `host` and `port` of the target application it is configured to test.
    *   The `AgentManager` receives this request, creates a new `Agent` record, and assigns the agent a unique `agent_id`. It also creates a dedicated work queue in memory for the agent's target if one doesn't already exist.

2.  **Work Queueing**:
    *   Meanwhile, if a fuzzing session is running in `AGENT` mode, the `FuzzOrchestrator` generates a test case.
    *   Instead of executing it, it calls the `AgentManager`'s `enqueue_test_case` method, passing the test case and the target information.
    *   The `AgentManager` places the test case into the appropriate in-memory work queue for that target.

3.  **Agent Polling for Work**:
    *   The agent enters a continuous loop where it periodically sends a `GET` request to the `/api/agents/{agent_id}/work` endpoint. The frequency of this polling is configurable via the agent's `--poll-interval` command-line argument.
    *   The `AgentManager` receives this request. It checks the work queue for the agent's target.
    *   If a test case is available, the `AgentManager` dequeues it and returns it in the HTTP response to the agent. If the queue is empty, it returns an empty response.

4.  **Execution and Result Submission**:
    *   When the agent receives a test case, it sends the payload to its target.
    *   It monitors the outcome (e.g., success, crash, hang) and collects any telemetry from the target's system (CPU/memory).
    *   It then sends the result back to the Core by making a `POST` request to the `/api/sessions/{session_id}/results` endpoint.
    *   The `FuzzOrchestrator` receives this result, processes it, and, if it's a crash, initiates the crash triage process.

This polling-based architecture is simple and robust. It decouples the Core from the agents, meaning that agents can connect, disconnect, or crash without bringing down the entire fuzzing campaign.

## Key Components in Detail

### `AgentManager` (`core/agents/manager.py`)

This class is the heart of the distributed system on the Core side.

-   `_agents`: A dictionary that stores the state of all registered agents, keyed by `agent_id`.
-   `_queues`: A dictionary of `asyncio.Queue` objects, keyed by a `(host, port)` tuple for each target. This allows multiple agents to service the same target, pulling from a shared queue.
-   `register_agent()`: Handles new agent registrations.
-   `enqueue_test_case()`: Called by the orchestrator to add work to a queue.
-   `request_work()`: Called by the agent's polling request to get work from a queue.

```python
# core/agents/manager.py - Simplified Logic

class AgentManager:
    async def enqueue_test_case(self, target_host: str, target_port: int, work: AgentWorkItem):
        """Queue a test case for agents matching the given target."""
        key = (target_host, target_port)
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
        
        queue = self._queues[key]
        await queue.put(work)

    async def request_work(self, agent_id: str) -> Optional[AgentWorkItem]:
        """Return the next work item for an agent if available."""
        agent = self._agents.get(agent_id)
        if not agent or agent.status != "active":
            return None

        queue = self._queues.get((agent.target_host, agent.target_port))
        if not queue or queue.empty():
            return None

        work = await queue.get()
        return work
```

### Agent (`agent/main.py`)

The agent is a much simpler process. Its main logic is in the `poll_for_work` function.

-   It starts by calling `register()` to make itself known to the Core.
-   It then enters a `while True` loop.
-   Inside the loop, it calls `request_work()` to poll the Core.
-   If it receives work, it calls `execute_test_case()`.
-   `execute_test_case()` connects to the target, sends the data, and monitors the result.
-   Finally, it calls `submit_result()` to send the outcome back to the Core.
-   It sleeps for the configured poll interval before repeating the loop.

This design allows the Core to manage the complex logic of fuzzing, while the agent remains a simple, focused "worker" responsible only for execution and reporting.
