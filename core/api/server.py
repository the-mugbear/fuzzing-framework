"""
FastAPI server for the fuzzer Core

Provides REST API for:
- Session management
- Protocol plugin management
- Corpus management
- Agent communication
- Results and findings
"""
import random
from datetime import datetime
from typing import List, Optional

import structlog
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from core.agents.manager import agent_manager
from core.config import settings
from core.logging import setup_logging
from core.corpus.store import CorpusStore
from core.engine.mutators import (
    ArithmeticMutator,
    BitFlipMutator,
    ByteFlipMutator,
    HavocMutator,
    InterestingValueMutator,
    MutationEngine,
)
from core.engine.orchestrator import orchestrator
from core.engine.protocol_parser import ProtocolParser
from core.engine.structure_mutators import StructureAwareMutator
from core.models import (
    AgentTestResult,
    AgentWorkItem,
    ExecutionHistoryResponse,
    FuzzConfig,
    FuzzSession,
    OneOffTestRequest,
    OneOffTestResult,
    PreviewField,
    PreviewRequest,
    PreviewResponse,
    ProtocolPlugin,
    ReplayRequest,
    ReplayResponse,
    StateMachineInfo,
    StateTransition,
    TestCaseExecutionRecord,
    TestCasePreview,
)
from core.plugin_loader import plugin_manager

setup_logging("core-api")
logger = structlog.get_logger()

# Create FastAPI app
app = FastAPI(
    title="Proprietary Protocol Fuzzer",
    description="Portable, extensible fuzzing framework for proprietary network protocols",
    version="0.1.0",
)

# CORS middleware for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

corpus_store = CorpusStore()


docs_path = settings.project_root / "docs"
if docs_path.exists():
    app.mount("/docs", StaticFiles(directory=docs_path), name="docs")

guides_path = settings.project_root / "core" / "ui" / "guides"
if guides_path.exists():
    app.mount("/guides", StaticFiles(directory=guides_path), name="guides")


@app.get("/")
async def root():
    """Serve the web UI"""
    ui_path = settings.project_root / "core" / "ui" / "index.html"
    if ui_path.exists():
        return FileResponse(ui_path)
    return {
        "service": "Proprietary Protocol Fuzzer",
        "version": "0.1.0",
        "status": "operational",
    }


# ========== Protocol Plugin Endpoints ==========


