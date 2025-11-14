# Fuzzing Engine: Developer Documentation

## 5. Corpus and Agents

Beyond the core fuzzing loop, the engine has two important subsystems that support its operation: the **Corpus Store** for managing test cases and the **Agent Manager** for distributed fuzzing.

### Corpus Management

The "corpus" refers to the collection of all test cases that the fuzzer uses and discovers. This includes the initial seeds and any crash-inducing test cases found during a fuzzing session. The `CorpusStore` (`core/corpus/store.py`) is responsible for managing this data.

#### Seeds

Seeds are the initial inputs for the fuzzer. They are typically a small set of valid messages provided by a protocol plugin. The `CorpusStore` handles the storage of these seeds on disk.

-   **Adding Seeds**: When a session is created, the orchestrator loads the seeds from the plugin and adds them to the corpus store using `add_seed`. The store deduplicates seeds by hashing their content.
-   **Retrieving Seeds**: During the fuzzing loop, the engine retrieves the seed data from the store's in-memory cache for use in mutations.

```python
# core/corpus/store.py

class CorpusStore:
    # ...
    def add_seed(self, data: bytes, metadata: Optional[Dict] = None) -> str:
        """
        Add a new seed to the corpus
        """
        seed_id = hashlib.sha256(data).hexdigest()

        if seed_id in self._seed_cache:
            return seed_id

        # Write seed file and metadata
        # ...
        self._seed_cache[seed_id] = data
        return seed_id

    def get_seed(self, seed_id: str) -> Optional[bytes]:
        """Retrieve a seed by ID"""
        return self._seed_cache.get(seed_id)
```

#### Findings

When a test case causes a crash, hang, or other anomaly, it is considered a "finding." The `FuzzOrchestrator` reports this to the `CrashReporter`, which in turn instructs the `CorpusStore` to save the finding.

The `save_finding` method stores two key pieces of information:
1.  `input.bin`: The raw bytes of the test case that caused the crash.
2.  `report.json`: A JSON file containing detailed metadata about the crash, including the session ID, time, and any metrics collected.

This ensures that every crash is fully reproducible and available for later analysis.

### Distributed Fuzzing with Agents

To scale up the fuzzing process, the engine supports distributing the workload to multiple remote **agents**. An agent is a separate process, potentially running on a different machine, that is responsible for executing test cases against a specific target.

The `AgentManager` (`core/agents/manager.py`) is the central coordinator for this distributed system.

#### How it Works

1.  **Registration**: When an agent starts, it registers itself with the main fuzzer application, specifying the target host and port it is configured to test.
2.  **Work Queueing**: When a fuzzing session is configured to run in `AGENT` mode, the `FuzzOrchestrator` does not execute the test cases itself. Instead, it generates a test case and enqueues it as a work item for the appropriate target via the `AgentManager`.
3.  **Work Request**: Agents periodically poll the `AgentManager`, requesting work. If a test case is available in the queue for the agent's target, the `AgentManager` sends it to the agent.
4.  **Execution and Results**: The agent executes the test case against its target and sends the result (e.g., `PASS`, `CRASH`) back to the `FuzzOrchestrator`, which then records the outcome.

This architecture allows the main fuzzer process to focus on the computationally expensive tasks of test case generation and mutation, while offloading the I/O-bound work of sending data and waiting for responses to multiple agents. This enables a much higher throughput of test cases per second.

```python
# core/agents/manager.py

class AgentManager:
    # ...
    async def enqueue_test_case(self, target_host: str, target_port: int, work: AgentWorkItem) -> None:
        """Queue a test case for agents matching the given target"""
        key = (target_host, target_port)
        queue = self._queues[key]
        await queue.put(work)

    async def request_work(self, agent_id: str, timeout: float = 0.5) -> Optional[AgentWorkItem]:
        """Return the next work item for an agent if available"""
        agent = self._agents.get(agent_id)
        # ...
        queue = self._queues[(agent.target_host, agent.target_port)]
        try:
            work = await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        # ...
        return work
```
