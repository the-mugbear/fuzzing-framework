# 6. A Developer's First Debug Session (Orchestrated Focus)

**Objective:** This guide will walk you through setting up a complete debugging environment for orchestrated fuzzing sessions. By the end, you will be able to create a minimal protocol plugin, run the fuzzer, and step through the core fuzzing logic, including `bootstrap` stages and heartbeats, using VSCode's debugger.

**Prerequisites:**
*   Docker and `docker-compose` installed.
*   Visual Studio Code with the official Python extension.
*   A local clone of the project repository.

---

## Step 1: Launch the Development Environment

The project includes a `docker-compose.yml` file configured for local development. It defines key services:
*   `core`: The main fuzzer application (API, orchestrator, UI).
*   `target`: The `feature_showcase_server`, a robust target that supports the `orchestrated_example` plugin.

The `core` service is configured with `debugpy` to allow a remote Python debugger to attach. To start the environment, run:

```bash
docker-compose up --build
```

You should see logs indicating `debugpy` is listening on port 5678:

```
core_1    | INFO:     debugpy is listening on port 5678
```

Access the web UI at [http://localhost:8000](http://localhost:8000).

## Step 2: Prepare the `orchestrated_example` Plugin

We'll use the built-in `orchestrated_example` plugin to debug an orchestrated session. This plugin demonstrates:
-   A `bootstrap` stage to perform a handshake.
-   `exports` to capture a session ID from the handshake response.
-   `from_context` to inject the session ID into the `fuzz_target` messages.
-   A `heartbeat` to keep the connection alive.

You don't need to create a new file, as this plugin is already part of `core/plugins/orchestrated_example.py`.

## Step 3: Configure and Attach the VSCode Debugger

1.  **Open the "Run and Debug" Panel** in VSCode.
2.  **Create/Update `launch.json`**: Ensure your `.vscode/launch.json` has the following configuration:

    ```json
    {
        "version": "0.2.0",
        "configurations": [
            {
                "name": "Python: Attach to Fuzzer Core",
                "type": "python",
                "request": "attach",
                "connect": {
                    "host": "localhost",
                    "port": 5678
                },
                "pathMappings": [
                    {
                        "localRoot": "${workspaceFolder}",
                        "remoteRoot": "/app"
                    }
                ],
                "justMyCode": false
            }
        ]
    }
    ```
    *   `"port": 5678"` matches the port `debugpy` is listening on in the `core` container.
    *   `pathMappings` is crucial for mapping local files to Docker container paths.
    *   `"justMyCode": false` allows stepping into library code.

3.  **Launch the Debugger**: Press **F5** or click the green play button. The VSCode status bar should turn orange upon successful connection.

## Step 4: Set Breakpoints for Orchestration

Now, set strategic breakpoints to understand the orchestrated session lifecycle.

1.  **Orchestrator Entry Point**: Open `core/engine/orchestrator.py` and set a breakpoint at the beginning of `_run_fuzzing_loop`.
2.  **Stage Execution**: Open `core/engine/stage_runner.py` and set a breakpoint at the beginning of `run_bootstrap_stages`. This is where the handshake is performed.
3.  **Context Injection**: In `core/engine/orchestrator.py`, set a breakpoint within the `_inject_context_values` method to observe how session data is injected into test cases.
4.  **Heartbeat Logic**: Open `core/engine/heartbeat_scheduler.py` and set a breakpoint at the beginning of `_heartbeat_loop` to see the keep-alive mechanism in action.
5.  **Plugin Logic**: Open `core/plugins/orchestrated_example.py` and set a breakpoint in its `data_model`'s `from_context` field definition or in the `exports` definition to see how values are handled.

## Step 5: Start an Orchestrated Session

1.  Navigate to the web UI at [http://localhost:8000](http://localhost:8000).
2.  Click on "New Session".
3.  **Protocol**: Select `orchestrated_example` from the dropdown.
4.  **Target Host**: Enter `target`.
5.  **Target Port**: Enter `9999`.
6.  Click "Start Session".

## Step 6: Step Through and Observe

Your debugger will now hit the breakpoints.

-   **Follow `_run_fuzzing_loop`**: Observe how the `FuzzOrchestrator` sets up the session.
-   **Step into `run_bootstrap_stages`**: See the `bootstrap` process, how messages are sent, and how `exports` extract data into the `ProtocolContext`.
-   **Observe Context Injection**: In `_inject_context_values`, you'll see the session ID (or other exported values) being dynamically placed into the fuzzing message.
-   **Trace Heartbeats**: The `_heartbeat_loop` breakpoint will show the periodic sending of keep-alive messages.

This setup is invaluable for understanding the complex interactions within an orchestrated session and debugging issues related to handshakes, token management, or connection stability.

## Debugging Agent-Side Orchestration (Advanced)

If you need to debug an orchestrated session running on a remote agent:

1.  **Enable Debugpy in `Dockerfile.agent`**: Modify `Dockerfile.agent` to install `debugpy` and start the agent with it enabled.
2.  **Expose Debug Port**: Add a port mapping for the agent's debug port (e.g., `5679:5679`) to the `agent` service in `docker-compose.yml`.
3.  **Create New `launch.json` Config**: Add a new configuration in `launch.json` similar to the Core's, but pointing to the agent's debug port and mapping its local root (`/app`) accordingly.
4.  **Attach to Agent**: Start the agent service with the debugpy port exposed, then attach the debugger using your new configuration. The agent will then execute the orchestrated session, allowing you to debug its local `StageRunner`, `ConnectionManager`, etc.