@app.get("/api/plugins", response_model=List[str])
async def list_plugins():
    """List all available protocol plugins"""
    try:
        plugins = plugin_manager.discover_plugins()
        return plugins
    except Exception as e:
        logger.error("failed_to_list_plugins", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/plugins/{plugin_name}", response_model=ProtocolPlugin)
async def get_plugin(plugin_name: str):
    """Get details of a specific protocol plugin"""
    try:
        plugin = plugin_manager.load_plugin(plugin_name)
        return plugin
    except Exception as e:
        logger.error("failed_to_load_plugin", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=404, detail=f"Plugin not found: {plugin_name}")


@app.post("/api/plugins/{plugin_name}/reload", response_model=ProtocolPlugin)
async def reload_plugin(plugin_name: str):
    """Reload a protocol plugin (useful for development)"""
    try:
        plugin = plugin_manager.reload_plugin(plugin_name)
        logger.info("plugin_reloaded", plugin=plugin_name)
        return plugin
    except Exception as e:
        logger.error("failed_to_reload_plugin", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mutators")
async def list_mutators():
    """Expose available mutators for the UI"""
    return {"mutators": MutationEngine.available_mutators()}


@app.post("/api/plugins/{plugin_name}/preview", response_model=PreviewResponse)
async def preview_test_cases(plugin_name: str, request: PreviewRequest):
    """
    Generate test case previews using actual fuzzer logic.

    This ensures UI shows exactly what the fuzzer will generate,
    with proper handling of derived fields (size, checksums, etc.).
    """
    try:
        plugin = plugin_manager.load_plugin(plugin_name)
        data_model = plugin.data_model
        blocks = data_model.get('blocks', [])
        seeds = data_model.get('seeds', [])

        parser = ProtocolParser(data_model)
        previews = []

        # Get state model for transition detection
        state_model = plugin.state_model if plugin.state_model else {}

        if request.mode == "seeds":
            # Show actual seeds
            for i, seed in enumerate(seeds[:request.count]):
                preview = _build_preview(
                    i, seed, parser, blocks,
                    mode="baseline",
                    state_model=state_model
                )
                previews.append(preview)

        elif request.mode == "mutations":
            # Generate both structure-aware and byte-level mutations
            if not seeds:
                raise HTTPException(status_code=400, detail="Protocol has no seeds defined")

            structure_mutator = StructureAwareMutator(data_model)

            # Initialize byte-level mutation engine
            byte_mutators = {
                "bitflip": BitFlipMutator(),
                "byteflip": ByteFlipMutator(),
                "arithmetic": ArithmeticMutator(),
                "interesting": InterestingValueMutator(),
                "havoc": HavocMutator()
            }

            # Generate mix of structure-aware and byte-level mutations
            for i in range(request.count):
                seed = random.choice(seeds)

                # Alternate between structure-aware and byte-level
                if i % 2 == 0:
                    # Structure-aware mutation
                    mutated = structure_mutator.mutate(seed)

                    # Try to determine which field was mutated by comparing
                    mutated_field = _detect_mutated_field(seed, mutated, parser, blocks)

                    preview = _build_preview(
                        i, mutated, parser, blocks,
                        mode="mutated",
                        mutation_type="structure_aware",
                        mutators_used=["structure_aware"],
                        description=f"Structure-aware mutation respecting protocol grammar{f' (field: {mutated_field})' if mutated_field else ''}",
                        state_model=state_model
                    )
                else:
                    # Byte-level mutation
                    mutator_name = random.choice(list(byte_mutators.keys()))
                    mutator = byte_mutators[mutator_name]
                    mutated = mutator.mutate(seed)

                    description = _get_mutator_description(mutator_name)

                    preview = _build_preview(
                        i, mutated, parser, blocks,
                        mode="mutated",
                        mutation_type="byte_level",
                        mutators_used=[mutator_name],
                        description=description,
                        state_model=state_model
                    )

                previews.append(preview)

        elif request.mode == "field_focus":
            # Generate mutations focused on specific field
            if not request.focus_field:
                raise HTTPException(status_code=400, detail="focus_field required for field_focus mode")

            if not seeds:
                raise HTTPException(status_code=400, detail="Protocol has no seeds defined")

            mutator = StructureAwareMutator(data_model)

            for i in range(request.count):
                seed = random.choice(seeds)
                mutated = mutator.mutate(seed)
                preview = _build_preview(
                    i, mutated, parser, blocks,
                    mode="mutated",
                    focus_field=request.focus_field,
                    state_model=state_model
                )
                previews.append(preview)

        else:
            raise HTTPException(status_code=400, detail=f"Invalid mode: {request.mode}")

        # Build state machine info if protocol has state model
        state_machine_info = _build_state_machine_info(plugin)

        return PreviewResponse(
            protocol=plugin_name,
            previews=previews,
            state_machine=state_machine_info
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("preview_generation_failed", plugin=plugin_name, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


def _build_preview(
    preview_id: int,
    data: bytes,
    parser: ProtocolParser,
    blocks: List[dict],
    mode: str = "baseline",
    mutation_type: Optional[str] = None,
    mutators_used: List[str] = None,
    description: Optional[str] = None,
    focus_field: Optional[str] = None,
    state_model: dict = None
) -> TestCasePreview:
    """
    Build a test case preview from binary data.

    Args:
        preview_id: Preview identifier
        data: Test case bytes
        parser: Protocol parser instance
        blocks: Block definitions from data_model
        mode: "baseline" or "mutated"
        mutation_type: "structure_aware" | "byte_level"
        mutators_used: List of mutator names
        description: Human-readable description
        focus_field: Optional field name that was mutated
        state_model: Protocol state machine model

    Returns:
        TestCasePreview with parsed fields and state info
    """
    try:
        # Parse the data into fields
        fields_dict = parser.parse(data)
    except Exception as e:
        logger.warning("preview_parse_failed", error=str(e))
        # If parsing fails, create minimal preview
        fields_dict = {}

    # Build field list with metadata
    preview_fields = []

    for block in blocks:
        field_name = block['name']
        field_value = fields_dict.get(field_name, block.get('default', ''))

        # Convert value to hex
        if isinstance(field_value, bytes):
            hex_str = field_value.hex().upper()
            display_value = field_value.decode('latin-1', errors='replace')
        elif isinstance(field_value, int):
            hex_str = f"{field_value:X}".zfill(2)
            display_value = field_value
        elif isinstance(field_value, str):
            hex_str = field_value.encode('utf-8').hex().upper()
            display_value = field_value
        else:
            hex_str = str(field_value)
            display_value = field_value

        preview_field = PreviewField(
            name=field_name,
            value=display_value,
            hex=hex_str,
            type=block.get('type', 'unknown'),
            mutable=block.get('mutable', True),
            computed=block.get('is_size_field', False),
            references=block.get('size_of') if block.get('is_size_field') else None,
            mutated=(field_name == focus_field) if focus_field else False
        )
        preview_fields.append(preview_field)

    # Create hex dump
    hex_dump = data.hex().upper()

    # Determine message type and transition info if state model exists
    message_type = None
    valid_in_state = None
    causes_transition = None

    if state_model and state_model.get("transitions"):
        # Find command field to identify message type
        command_value = fields_dict.get("command")

        if command_value is not None:
            # Map command value to message type
            for block in blocks:
                if block.get("name") == "command" and "values" in block:
                    message_type = block["values"].get(command_value)
                    break

            if message_type:
                # Find which state this message is valid in and what transition it causes
                transitions = state_model.get("transitions", [])

                # Find the first transition that matches this message type
                for trans in transitions:
                    if trans.get("message_type") == message_type:
                        valid_in_state = trans.get("from")
                        to_state = trans.get("to")
                        causes_transition = f"{valid_in_state} → {to_state}"
                        break

    return TestCasePreview(
        id=preview_id,
        mode=mode,
        mutation_type=mutation_type,
        mutators_used=mutators_used or [],
        description=description,
        focus_field=focus_field,
        hex_dump=hex_dump,
        total_bytes=len(data),
        fields=preview_fields,
        message_type=message_type,
        valid_in_state=valid_in_state,
        causes_transition=causes_transition
    )


def _get_mutator_description(mutator_name: str) -> str:
    """Get human-readable description of what a mutator does"""
    descriptions = {
        "bitflip": "Bit flipping: Randomly flips individual bits in the message, potentially breaking field boundaries and creating invalid values",
        "byteflip": "Byte flipping: Replaces random bytes with random values, ignoring protocol structure",
        "arithmetic": "Arithmetic: Adds/subtracts small integers to 4-byte sequences, may corrupt length fields or counters",
        "interesting": "Interesting values: Injects boundary values (0, 255, 65535, etc.) at random positions",
        "havoc": "Havoc: Aggressive random mutations including insertions, deletions, and bit flips throughout the message"
    }
    return descriptions.get(mutator_name, f"Byte-level mutation: {mutator_name}")


def _detect_mutated_field(original: bytes, mutated: bytes, parser: ProtocolParser, blocks: List[dict]) -> Optional[str]:
    """
    Try to detect which field was mutated by comparing original and mutated messages.

    Returns the name of the field that was likely mutated, or None if unclear.
    """
    try:
        original_fields = parser.parse(original)
        mutated_fields = parser.parse(mutated)

        # Compare each field
        for block in blocks:
            field_name = block['name']
            if field_name in original_fields and field_name in mutated_fields:
                orig_val = original_fields[field_name]
                mut_val = mutated_fields[field_name]

                # Skip computed fields (they change as a result of other changes)
                if block.get('is_size_field'):
                    continue

                if orig_val != mut_val:
                    return field_name

    except Exception:
        # If parsing fails, we can't determine the field
        pass

    return None


def _build_state_machine_info(plugin: ProtocolPlugin) -> Optional[StateMachineInfo]:
    """
    Build state machine information from protocol plugin.

    Args:
        plugin: Protocol plugin with state_model

    Returns:
        StateMachineInfo if protocol has state model, None otherwise
    """
    state_model = plugin.state_model
    if not state_model:
        return StateMachineInfo(has_state_model=False)

    transitions_list = state_model.get("transitions", [])
    if not transitions_list:
        return StateMachineInfo(has_state_model=False)

    # Build message type to command mapping from data model
    message_type_to_command = {}
    command_block = None

    for block in plugin.data_model.get("blocks", []):
        if block.get("name") == "command" and "values" in block:
            command_block = block
            break

    if command_block:
        # Invert the values dict: "CONNECT" -> 0x01
        for cmd_value, cmd_name in command_block["values"].items():
            message_type_to_command[cmd_name] = cmd_value

    # Convert transitions to Pydantic models
    transitions = []
    for trans in transitions_list:
        transitions.append(StateTransition(
            **{
                "from": trans.get("from"),
                "to": trans.get("to"),
                "message_type": trans.get("message_type"),
                "trigger": trans.get("trigger"),
                "expected_response": trans.get("expected_response")
            }
        ))

    return StateMachineInfo(
        has_state_model=True,
        initial_state=state_model.get("initial_state"),
        states=state_model.get("states", []),
        transitions=transitions,
        message_type_to_command=message_type_to_command
    )


# ========== Session Management Endpoints ==========


@app.post("/api/sessions", response_model=FuzzSession)
async def create_session(config: FuzzConfig):
    """Create a new fuzzing session"""
    try:
        session = await orchestrator.create_session(config)
        logger.info("session_created_via_api", session_id=session.id)
        return session
    except Exception as e:
        logger.error("failed_to_create_session", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions", response_model=List[FuzzSession])
async def list_sessions():
    """List all fuzzing sessions"""
    return orchestrator.list_sessions()


@app.get("/api/sessions/{session_id}", response_model=FuzzSession)
async def get_session(session_id: str):
    """Get details of a specific session"""
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@app.post("/api/sessions/{session_id}/start")
async def start_session(session_id: str):
    """Start a fuzzing session"""
    success = await orchestrator.start_session(session_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to start session")
    return {"status": "started", "session_id": session_id}


@app.post("/api/sessions/{session_id}/stop")
async def stop_session(session_id: str):
    """Stop a fuzzing session"""
    success = await orchestrator.stop_session(session_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to stop session")
    return {"status": "stopped", "session_id": session_id}


@app.get("/api/sessions/{session_id}/stats")
async def get_session_stats(session_id: str):
    """Get session statistics"""
    stats = orchestrator.get_session_stats(session_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Session not found")
    return stats


@app.get("/api/sessions/{session_id}/state_coverage")
async def get_session_state_coverage(session_id: str):
    """
    Get state coverage for stateful fuzzing session.

    Returns state machine coverage including:
    - Which states have been visited
    - Which transitions have been taken
    - Coverage percentages

    Returns 404 if session not found or not using stateful fuzzing.
    """
    coverage = orchestrator.get_state_coverage(session_id)
    if not coverage:
        # Check if session exists
        session = orchestrator.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        else:
            raise HTTPException(
                status_code=400,
                detail="Session is not using stateful fuzzing"
            )
    return coverage


# ========== Test Case Correlation & Replay ==========


@app.get("/api/sessions/{session_id}/execution_history", response_model=ExecutionHistoryResponse)
async def get_execution_history(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    since: Optional[str] = None,
    until: Optional[str] = None
):
    """
    Get execution history for test case correlation.

    Query parameters:
    - limit: Number of records to return (default 100, max 1000)
    - offset: Skip N records for pagination
    - since: ISO 8601 timestamp - filter records after this time
    - until: ISO 8601 timestamp - filter records before this time

    Returns recent test case executions with full details for correlation.
    """
    # Check session exists
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Parse datetime filters
    since_dt = None
    until_dt = None

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid 'since' timestamp: {since}")

    if until:
        try:
            until_dt = datetime.fromisoformat(until.replace('Z', '+00:00'))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid 'until' timestamp: {until}")

    # Enforce max limit
    if limit > 1000:
        limit = 1000

    # Get execution history
    executions = orchestrator.get_execution_history(
        session_id,
        limit=limit,
        offset=offset,
        since=since_dt,
        until=until_dt
    )

    # Get total count (unfiltered)
    all_executions = orchestrator.execution_history.get(session_id, [])
    total_count = len(all_executions)

    return ExecutionHistoryResponse(
        session_id=session_id,
        total_count=total_count,
        returned_count=len(executions),
        executions=executions
    )


@app.get("/api/sessions/{session_id}/execution/at_time", response_model=TestCaseExecutionRecord)
async def get_execution_at_time(session_id: str, timestamp: str):
    """
    Find which test case was executing at a specific timestamp.

    This is the key correlation endpoint - use it to answer:
    "What was the fuzzer sending when I saw the target crash at 10:23:45?"

    Query parameter:
    - timestamp: ISO 8601 timestamp (e.g., "2025-11-10T10:23:45Z")

    Returns the test case that was being executed at that moment.
    """
    # Check session exists
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Parse timestamp
    try:
        timestamp_dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp format: {timestamp}. Use ISO 8601 format (e.g., 2025-11-10T10:23:45Z)")

    # Find execution at this time
    execution = orchestrator.find_execution_at_time(session_id, timestamp_dt)

    if not execution:
        raise HTTPException(
            status_code=404,
            detail=f"No execution found at {timestamp}. The timestamp may be outside the recorded range, or the execution may have been rotated out of history."
        )

    return execution


@app.get("/api/sessions/{session_id}/execution/{sequence_number}", response_model=TestCaseExecutionRecord)
async def get_execution_by_sequence(session_id: str, sequence_number: int):
    """
    Get a specific test case execution by sequence number.

    Use this to retrieve full details of test case #N, including:
    - Complete payload (base64 encoded)
    - Timestamps, duration, result
    - Protocol state and message type
    - Response preview
    """
    # Check session exists
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Find execution
    execution = orchestrator.find_execution_by_sequence(session_id, sequence_number)

    if not execution:
        raise HTTPException(
            status_code=404,
            detail=f"Execution #{sequence_number} not found. It may have been rotated out of history (keeping last 5000)."
        )

    return execution


@app.post("/api/sessions/{session_id}/execution/replay", response_model=ReplayResponse)
async def replay_executions(session_id: str, request: ReplayRequest):
    """
    Replay test cases by sequence number.

    This re-sends the exact same payloads to the target, useful for:
    - Confirming a suspected crash-inducing test case
    - Investigating a range of test cases (time band replay)
    - Manual observation with slowed-down replay

    Request body:
    - sequence_numbers: List of sequence numbers to replay (e.g., [845, 846, 847])
    - delay_ms: Milliseconds to wait between replays (default 0)

    Example: Replay test cases 845-850 with 1 second between each:
    {
      "sequence_numbers": [845, 846, 847, 848, 849, 850],
      "delay_ms": 1000
    }
    """
    # Check session exists
    session = orchestrator.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Validate request
    if not request.sequence_numbers:
        raise HTTPException(status_code=400, detail="sequence_numbers cannot be empty")

    if len(request.sequence_numbers) > 100:
        raise HTTPException(status_code=400, detail="Cannot replay more than 100 test cases at once")

    if request.delay_ms < 0:
        raise HTTPException(status_code=400, detail="delay_ms cannot be negative")

    # Replay executions
    results = await orchestrator.replay_executions(
        session_id,
        request.sequence_numbers,
        delay_ms=request.delay_ms
    )

    return ReplayResponse(
        replayed_count=len(results),
        results=results
    )


# ========== Ad-hoc Testing ==========


@app.post("/api/tests/execute", response_model=OneOffTestResult)
async def execute_test(request: OneOffTestRequest):
    """Execute a single test case without creating a session"""
    try:
        result = await orchestrator.execute_one_off(request)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ========== Corpus Management Endpoints ==========


@app.get("/api/corpus/seeds")
async def list_seeds():
    """List all seed IDs in the corpus"""
    return {"seed_ids": corpus_store.get_seed_ids()}


@app.post("/api/corpus/seeds")
async def upload_seed(file: UploadFile = File(...), metadata: Optional[str] = None):
    """Upload a new seed to the corpus"""
    try:
        data = await file.read()
        import json

        meta = json.loads(metadata) if metadata else {}
        meta["filename"] = file.filename

        seed_id = corpus_store.add_seed(data, metadata=meta)
        return {"seed_id": seed_id, "size": len(data)}
    except Exception as e:
        logger.error("failed_to_upload_seed", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/corpus/stats")
async def get_corpus_stats():
    """Get corpus statistics"""
    return corpus_store.get_corpus_stats()


@app.get("/api/corpus/findings")
async def list_findings(session_id: Optional[str] = None):
    """List all findings (crashes, hangs, anomalies)"""
    findings = corpus_store.list_findings(session_id)
    return {"findings": findings, "count": len(findings)}


@app.get("/api/corpus/findings/{finding_id}")
async def get_finding(finding_id: str):
    """Get details of a specific finding"""
    result = corpus_store.load_finding(finding_id)
    if not result:
        raise HTTPException(status_code=404, detail="Finding not found")

    crash_report, test_case_data = result
    return {
        "report": crash_report,
        "reproducer_size": len(test_case_data),
        "reproducer_sha256": crash_report.id,
    }


# ========== Agent Communication Endpoints ==========


@app.post("/api/agents/register")
async def register_agent(agent_info: dict):
    """Register a new agent"""
    required_fields = {"agent_id", "hostname", "target_host", "target_port"}
    missing = [field for field in required_fields if field not in agent_info]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing fields: {', '.join(missing)}")

    status = agent_manager.register_agent(
        agent_id=agent_info["agent_id"],
        hostname=agent_info["hostname"],
        target_host=agent_info["target_host"],
        target_port=int(agent_info["target_port"]),
    )
    return status


@app.post("/api/agents/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: str, status: dict):
    """Agent heartbeat and status update"""
    updated = agent_manager.heartbeat(
        agent_id,
        cpu_usage=status.get("cpu_usage", 0.0),
        memory_usage_mb=status.get("memory_usage_mb", 0.0),
        active_tests=status.get("active_tests", 0),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not registered")
    return {"status": "ok"}


@app.get("/api/agents/{agent_id}/next-case", response_model=Optional[AgentWorkItem])
async def agent_next_case(agent_id: str):
    """Provide the next pending test case for an agent"""
    work = await agent_manager.request_work(agent_id)
    if not work:
        return JSONResponse(status_code=204, content=None)
    return work


@app.post("/api/agents/{agent_id}/result")
async def agent_submit_result(agent_id: str, result: AgentTestResult):
    """Agent submits a test case result"""
    response = await orchestrator.handle_agent_result(agent_id, result)
    return response


# ========== System Endpoints ==========


@app.get("/api/system/health")
async def system_health():
    """System health check"""
    return {
        "status": "healthy",
        "active_sessions": len(orchestrator.active_tasks),
        "total_sessions": len(orchestrator.sessions),
        "corpus_seeds": len(corpus_store.get_seed_ids()),
    }


@app.get("/api/system/config")
async def get_config():
    """Get system configuration (sanitized)"""
    return {
        "plugins_dir": str(settings.plugins_dir),
        "max_concurrent_tests": settings.max_concurrent_tests,
        "mutation_timeout_sec": settings.mutation_timeout_sec,
    }


if __name__ == "__main__":
    import uvicorn

    logger.info(
        "starting_fuzzer_core",
        host=settings.api_host,
        port=settings.api_port,
    )

    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level="info",
    )
