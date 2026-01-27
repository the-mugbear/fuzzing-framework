# 6. A Developer's First Debug Session

**Objective:** This guide will walk you through setting up a complete, end-to-end debugging environment. By the end, you will be able to create a simple protocol plugin, run the fuzzer, and step through the core fuzzing logic in `orchestrator.py` using VSCode's debugger.

**Prerequisites:**
*   Docker and `docker-compose` installed.
*   Visual Studio Code with the official Python extension.
*   A local clone of the project repository.

---

## Step 1: Launch the Development Environment

The project includes a `docker-compose.yml` file configured for local development. It defines three key services:
*   `core`: The main fuzzer application (API, orchestrator, UI).
*   `agent`: A remote worker that executes test cases.
*   `target`: A simple TCP echo server to test against.

The `core` service is configured with `debugpy` to allow a remote Python debugger to attach to the process.

To start the environment, run the following command from the project root:

```bash
docker-compose up --build
```

You should see logs from all three services. The `core` service will log a message indicating the debugger is listening on port 5678:

```
core_1    | INFO:     debugpy is listening on port 5678
```

You can now access the web UI at [http://localhost:8000](http://localhost:8000).

## Step 2: Create a "Simple Echo" Plugin

Protocol plugins are the heart of the fuzzer. Let's create a minimal plugin to test the `target` echo server.

Create a new file named `core/plugins/simple_echo.py` with the following content:

```python
"""
A simple echo protocol for debugging and demonstration.
Sends a message and expects to receive the same data back.
"""
from typing import Optional

from pydantic import BaseModel, Field

# 1. Define the data model for the protocol message
class EchoMessage(BaseModel):
    data: bytes = Field(..., description="The data to be echoed")

# 2. Define the protocol plugin object
class ProtocolPlugin:
    # Human-readable name and description
    name: str = "Simple Echo"
    description: str = "Sends data to a TCP server and expects it back."

    # The data model for a single message
    data_model: type = EchoMessage

    # A simple seed to start fuzzing from
    seeds: list[bytes] = [ b"HELLO_WORLD" ]

    # The transport protocol (TCP or UDP)
    transport: str = "tcp"

    # 3. (Optional) A function to validate server responses
    def validate_response(self, sent: bytes, received: Optional[bytes]) -> bool:
        """
        Validates that the server's response matches the data sent.
        - The fuzzer calls this after every test case.
        - Returning `True` marks the test as 'passed'.
        - Returning `False` marks it as 'failed'.
        """
        if received is None:
            return False # No response is a failure
        return sent == received

# Required: The fuzzer looks for a variable named `protocol_plugin`
protocol_plugin = ProtocolPlugin()
```

The fuzzer's plugin loader will automatically detect and load this new file.

## Step 3: Configure and Attach the VSCode Debugger

Now, let's attach VSCode's debugger to the `core` service running in Docker.

1.  **Open the "Run and Debug" Panel** in VSCode (usually on the left-hand side, with a play button and bug icon).
2.  **Create a `launch.json` file** if you don't have one. Select "Python" from the dropdown, and then "Remote Attach".
3.  **Configure `launch.json`**: Replace the contents of `.vscode/launch.json` with the following configuration:

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
    *   `"port": 5678"` matches the port `debugpy` is listening on.
    *   `pathMappings` is crucial: it tells the debugger how to map file paths on your local machine (`${workspaceFolder}`) to the corresponding paths inside the Docker container (`/app`).
    *   `"justMyCode": false` ensures the debugger can step into library code if needed.

4.  **Launch the Debugger**: Press **F5** or click the green play button next to "Python: Attach to Fuzzer Core".

The VSCode status bar should turn orange, indicating a successful debugger connection.

## Step 4: Set Breakpoints and Start a Session

With the debugger attached, you can now set breakpoints and inspect the code live.

1.  **Set a Breakpoint**: Open `core/engine/orchestrator.py` and find the `_run_fuzzing_loop` method. Place a breakpoint at the very beginning of this method. This is the entry point for the main fuzzing loop.

2.  **Start a Fuzzing Session**:
    *   Navigate to the web UI at [http://localhost:8000](http://localhost:8000).
    *   Click on "New Session".
    *   **Protocol**: Select `simple_echo` from the dropdown.
    *   **Target Host**: Enter `target` (the name of our docker service).
    *   **Target Port**: Enter `1337`.
    *   Click "Start Session".

3.  **Hit the Breakpoint**: The execution in the `core` container will immediately pause at your breakpoint in `_run_fuzzing_loop`. You can now:
    *   **Inspect variables**: Hover over variables like `session_context` to see their current values.
    *   **Step through code**: Use the debugger controls (F10 to step over, F11 to step into) to walk through the fuzzing lifecycle.
    *   **Examine the call stack**: See how the orchestrator was called from the API layer.

## Step 5: Explore and Experiment

Congratulations! You have a fully operational debug environment. From here, you can explore the entire fuzzing process:

*   **Mutation**: Set a breakpoint in `core/engine/mutators.py` to see how a seed is transformed into a new test case.
*   **Execution**: Follow the code path into `core/engine/transport.py` to see how the data is sent over the network.
*   **Response Validation**: Place a breakpoint in our `simple_echo.py` plugin's `validate_response` function to inspect the data sent and received.

This setup is the key to understanding the fuzzer's internal mechanics and is the recommended starting point for developing new features or fixing bugs.
