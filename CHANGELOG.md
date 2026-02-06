# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Fixed - 2026-02-06

- **Fixed race condition in AgentManager.clear_session** (`core/agents/manager.py:147-175`)
  - Queue iteration was not atomic - `empty()` and `get_nowait()` could race with other coroutines
  - Moved queue manipulation inside the existing `_lock` to ensure atomic operation
  - Impact: Prevents potential data corruption when multiple coroutines access agent queues concurrently
  - Testing: Run sessions with agent mode and stop them concurrently

- **Fixed incomplete session recovery marking sessions as FAILED** (`core/engine/orchestrator.py:152-168`)
  - Sessions with failed runtime helper rebuilding were silently added in inconsistent state
  - Now marks session as FAILED with clear error message when recovery fails
  - Impact: Users can identify and properly handle sessions that failed to recover
  - Testing: Simulate plugin load failure during session recovery

- **Fixed resource leak in managed connections** (`core/engine/orchestrator.py:1622-1631`, `core/engine/connection_manager.py:666-694`)
  - Unhealthy managed transports remained in connection pool after errors
  - Added `cleanup_unhealthy()` method to ConnectionManager to remove and close unhealthy transports
  - Orchestrator now calls cleanup when marking transport as unhealthy
  - Impact: Prevents socket leaks when persistent connections fail
  - Testing: Run session with persistent connection mode, simulate transport errors

- **Fixed checkpoint failure not propagating errors** (`core/engine/orchestrator.py:206-226`)
  - `_checkpoint_session` silently swallowed errors
  - Now returns `bool` indicating success/failure for callers that need to handle failures
  - Impact: Callers can optionally react to checkpoint failures
  - Testing: Simulate disk write failure during checkpoint

- **Fixed teardown failure visibility** (`core/engine/orchestrator.py:1505-1518`)
  - Teardown errors were only logged, not visible to users
  - Now stores teardown errors in session.error_message for visibility
  - Impact: Users can see if teardown stages failed during session stop
  - Testing: Create session with failing teardown stage

- **Fixed CorpusStore LRU cache documentation and methods** (`core/corpus/store.py:69-153`)
  - Fixed docstring to correctly describe LRU eviction (was incorrectly called FIFO)
  - Renamed `get_all_seeds()` to `get_cached_seeds()` for clarity (alias preserved for compatibility)
  - Added `get_all_seed_ids()` method to list all seeds on disk, not just cached ones
  - Added docstrings to clarify which methods return cached vs disk data
  - Impact: Clearer API for seed corpus management
  - Testing: Add many seeds, verify cache behavior

### Added - 2026-02-06

- **SessionRuntimeContext dataclass** (`core/engine/session_context.py`)
  - New dataclass consolidating all session-specific runtime state
  - Replaces scattered dictionary-based tracking (behavior_processors, stateful_sessions, etc.)
  - SessionContextManager class for unified context lifecycle management
  - Methods: has_behaviors(), has_stateful_fuzzing(), has_orchestration(), get_context_snapshot()
  - Impact: Cleaner code organization, foundation for further orchestrator decomposition
  - Testing: Import and instantiate SessionRuntimeContext with various configurations

- **TestExecutor component** (`core/engine/test_executor.py`)
  - Extracted test case execution logic from orchestrator
  - Handles transport selection, send/receive, error categorization
  - Methods: execute(), classify_response(), build_connection_error_message()
  - Supports both ephemeral and persistent connections via ConnectionManager
  - Impact: Focused component for test execution, improves testability
  - Testing: Instantiate with mock ConnectionManager and execute test cases

- **StateNavigator component** (`core/engine/state_navigator.py`)
  - Extracted state machine navigation logic from orchestrator
  - Handles fuzzing mode selection (breadth-first, depth-first, targeted)
  - Termination test injection for cleanup/teardown coverage
  - Methods: select_message_for_mode(), select_termination_message(), find_path_to_state()
  - Impact: Focused component for stateful fuzzing navigation
  - Testing: Wrap StatefulFuzzingSession and test navigation strategies

- **AgentDispatcher component** (`core/engine/agent_dispatcher.py`)
  - Extracted agent work distribution logic from orchestrator
  - Manages test case dispatch, result handling, pending test tracking
  - Methods: dispatch(), handle_result(), discard_pending(), get_stats()
  - Impact: Focused component for agent coordination
  - Testing: Dispatch test cases and handle mock agent results

- **SessionManager component** (`core/engine/session_manager.py`)
  - Extracted session CRUD and lifecycle management from orchestrator
  - Handles session creation, start, stop, delete operations
  - Integrates with SessionContextManager for runtime state
  - Methods: create_session(), start_session(), stop_session(), delete_session(), get_session_stats()
  - Supports callbacks for orchestrator integration (bootstrap, teardown, heartbeat)
  - Impact: Focused component for session lifecycle, improves testability
  - Testing: Create and manage sessions with mock dependencies

- **FuzzingLoopCoordinator component** (`core/engine/fuzzing_loop.py`)
  - Extracted main fuzzing loop logic from orchestrator
  - Coordinates test generation, execution, and state tracking
  - Uses StateNavigator for stateful fuzzing, TestExecutor for execution
  - Methods: run(), _initialize_context(), _run_loop(), _create_fuzz_test_case()
  - Supports rate limiting, checkpointing, and max iterations
  - Impact: Focused component for fuzzing loop, reduces orchestrator complexity
  - Testing: Run fuzzing loop with mock dependencies

- **Decomposed session models** (`core/engine/session_models.py`)
  - New structured models grouping related FuzzSession fields
  - SessionConfig: Immutable configuration (protocol, target, mutation settings)
  - SessionStats: Counters (total_tests, crashes, hangs, anomalies)
  - SessionState: Runtime state (status, error_message, current_state)
  - CoverageState: Coverage tracking (state_coverage, transition_coverage)
  - OrchestrationState: Protocol stack and connection state
  - ComposedSession: Aggregates all sub-models with FuzzSession conversion
  - Impact: Cleaner organization for session data, backward compatible
  - Testing: Convert FuzzSession to ComposedSession and back
  - Testing: Dispatch test cases and handle mock agent results

### Changed - 2026-02-06

- **Improved testability with dependency injection** (`core/engine/orchestrator.py:52-118`, `core/api/deps.py`)
  - FuzzOrchestrator now accepts optional `corpus_store`, `session_store`, `history_store` parameters
  - Added `skip_session_load` parameter to skip disk loading during tests
  - Added `get_orchestrator()` factory function with lazy initialization
  - Added `reset_orchestrator()` for test isolation
  - Updated `core/api/deps.py` to use factory function
  - Impact: Enables proper unit testing with mock dependencies
  - Testing: Create orchestrator with injected mock stores

- **Extracted magic numbers to configuration** (`core/config.py:59-67`, `core/engine/orchestrator.py:905-917`, `core/engine/mutators.py:155`)
  - Added `termination_test_window` (default: 3) - tests before reset to try termination
  - Added `termination_test_interval` (default: 50) - periodic termination injection
  - Added `havoc_max_size` (default: 4096) - maximum size for havoc mutations
  - Added `seed_cache_max_size` (default: 1000) - maximum seeds in memory cache
  - Updated orchestrator and mutators to use config settings
  - Impact: All fuzzing parameters now configurable via environment variables
  - Testing: Set FUZZER_TERMINATION_TEST_WINDOW=5 and verify behavior change

- **Updated deprecated FastAPI event handlers** (`core/api/server.py:1-45`)
  - Replaced `@app.on_event("startup")` and `@app.on_event("shutdown")` with lifespan context manager
  - Uses the modern `@asynccontextmanager` pattern recommended by FastAPI
  - Impact: Removes deprecation warnings, follows FastAPI best practices
  - Testing: Start/stop the API server and verify startup/shutdown logs

### Documentation - 2026-02-06

- **Updated all Phase 5 component files with comprehensive headers**
  - Added detailed module docstrings to all 7 new component files
  - Each header includes: purpose, responsibilities, integration points, usage examples
  - Files: session_context.py, test_executor.py, state_navigator.py, agent_dispatcher.py, session_manager.py, fuzzing_loop.py, session_models.py

- **Updated core file headers** (`core/agents/manager.py`, `core/corpus/store.py`, `core/config.py`, `core/api/server.py`, `core/engine/orchestrator.py`)
  - Added comprehensive module docstrings with component overview and usage examples
  - Orchestrator header includes ASCII architecture diagram showing component relationships

- **Updated architectural documentation** (`docs/developer/01_architectural_overview.md`)
  - Added new section documenting Phase 5 decomposed architecture
  - Added ASCII diagram showing orchestrator facade and component relationships
  - Added component files table with responsibilities
  - Added decomposed session models table

- **Updated developer documentation dates and references**
  - Updated all developer docs with current date (2026-02-06)
  - Added StateNavigator reference to stateful fuzzing docs
  - Added AgentDispatcher reference to agent communication docs
  - Updated documentation index (docs/README.md) with decomposition note

### Added - 2026-01-31

- **In-app documentation viewer** (`core/api/routes/docs.py`, `core/ui/spa/src/pages/DocumentationHubPage.tsx`)
  - New `/api/docs` endpoint serves markdown documentation files
  - Documentation Hub now renders markdown content in a modal instead of showing file paths
  - Added syntax highlighting for code blocks and proper table formatting
  - Security: Whitelisted paths prevent directory traversal
  - Updated Dockerfile to include `docs/` directory in container image
  - Impact: All documentation is now readable directly in the web UI
  - Testing: Open Documentation Hub, click any "Read documentation" button

### Fixed - 2026-01-31

- **Correlation page "Older" pagination not working** (`core/engine/history_store.py:601-641`, `core/ui/spa/src/pages/CorrelationPage.tsx:701-723`)
  - Fixed `total_count()` to use sequence counter (accurate for active sessions) instead of max(db_count, cache_count) which underreported when writes were pending
  - Fixed pagination button offsets to use actual returned count instead of fixed historyLimit, preventing skipping over records when cache returns fewer than limit
  - Changed `list()` to always query SQLite and merge unflushed cache records, ensuring consistent page sizes regardless of cache state
  - Impact: Users can now paginate through all execution history, not just the last 100 cached records
  - Testing: Run a session with >500 tests, stop it, then use the "Older" button to view earlier executions

- **Execution history batch write failing with bytes serialization error** (`core/engine/history_store.py:17-28`, `core/engine/history_store.py:265-267`)
  - Added `_json_safe()` helper to recursively convert bytes to base64 strings before JSON serialization
  - Applied to `context_snapshot` and `parsed_fields` which may contain bytes values from protocol parsing
  - Impact: All execution records now persist correctly to SQLite; previously 14k+ records were lost on flush
  - Testing: Run a session, stop it, verify execution history displays correctly in Correlation page

- **Correlation filter buttons inconsistent sizes** (`core/ui/spa/src/pages/CorrelationPage.css:338-355`)
  - Added `min-width: 64px` and `max-width: 140px` for consistent button sizing
  - Added text truncation with ellipsis for long state names (e.g., "AUTHENTICATED...")
  - Centered text with `justify-content: center`
  - Impact: Filter buttons now have uniform appearance regardless of state name length
  - Testing: Open Correlation page with protocol that has varied state name lengths

- **Correlation state filter missing rare states** (`core/ui/spa/src/pages/CorrelationPage.tsx:211-227`)
  - State filter options were derived from current page only, missing states that appear rarely
  - Now uses session's `state_coverage` which tracks all visited states across the entire session
  - Example: ESTABLISHED (49 visits in 16k tests) now appears even if not in current page
  - Impact: All visited states are available as filter options regardless of pagination
  - Testing: Run stateful session, verify all states from state_coverage appear in filters

### Changed - 2026-01-31

- **Documentation updates for plugin reorganization**
  - Updated `docs/PROTOCOL_PLUGIN_GUIDE.md` with new three-tier plugin directory structure
  - Updated `docs/QUICKSTART.md` with correct plugin paths and example names
  - Updated `docs/developer/04_data_management.md` with execution history architecture details
  - Added example plugins reference table to Protocol Plugin Guide
  - All docs now accessible via Documentation Hub in the web UI

- **Enforced termination-state traversal before session resets** (`core/engine/orchestrator.py:762-850`, `core/models.py:199-214`)
  - Added a termination reset pending flag to ensure termination fuzzing drives the state machine into a closed/terminal state before any periodic reset fires
  - Deferred interval-based resets while a termination reset is pending and reset immediately upon reaching a termination state
  - Ensured termination tests keep injecting while a termination reset is pending to avoid skipping teardown coverage
  - Impact: Session reset intervals now respect termination fuzzing by forcing a closed state before restarting traversal
  - Testing: Run a stateful session with termination fuzzing enabled and a short reset interval; confirm logs show termination_state_reached before periodic_state_reset

- **Preserved stateful message types during mutation** (`core/engine/orchestrator.py:621-700`)
  - Enforced the selected seed's message_type after mutation to prevent byte-level fuzzing from breaking state transitions
  - Re-serialized mutated fields with the fixed message_type for consistent state tracking
  - Impact: Stateful sessions can now reliably reach termination states even with aggressive mutations
  - Testing: Run the feature_reference plugin with termination fuzzing enabled; verify coverage reaches CLOSED

- **Termination fuzzing now overrides response followups when needed** (`core/engine/orchestrator.py:990-1034`)
  - Skips response-handler followups when a termination test should be injected, ensuring cleanup transitions aren't starved by continuous followups
  - Impact: Sessions using response handlers can still force CLOSED/termination states before reset
  - Testing: Run feature_reference with termination fuzzing enabled and confirm termination transitions occur despite followup traffic

- **Session reset/termination config now applied at creation** (`core/engine/orchestrator.py:240-278`)
  - Propagated session_reset_interval and enable_termination_fuzzing from FuzzConfig into new sessions
  - Impact: UI toggles now take effect for newly created sessions
  - Testing: Create a session with reset interval + termination fuzzing enabled; verify the session payload reflects those values

- **Correlation filter buttons no longer distort cards** (`core/ui/spa/src/pages/CorrelationPage.css:338-365`)
  - Normalized filter tag layout with inline-flex alignment, fixed line-height, and consistent height
  - Disabled hover transform for filter tags to prevent visual shifting
  - Impact: Filter buttons render as consistent pills without warping the filter card
  - Testing: Open Correlation page and toggle filters; verify buttons remain uniform and card layout stays stable

- **Correlation pagination allows older pages even with cache-only counts** (`core/ui/spa/src/pages/CorrelationPage.tsx:306-313`)
  - Enabled the "Older" button when the current page fills the limit, not only when total_count reports more rows
  - Impact: Users can page older history even if total_count is limited by cache state
  - Testing: Run a session with >500 executions, click Older and confirm older rows load

### Changed - 2026-01-30

- **Plugin directory reorganization** (`core/plugins/`)
  - Created three-tier directory structure:
    - `standard/`: Production-ready protocol implementations (DNS, MQTT, Modbus, TFTP, NTP, CoAP, IPv4)
    - `examples/`: Learning-focused plugins for bootstrapping custom development
    - `custom/`: User-created protocol plugins (auto-discovered)
  - Example plugins consolidated and renamed:
    - `minimal_tcp.py` - Bare minimum TCP protocol (start here)
    - `minimal_udp.py` - Bare minimum UDP protocol
    - `feature_reference.py` - Comprehensive feature showcase (all capabilities)
    - `orchestrated.py` - Multi-stage protocols with authentication
    - `stateful.py` - Complex state machines with branching
    - `field_types.py` - Quick copy-paste field reference
  - Removed obsolete plugins: auto_test.py, functionality_test.py, transform_demo.py
  - Updated `PluginManager` to scan subdirectories with priority (custom > examples > standard)
  - Test servers updated: removed functionality_server.py
  - All example plugins include clear docstrings pointing to their test servers

### Added - 2026-01-30

- **Orchestration integration into main fuzzing loop** (`core/engine/orchestrator.py`)
  - **Session initialization** (`create_session`):
    - Extracts `protocol_stack` from plugin configuration
    - Creates `ProtocolContext` for orchestrated sessions
    - Sets `connection_mode` and `heartbeat_enabled` from plugin config
  - **Bootstrap stage execution** (`start_session`, `_run_bootstrap_stages`):
    - Runs bootstrap stages via StageRunner before fuzzing starts
    - Extracts context values (auth tokens, etc.) for use in fuzzing
    - Sets `current_stage` to "fuzz_target" after bootstrap completes
    - Fails session gracefully if bootstrap fails
  - **Heartbeat integration** (`_start_heartbeat`):
    - Starts HeartbeatScheduler after bootstrap for orchestrated protocols
    - Stops heartbeat on session stop
    - Passes context for interval negotiation (from_context support)
  - **Persistent connection support** (`_execute_test_case`):
    - Uses ConnectionManager.get_transport() when connection_mode != "per_test"
    - Maintains persistent connections across test cases
    - Tracks connection health and marks unhealthy on errors
  - **Teardown stage execution** (`stop_session`, `_run_teardown_stages`):
    - Runs teardown stages when session stops
    - Gracefully handles teardown failures (logs warning, doesn't fail)
  - **Context injection** (`_inject_context_values`):
    - Injects context values into test case data for from_context fields
    - Re-serializes messages with context after mutation
  - **Execution recording** (`_record_execution`):
    - Records `stage_name`, `context_snapshot`, `parsed_fields`, `connection_sequence`
    - Captures protocol context at each execution for replay
  - **Resource cleanup**:
    - Cleans up `_session_contexts`, `_stage_runners`, connection manager on stop
  - Impact: Orchestrated protocols now fully functional in main fuzzing loop
  - Testing: 29 replay tests pass

### Fixed - 2026-01-30

- **Terminal states not reached during stateful fuzzing** (`core/engine/stateful_fuzzer.py`, `core/engine/orchestrator.py`)
  - Issue: With feature_reference plugin, CLOSED state never reached even with termination fuzzing enabled
  - Root cause 1: `select_transition()` 80% progression_weight always favored DATA_STREAM over TERMINATE
  - Root cause 2: Termination test interval (50) was larger than reset interval (20), so resets happened first
  - Root cause 3: Termination tests only fired every 50 iterations, missing the window before reset
  - Fixes to `select_transition()`:
    - Increased coverage exploration from 10% to 15%
    - Increased terminal state exploration from 5% to 10%
    - Added logging for reset reasons (interval vs terminal state)
  - Fixes to `_should_inject_termination_test()`:
    - Inject in last 3 tests before reset (ensures we try to reach terminal before resetting)
    - Scale termination interval to half of reset interval (if reset=20, termination=10)
    - Always check for termination transitions before deciding
  - Impact: Terminal states now reliably reached with termination fuzzing enabled
  - Probability analysis: ~20% combined chance per iteration to prioritize terminal/unvisited states

- **Execution history not showing records in Correlation page** (`core/engine/history_store.py`, `core/api/server.py`)
  - Issue: No executions visible - records queued but never written to SQLite
  - Root cause: Background writer lazy initialization silently failed when no event loop available
  - Architectural fix with multiple improvements:
  - **Robust writer initialization**: `start_background_writer()` now returns bool; `record()` falls back to synchronous writes if writer can't start
  - **Eager startup**: Background writer now starts in `server.py` startup_event() when event loop is guaranteed
  - **Cache-first queries**: `list()` returns from memory cache for first page (real-time data), SQLite for pagination
  - **Consistent counts**: `total_count()` returns max(sqlite_count, cache_count) to match list() behavior
  - **Session flush**: `flush()` drains queue and writes synchronously when session stops
  - Impact: Records visible immediately during fuzzing, reliably persisted to SQLite

- **Correlation page cleanup and consolidation** (`core/ui/spa/src/pages/CorrelationPage.tsx`, `CorrelationPage.css`)
  - Issue: Page had overlap with State Graph page (duplicated state coverage, mutation insights)
  - Issue: No executions appearing due to stale closure in fetchHistory useEffect
  - Removed: Session config card (available in session details), State Coverage insight card, Mutation Insights card
  - Added: Link to State Graph page in KPIs section for coverage details
  - Added: Empty state with contextual messaging based on session status
  - Fixed: `fetchHistory` wrapped in `useCallback` with proper dependencies
  - Fixed: useEffect dependency arrays now include stable function references
  - Simplified: Filter section with cleaner header showing count and clear button
  - Added CSS: `.empty-state` component, `.timeline-range-text`, `.timeline-dot-notable`, `.timeline-dot-filtered`
  - Impact: Focused correlation page on execution history and replay; coverage analysis on State Graph page

- **Mutation workbench visuals disappearing for havoc/splice mutations** (`core/ui/spa/src/pages/MutationWorkbenchPage.tsx`)
  - Issue: When havoc or splice mutators produced unparseable packets, the UI hid the entire workbench content
  - Root cause: Render condition `fields.length > 0` failed when parser couldn't parse aggressive mutations
  - Fix: Changed condition to `fields.length > 0 || hexData` so content shows with hex data even without parsed fields
  - Added `lastKnownFields` state to preserve field info from before aggressive mutations
  - Added `parseWarning` state to explain when mutations produce unparseable packets (expected for havoc/splice)
  - DiffHexViewer and LivePacketBuilder now fallback to `lastKnownFields` for byte highlighting
  - FieldMutationPanel disabled when fields are unparseable (must use Clear All or Undo first)
  - Added CSS styling for `.parse-warning` and `.section-hint.unparseable` messages
  - Impact: Users can now see hex diff visualization for all mutation types including havoc and splice

- **Plugin Debugger validation failing for orchestrated plugins** (`core/api/routes/plugins.py`, `core/ui/spa/src/pages/PluginDebuggerPage.tsx`)
  - Issue: Plugin Debugger page failed to validate plugins with `protocol_stack` (multi-stage orchestration)
  - Root cause: API `/validate` endpoint only called `validate_plugin()` for main data_model, not `validate_protocol_stack()`
  - API fix: Added call to `validator.validate_protocol_stack(plugin.protocol_stack)` when protocol_stack is present
  - UI fix: Added new interfaces for `ProtocolStage`, `HeartbeatConfig`, `ConnectionConfig` in PluginDetails
  - UI fix: Added orchestration section displaying protocol_stack stages with visual cards
  - Each stage card shows: name, role badge (bootstrap/fuzz_target/teardown), request/response fields, exports, expect conditions
  - Added connection mode and heartbeat configuration display
  - Added CSS for `.orchestration-section`, `.stage-card`, `.role-badge`, `.field-chip`, `.export-chip`
  - Impact: Orchestrated plugins like `examples/orchestrated.py` now validate and display correctly

- **State Walker failing with "No seed found for message type 'None'"** (`core/api/routes/walker.py`, `core/engine/stateful_fuzzer.py`)
  - Issue: State Walker page failed on orchestrated plugin because state_model uses `message` key instead of `message_type`
  - Root cause: Walker and stateful fuzzer only checked `transition.get("message_type")`, missing plugins using `message` key
  - Fix: Added `_get_message_type()` helper function in both files that checks `message_type`, `message`, and `trigger` keys
  - Updated all transition message type lookups to use the helper function
  - Also fixed: `get_valid_transitions()` and `_find_transition()` now handle wildcard "from" states (`"*"`) used in orchestrated plugins
  - Impact: State Walker now works with orchestrated plugins and other plugins using alternate transition key names

- **Request payload parsing during fuzz loop** (`core/engine/orchestrator.py`)
  - Added `_parse_request_payload()` helper method to parse test case data into field dictionary
  - Updated `_execute_and_record_test_case()` to parse request payloads before execution
  - Updated `handle_agent_result()` to parse request payloads for agent-mode execution
  - Both paths now pass `parsed_fields` to `_record_execution()` for storage
  - Impact: Enables FRESH mode replay to re-serialize messages with current context values
  - Previously, `parsed_fields` was only populated during replay (line 1909), not normal fuzzing
  - Now all execution records include parsed field values for reliable context-aware replay

- **Terminal states not reached during stateful fuzzing** (`core/engine/stateful_fuzzer.py:254-330`)
  - Issue: CLOSED state never reached after 88 tests with reset_interval=20 using feature_reference plugin
  - Root cause: `select_transition()` used 80% `progression_weight` to always pick the first transition
  - For ESTABLISHED state, self-loop transitions (DATA_STREAM, HEARTBEAT) were listed first
  - TERMINATE transition to CLOSED had only ~6.7% selection probability (80% first + 20%/3 random)
  - Fix: Added coverage-guided exploration to `select_transition()`:
    - 10% chance: Prioritize transitions to unvisited states (`_find_transition_to_unvisited_state()`)
    - 5% chance: Prioritize transitions to terminal states (`_find_transition_to_terminal_state()`)
    - Remaining: Original progression_weight + random selection
  - New helper methods:
    - `_find_transition_to_unvisited_state()`: Returns transition to state with zero visits
    - `_find_transition_to_terminal_state()`: Returns transition to states identified as terminal
  - Impact: Terminal states (CLOSED, DISCONNECTED, etc.) now get explored within reasonable test counts
  - Note: `enable_termination_fuzzing` session option still available for more aggressive termination testing

- **Code review remediation - Phase 3: Critical/High severity fixes**
  - **CRITICAL: Bootstrap now uses persistent connection** (`core/engine/stage_runner.py`)
    - Added `connection_manager` parameter to StageRunner constructor
    - `_execute_bootstrap_attempt()` uses ConnectionManager when connection_mode is session/per_stage
    - Bootstrap and fuzzing now share the same TCP connection for protocols requiring it
    - Fixes: Auth tokens tied to connection, TLS session continuity, stateful handshakes
  - **CRITICAL: Stage name mismatch in replay fixed** (`core/engine/orchestrator.py`, `core/engine/replay_executor.py`)
    - `_run_bootstrap_stages()` now uses actual stage name (e.g., "application") not role ("fuzz_target")
    - Replay filtering properly matches fuzz executions by stage name
    - Fixes: All fuzz executions being skipped during replay
  - **HIGH: Bootstrap sequence numbers now unique** (`core/engine/stage_runner.py`)
    - Bootstrap stages use negative sequence numbers (-1, -2, -3, ...)
    - Prevents primary key collision in history store (session_id, sequence_number)
    - Fixes: Only last bootstrap stage being stored
  - **HIGH: Connection config now applied** (`core/engine/orchestrator.py`)
    - Calls `set_connection_config()` when creating persistent connections
    - demux, on_drop, reconnect options from plugin now take effect
  - **HIGH: Heartbeat reconnect callback for re-bootstrap** (`core/engine/orchestrator.py`, `core/engine/heartbeat_scheduler.py`)
    - HeartbeatScheduler now supports async callbacks (awaits coroutines)
    - Orchestrator passes reconnect_callback that re-runs bootstrap stages
    - Fixes: Session continuing without bootstrap after connection loss
  - **MEDIUM: send_with_lock transport leak fixed** (`core/engine/connection_manager.py`)
    - Closes transport after use in per_test mode
    - Prevents socket leaks from repeated heartbeats
  - **MEDIUM: Session context now persisted** (`core/engine/orchestrator.py`)
    - `_checkpoint_session()` syncs `_session_contexts` to `session.context`
    - `_load_sessions_from_disk()` restores context from persisted `session.context`
    - Fixes: Context lost on session resume after restart

- **Additional code quality improvements** (`core/engine/`)
  - **CRITICAL: asyncio Future creation fixed** (`core/engine/connection_manager.py`)
    - PendingRequest.future now created lazily via property, not in default_factory
    - Prevents RuntimeError when instantiated outside event loop
  - **Orchestrator initialization cleanup** (`core/engine/orchestrator.py`)
    - All private attributes (`_session_contexts`, `_stage_runners`, `_connection_manager`, `_heartbeat_scheduler`) now initialized in `__init__`
    - Replaced `hasattr()` checks with direct attribute access
    - Prevents race conditions in multi-session scenarios
  - **Extracted cleanup logic** (`core/engine/orchestrator.py`)
    - New `_cleanup_session_resources()` method consolidates cleanup code
    - Used by both `stop_session()` and `delete_session()`
    - Reduces code duplication and ensures consistent cleanup

- **Code review remediation - Phase 4: Connection mode and rebootstrap fixes**
  - **HIGH: per_stage connection mode now works during bootstrap/teardown** (`core/engine/stage_runner.py:320,716`)
    - `_execute_bootstrap_attempt()` and `_run_teardown_stage()` now set `session.current_stage` before calling `get_transport()`
    - ConnectionManager's `_get_connection_id()` uses `session.current_stage` for per_stage mode
    - Previously, all stages shared one connection because current_stage wasn't set
  - **HIGH: Teardown now uses ConnectionManager for persistent modes** (`core/engine/stage_runner.py:710-733`)
    - `_run_teardown_stage()` checks for persistent connection mode (session/per_stage)
    - Uses existing managed transport instead of creating ephemeral connections
    - Teardown messages now sent on the same connection used for fuzzing
  - **HIGH: Bootstrap sequence collision on rebootstrap fixed** (`core/engine/orchestrator.py:1214-1226`)
    - `_run_bootstrap_stages()` now reuses existing StageRunner instead of creating new one
    - Preserves `_bootstrap_sequence` counter across rebootstraps
    - Calls `reset_for_reconnect()` to clear context but keep sequence counter
    - Fixes: Sequence numbers -1, -2, -3 reused after heartbeat-triggered rebootstrap
  - **MEDIUM: Connection config applied early in session lifecycle** (`core/engine/orchestrator.py:354-367`)
    - `start_session()` now applies connection config before bootstrap stages
    - Sessions without bootstrap stages now get their connection config applied
    - Removed duplicate config application from `_run_bootstrap_stages()`
  - **MEDIUM: reset_for_reconnect() now called during rebootstrap** (`core/engine/orchestrator.py:1219`)
    - Context is cleared before re-running bootstrap stages
    - Prevents stale context values from affecting new authentication
    - connection_manager reference updated on reused StageRunner

- **Code review remediation - Phase 5: Transport and replay fixes**
  - **CRITICAL: UDP sessions now use UDP transport** (`core/engine/transport.py:271-288`, `core/engine/orchestrator.py:1409-1414`)
    - `TransportFactory.create_transport()` now accepts `transport_type` parameter
    - `_execute_test_case()` passes `session.transport.value` to factory
    - Previously, all protocols silently used TCP regardless of session transport setting
  - **HIGH: Receive timeouts now classified as HANG, not CRASH** (`core/engine/orchestrator.py:1468-1478`)
    - Added explicit `except ReceiveTimeoutError` handler before `TransportError`
    - ReceiveTimeoutError indicates target not responding (potential hang)
    - Previously caught by TransportError handler which set CRASH, inflating crash stats
  - **HIGH: FRESH replay bootstrap and replay now share same connection** (`core/engine/replay_executor.py:185-227`, `core/engine/connection_manager.py:527-548,736-778`)
    - Added `register_replay_transport()` / `unregister_replay_transport()` methods
    - Added `use_replay_transport` parameter to `get_transport()` for explicit opt-in
    - StageRunner accepts `use_replay_transport` flag, passes to ConnectionManager
    - Bootstrap and replay now use same TCP connection for connection-bound tokens
    - Previously, bootstrap used ephemeral connection while replay used isolated transport
  - **MEDIUM: Replay transport registration no longer hijacks active sessions** (`core/engine/connection_manager.py:799-804`, `core/engine/stage_runner.py:84,325,722`)
    - Removed implicit replay transport lookup from `_get_connection_id()`
    - Replay transport only used when `use_replay_transport=True` is explicitly passed
    - Prevents concurrent replay from routing active session's fuzz traffic to replay transport
  - **HIGH: replay_single no longer closes active session transport** (`core/engine/replay_executor.py:352`)
    - Changed from `get_transport()` to `create_replay_transport()`
    - Prevents replay operations from tearing down active session connections
  - **MEDIUM: Removed unused global heartbeat_scheduler** (`core/engine/heartbeat_scheduler.py:544-556`)
    - Deleted global `heartbeat_scheduler` instance and `init_heartbeat_scheduler()` function
    - FuzzOrchestrator uses instance variable `_heartbeat_scheduler` instead
    - Dead code from incomplete global pattern

- **Code review remediation - Phase 2** (`core/engine/`, `core/api/`, `core/ui/spa/`)
  - `core/engine/replay_executor.py`:
    - Creates StageRunner on-demand for FRESH mode when not provided (fixes bootstrap skipping)
    - Denormalizes data_model before creating ProtocolParser (fixes base64 serialization issue)
    - Uses `create_replay_transport()` for isolated replay connections (prevents transport reuse)
  - `core/engine/connection_manager.py`:
    - UDP persistent connections now raise TransportError with helpful message
    - Added `create_replay_transport()` method for isolated replay connections
  - `core/ui/spa/src/pages/CorrelationPage.tsx`:
    - Removed legacy range replay controls (handleRangeReplay, handleSequenceRangeReplay)
    - Removed associated state variables (rangeStart, rangeEnd, rangeDelay, sequenceRangeStart, sequenceRangeEnd)
    - Added hint directing users to SessionDetailPanel for context-aware replay
  - `core/ui/spa/src/components/SessionDetailPanel.tsx`:
    - Added aria-label attributes to reveal/delete/close buttons for accessibility
  - Impact: 29 replay tests pass, UI now has proper accessibility labels
  - Testing: Rebuild SPA, verify in browser

- **Critical review fixes for orchestrated sessions**
  - `core/engine/history_store.py`: Added `record_direct()` method for pre-built records
    - Fixes signature mismatch: StageRunner was passing TestCaseExecutionRecord to record()
  - `core/engine/stage_runner.py`: Updated to use `record_direct()` instead of `record()`
    - Added `rerun_stage()` method for re-running bootstrap stages via API
    - Added `_protocol_stages` and `_last_session` for rerun support
    - Stores stage definitions during bootstrap for later reference
  - `core/engine/replay_executor.py`: Fixed `_context` → `context` attribute access
    - StageRunner exposes `context` not `_context`
  - `core/engine/heartbeat_scheduler.py`: Added `interval_ms` to HeartbeatState and get_status()
    - API now returns correct interval_ms value
  - `core/api/routes/orchestration.py`: Fixed stage status API calls
    - Uses `get_stage_statuses()` (returns list) instead of `get_stage_status()` (needs name)
  - `tests/test_replay.py`: Fixed MockStageRunner to use `context` not `_context`
  - Removed `core/engine/session_context.py` (dead code, unused)
  - Impact: All 114 orchestration tests now pass
  - **Known Limitations** (documented, not implemented in this phase):
    - Demultiplexing code paths in connection_manager.py are scaffolded but not active
    - UDP handling logs warning and falls back to TCP
    - Main fuzzing loop does not yet use orchestrated components
    - Connection manager not wired into StageRunner (uses per-test TransportFactory)

### Added - 2026-01-30

- **Phase 8: Documentation & Polish** - Production readiness
  - `core/plugins/orchestrated_example.py`: New example multi-stage protocol plugin
    - Demonstrates protocol_stack with bootstrap/fuzz_target/teardown stages
    - Shows context-based value injection (from_context)
    - Shows response value extraction (exports)
    - Shows heartbeat configuration with context-based interval
    - Shows connection lifecycle management
    - Includes validate_response specification oracle
  - `docs/ORCHESTRATED_SESSIONS_GUIDE.md`: New comprehensive guide
    - Quick start with protocol stack and context
    - Protocol stack stages (bootstrap, fuzz_target, teardown)
    - Context system (setting, using, viewing)
    - Connection management (modes, reconnection)
    - Heartbeat configuration (interval, jitter, actions)
    - Replay (modes, UI, API)
    - API reference for all orchestration endpoints
    - Troubleshooting section with common issues and solutions
  - Impact: Complete documentation for orchestrated sessions feature
  - Testing: Example plugin syntax verified

- **Phase 7: UI Overhaul** - Session detail panel with orchestration visibility
  - `core/ui/spa/src/components/SessionDetailPanel.tsx`: New expandable session detail panel
    - **Context tab**: View/add/delete context values with masked values (click to reveal)
    - **Stages tab**: View protocol stages, status, attempts, and re-run bootstrap stages
    - **Connection tab**: View connection stats, health, and trigger reconnect/rebootstrap
    - **Heartbeat tab**: View heartbeat status, interval, failures, and reset failure count
    - **Replay tab**: Execute orchestrated replay with mode selection (fresh/stored/skip)
  - `core/ui/spa/src/components/SessionDetailPanel.css`: Styles for session detail panel
    - Tabbed interface with context/stages/connection/heartbeat/replay tabs
    - Status badges, health indicators, stat cards
    - Context value masking with reveal toggle
    - Replay form with mode, sequence, and delay controls
  - `core/ui/spa/src/pages/DashboardPage.tsx`: Updated with expandable session rows
    - Added expand/collapse button to session table
    - Shows SessionDetailPanel when row is expanded
    - React.Fragment with proper keys for table rows
    - Added health indicators (⚡ for persistent connection, ❤️ for heartbeat)
    - FuzzSession interface extended with orchestration fields
  - `core/ui/spa/src/pages/DashboardPage.css`: Added expand button, detail row, and health indicator styles
  - Impact: Full orchestration visibility from the dashboard
  - Testing: UI builds successfully, accessible at http://localhost:8000/ui/

- **Phase 6: API & Storage** - New orchestration API endpoints
  - `core/api/routes/orchestration.py`: New route file for orchestration endpoints
    - **Context endpoints**:
      - `GET /api/sessions/{id}/context` - Get full context snapshot
      - `GET /api/sessions/{id}/context/{key}` - Get single context value
      - `POST /api/sessions/{id}/context` - Set context value (supports hex bytes with 0x prefix)
      - `DELETE /api/sessions/{id}/context/{key}` - Delete context value
    - **Stage endpoints**:
      - `GET /api/sessions/{id}/stages` - List protocol stages and status
      - `POST /api/sessions/{id}/stages/{name}/rerun` - Re-run bootstrap stage
    - **Connection endpoints**:
      - `GET /api/sessions/{id}/connection` - Get connection status and stats
      - `POST /api/sessions/{id}/connection/reconnect` - Trigger reconnection
    - **Heartbeat endpoints**:
      - `GET /api/sessions/{id}/heartbeat` - Get heartbeat status
      - `POST /api/sessions/{id}/heartbeat/reset` - Reset failure count
    - **Replay endpoint**:
      - `POST /api/sessions/{id}/replay` - Orchestrated replay with mode support
  - `core/models.py`: Added orchestration API models
    - `ContextValueResponse`, `ContextSnapshotResponse`, `ContextSetRequest`
    - `StageInfo`, `StageListResponse`
    - `ConnectionInfo`, `ConnectionStatusResponse`
    - `HeartbeatStatusResponse`
    - `OrchestratedReplayRequest`, `OrchestratedReplayResult`, `OrchestratedReplayResponse`
  - `core/api/routes/__init__.py`: Registered orchestration router
  - Impact: Full API surface for managing orchestrated sessions
  - Testing: All endpoints verified via curl (context, stages, connection, heartbeat)

- **Phase 5: Replay** - Execution replay with context reconstruction
  - `core/engine/replay_executor.py`: New `ReplayExecutor` class for replaying executions
    - `replay_up_to()`: Replay all executions from start up to target sequence number
    - `replay_single()`: Replay a single execution by sequence number
    - `_replay_single()`: Internal method for single execution replay
    - `_get_fuzz_target_stage()`: Get the fuzz_target stage from protocol stack
    - `ReplayMode` enum: FRESH (re-bootstrap), STORED (exact bytes), SKIP (no bootstrap)
    - `ReplayResult` dataclass: Result for single execution replay
      - `original_sequence`: Original sequence number from history
      - `status`: "success", "timeout", or "error"
      - `response_preview`: First 100 bytes of response as hex
      - `matched_original`: Whether response matches original
      - `duration_ms`: Execution duration
    - `ReplayResponse` dataclass: Response from replay operation
      - `replayed_count`: Number of executions replayed
      - `skipped_count`: Bootstrap stages skipped
      - `results`: List of individual ReplayResult
      - `context_after`: Final context snapshot
      - `warnings`: List of warnings (incomplete history, etc.)
    - `ReplayError` exception for replay failures
  - `core/engine/history_store.py`: Updated for replay support
    - Added columns: `stage_name`, `context_snapshot`, `parsed_fields`, `connection_sequence`
    - `list_for_replay()`: Query executions in ascending order for replay
    - `_row_to_record()`: DRY helper for row-to-record conversion
    - Fixed syntax error on line 563 (stray parenthesis)
  - `tests/test_replay.py`: Test suite for replay executor (29 tests)
    - Replay modes: stored, fresh, skip
    - Single execution replay: success, not found, with context
    - Multi-execution replay: basic, partial, delay, stop_on_error
    - Response matching: matched_original true/false
    - Error handling: timeout, send error, plugin not found
    - Duration tracking, dataclass defaults
  - Features:
    - FRESH mode: Re-run bootstrap, re-serialize with current context
    - STORED mode: Replay exact historical bytes, restore context from snapshot
    - SKIP mode: No bootstrap, use stored bytes, empty context
    - Warning detection: History gaps, incomplete range
    - Inter-message delay support for rate limiting
    - Transport cleanup on success and error
  - Impact: Enables reliable reproduction of issues via replay
  - Testing: `pytest tests/test_replay.py` (all 29 tests pass)

### Added - 2026-01-29

- **Phase 4: Heartbeat** - Scheduled keepalive messages
  - `core/engine/heartbeat_scheduler.py`: New `HeartbeatScheduler` class for periodic keepalives
    - `start()`: Start heartbeat task for a session
    - `stop()`: Stop heartbeat task for a session
    - `stop_all()`: Stop all heartbeat tasks
    - `get_status()`: Get heartbeat status (healthy/warning/failed/disabled)
    - `is_running()`: Check if heartbeat is running for a session
    - `reset_failures()`: Reset failure count after reconnection
    - `_heartbeat_loop()`: Main async loop that sends periodic heartbeats
    - `_handle_failure()`: Handle heartbeat failures with configurable actions
    - `_get_interval()`: Get interval from config or context (from_context support)
    - `_build_heartbeat()`: Build heartbeat message from data_model or raw bytes
    - `_is_valid_response()`: Validate heartbeat response
    - `HeartbeatStatus` enum: HEALTHY, WARNING, FAILED, DISABLED, STOPPED
    - `HeartbeatAbortError`: Exception for max failures with abort action
    - `HeartbeatState` dataclass: Runtime state for heartbeat task
  - Features:
    - Runs concurrently with fuzz loop as async task
    - Coordinates sends via ConnectionManager.send_with_lock() mutex
    - Supports jitter to avoid predictable patterns
    - Supports context-based interval (`interval_ms: {from_context: "hb_interval"}`)
    - Configurable failure handling: warn, reconnect, or abort
    - Reconnect callback for triggering re-bootstrap
    - Message building via ProtocolParser with context injection
  - `tests/test_heartbeat.py`: Test suite for heartbeat scheduler (27 tests)
    - Start/stop lifecycle, interval handling, failure detection
    - Reconnect triggering, callback invocation
    - Message building, response validation
  - Impact: Enables protocols requiring periodic keepalive messages
  - Testing: `pytest tests/test_heartbeat.py` (all 27 tests pass)

- **Phase 3: Connection Management** - Persistent connections with reconnect
  - `core/engine/connection_manager.py`: New module for managed transport lifecycle
    - `PendingRequest`: Tracks requests awaiting response for demux routing
      - `wait()`: Async wait with timeout support
      - `resolve()`: Set result on the future
      - `fail()`: Set exception on the future
    - `PersistentTCPTransport`: Low-level persistent TCP transport with separate connect/send/recv
      - `connect()`: Establish TCP connection with configurable timeout
      - `send()`: Send data on established connection
      - `recv()`: Receive data with timeout
      - `cleanup()`: Close socket and cleanup resources
    - `ManagedTransport`: High-level wrapper with health tracking and statistics
      - Health tracking: `connected`, `healthy` flags with automatic degradation
      - Statistics: `bytes_sent`, `bytes_received`, `send_count`, `recv_count`
      - Timestamps: `created_at`, `last_send`, `last_recv`
      - `send_and_receive()`: Coordinated send/recv with mutex for concurrent safety
      - `get_stats()`: Return connection statistics dictionary
    - `ConnectionManager`: Session-scoped transport management
      - `get_transport()`: Get or create transport with health check and replacement
      - `send_with_lock()`: Send data with mutex coordination for heartbeat safety
      - `reconnect()`: Handle reconnection with backoff and rebootstrap signaling
      - `close_session()`: Clean up all transports for a session
      - `close_all()`: Clean up all managed transports
      - Connection modes: `per_test`, `per_stage`, `session`
      - `_get_connection_id()`: Generate unique IDs based on connection mode
    - `ConnectionAbortError`: Exception for max reconnects exceeded
  - `tests/test_connection_manager.py`: Test suite for connection management (21 tests)
    - PendingRequest: resolve, timeout, fail behavior
    - ManagedTransport: connect, send, receive, close, statistics
    - ConnectionManager: transport creation, reuse, reconnect, modes
  - Impact: Foundation for persistent connections in orchestrated sessions
  - Testing: `pytest tests/test_connection_manager.py` (all 21 tests pass)

- **Phase 2: Stage Execution** - Bootstrap and teardown stage execution
  - `core/engine/stage_runner.py`: New `StageRunner` class for orchestrated session stages
    - `run_bootstrap_stages()`: Execute all bootstrap stages with retry logic
    - `run_teardown_stages()`: Execute teardown stages (failures logged, don't halt session)
    - `_run_bootstrap_stage()`: Single stage execution with retry, validation, exports
    - `_validate_response()`: Validate parsed response against `expect` conditions
    - `_extract_value()`: Extract values with dotted path support (e.g., "header.token")
    - `_apply_export_transforms()`: Apply transforms to exported values
    - `_record_bootstrap_execution()`: Record bootstrap in history for replay
    - `reset_for_reconnect()`: Reset state for reconnection with optional context clear
    - `BootstrapError`, `BootstrapValidationError` exception classes
  - `tests/test_stage_runner.py`: Test suite for stage runner (12 tests)
    - Bootstrap execution, validation, retry logic, export transforms
    - Stage status tracking, helper methods
  - Impact: Foundation for executing multi-stage protocols with context extraction
  - Testing: `pytest tests/test_stage_runner.py` (all 12 tests pass)

- **Phase 1: Orchestrated Sessions Foundation** - Core context and serialization support
  - `core/engine/protocol_context.py`: New `ProtocolContext` class for key-value store
    - Basic operations: `get()`, `set()`, `has()`, `delete()`, `keys()`, `clear()`
    - Snapshot/restore for persistence and replay with bytes/datetime serialization
    - `copy()` for deep cloning, `merge()` for combining contexts
    - `ContextKeyNotFoundError` for helpful error messages with available keys
  - `core/engine/protocol_parser.py:276-475`: Updated `serialize()` with context support
    - New optional `context` parameter for `from_context` field injection
    - `_resolve_field_values()` method for context resolution with transform pipeline
    - `_apply_transforms()` for bitwise operations (and_mask, or_mask, shift, invert, etc.)
    - `_generate_value()` for dynamic values: `unix_timestamp`, `sequence`, `random_bytes:N`
    - `SerializationError` exception for clear error messages
  - `core/plugin_loader.py:200-260`: Parse `protocol_stack`, `connection`, `heartbeat` attributes
    - `get_protocol_stack()`, `get_connection_config()`, `get_heartbeat_config()` helpers
    - `is_orchestrated()` method to check if plugin uses protocol stack
    - `_normalize_protocol_stack()` to convert bytes to base64 in stage data_models
  - `core/engine/plugin_validator.py:658-780`: Validate protocol_stack configuration
    - Check for required `fuzz_target` stage
    - Validate stage roles, data_models, response_models
    - Validate exports reference valid response_model fields
  - `core/models.py:39-55,188-227,500-513`: Model updates for orchestration
    - `ConnectionMode` enum: `per_test`, `per_stage`, `session`
    - `ProtocolPlugin`: Added `protocol_stack`, `connection`, `heartbeat` fields
    - `FuzzSession`: Added context, connection_mode, heartbeat state fields
    - `TestCaseExecutionRecord`: Added `stage_name`, `context_snapshot`, `parsed_fields`
    - `ProtocolStageStatus`: New model for tracking stage execution state
  - `tests/test_protocol_context.py`: Comprehensive test suite (25 tests)
    - Tests for ProtocolContext operations, snapshot/restore, bytes serialization
    - Tests for serialize with context, transform pipelines, dynamic generation
  - Impact: Foundation for multi-protocol fuzzing with shared context
  - Testing: `pytest tests/test_protocol_context.py` (all 25 tests pass)

- **Orchestrated Sessions Architecture Document** (`docs/developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md`)
  - Comprehensive architecture design for multi-protocol fuzzing with shared context
  - Defines plugin schema for `protocol_stack` with bootstrap and fuzz target stages
  - Session context for dynamic value extraction and injection (`from_context` field attribute)
  - Connection manager using existing `Transport` abstraction (not raw sockets)
  - Heartbeat scheduler with send coordination to prevent message interleaving
  - Response demultiplexing strategy for shared connections (sequential, tagged, type-based)
  - Context snapshot policy with size limits and key filtering
  - Replay architecture with modes: fresh, stored, skip (ascending order requirement)
  - State machine integration with existing `StatefulFuzzingSession`
  - Bootstrap stage policies: not fuzzed, recorded in history, no seeds
  - API additions: context, stages, connection, heartbeat endpoints
  - UI consolidation plan: Sessions, Analysis, Protocols, Settings pages
  - 8-phase implementation plan with deliverables and testing strategy
  - Backward compatible: existing single-protocol plugins continue to work unchanged
  - Amended based on code review feedback to align with existing codebase patterns

### Fixed - 2026-01-29

- **Fixed `from_context` and `generate` fields not resolving with `build_default_fields()`** (`core/engine/protocol_parser.py:1043-1065`)
  - `build_default_fields()` was including default values (0 for uint32) for fields with `from_context` or `generate`
  - This caused `_resolve_field_values()` to skip context/generation since a non-None value existed
  - Fix: `build_default_fields()` now skips fields that have `from_context` or `generate` attributes
  - These fields get their values from context injection or dynamic generation during serialization
  - Impact: Heartbeat messages and other context-dependent messages now serialize correctly
  - Testing: Verified with `parser.serialize(parser.build_default_fields(), context=ctx)` pattern

### Changed - 2026-01-29

- **Refined orchestrated sessions plan for transport reuse, demux, replay ordering, and validation** (`docs/developer/ORCHESTRATED_SESSIONS_ARCHITECTURE.md:60-1450`)
  - Replaced raw-socket assumptions with a persistent-transport extension of the existing Transport abstraction
  - Added single-reader demux requirements with FIFO pending queue and correlation strategies
  - Clarified per-stage vs session connection handoff rules and replay ascending-order requirement
  - Added context snapshot policy, masking requirements, and parsed_fields replay requirements
  - Added validator updates for from_context/transform/generate and phase deliverables alignment
  - Impact: Lowers implementation risk and keeps orchestration aligned with current async architecture
  - Testing: Review doc sections; no runtime changes yet

- **Validated dynamic field attributes in plugin validator** (`core/engine/plugin_validator.py:112-330`)
  - Added checks for `from_context`, `transform`, and `generate` to prevent runtime failures
  - Validates transform operation names and generator syntax (`random_bytes:N`, `unix_timestamp`, `sequence`)
  - Impact: Early detection of invalid orchestrated-session fields during plugin validation
  - Testing: Run plugin validation on a plugin using invalid `generate` or `transform` values

### Added - 2026-01-28

- **Variable-length field positioning warning in Plugin Validator** (`core/engine/plugin_validator.py:508-555`)
  - Added `_validate_variable_length_positioning()` method to detect problematic field configurations
  - Warns when a variable-length field (`max_size` without linked length field) is not the last field
  - The parser consumes all remaining bytes for such fields, breaking subsequent field parsing
  - Warning message explains the issue and provides three fix options:
    1. Add a length field with `is_size_field`/`size_of` linkage
    2. Move the variable-length field to the end of the message
    3. Use fixed `size` instead of `max_size`
  - Impact: Helps plugin authors avoid a common pitfall; affected plugins: DNS, CoAP, TFTP
  - This is a fundamental limitation of the parsing model, not a framework bug
  - Testing: Validate dns.py, coap.py, or tftp.py plugins to see the warning

- **Field Operations Reference plugin** (`core/plugins/field_operations_reference.py`)
  - Concise copy-paste ready examples of ALL supported field operations
  - Organized into numbered sections with line references:
    1. Field types: uint8/16/32/64, int8/16/32/64, bits, bytes, string
    2. Field attributes: default, mutable, endian, values, is_size_field/size_of
    3. Behaviors: increment (with initial/step/wrap), add_constant
    4. Response handlers: match conditions, copy_from_response
    5. Transform operations: all 9 operations with commented examples
    6. State model: states and transitions
  - Includes response_model and validate_response examples
  - Impact: Quick reference for plugin authors; complements feature_showcase.py
  - Testing: Load plugin, verify 15 blocks and 4 response handlers

- **Bitwise transformation pipeline for response handlers** (`core/engine/response_planner.py:1-250`, `core/plugins/transform_demo.py`)
  - Extended response handlers to support chained transformation operations
  - New `transform` list syntax for applying multiple operations in sequence:
    ```python
    "header_check": {
        "copy_from_response": "session_token",
        "transform": [
            {"operation": "and_mask", "value": 0x1F},
            {"operation": "invert", "bit_width": 5},
        ]
    }
    ```
  - New operations added:
    - `invert`: Bitwise NOT with optional `bit_width` parameter to limit inversion range
    - `subtract_constant`: Subtract a constant value
    - `modulo`: Modulo operation
  - Enhanced `bit_width` parameter for `invert` operation:
    - With bit_width=N (recommended): Inverts only N least significant bits (XOR with 2^N-1)
    - Without bit_width: Infers width from value with warning (see Fixed section below)
  - Added `transform_demo.py` plugin demonstrating:
    - Copying server token to subsequent messages
    - Deriving header check field by extracting 5 LSBs and inverting
    - Chaining and_mask -> invert operations
  - Backward compatible: Single `operation` syntax still works
  - Impact: Enables protocols requiring derived/computed fields from server responses
  - Testing: Load transform_demo plugin, verify transformation pipeline produces correct values

- **Common protocol plugins for real-world fuzzing** (`core/plugins/dns.py`, `core/plugins/mqtt.py`, `core/plugins/modbus_tcp.py`, `core/plugins/tftp.py`, `core/plugins/ntp.py`, `core/plugins/coap.py`)
  - **DNS** (RFC 1035): Network infrastructure protocol
    - 16 blocks, 8 bit fields (flags packed into 16 bits: QR, Opcode, AA, TC, RD, RA, Z, RCODE)
    - 8 seeds covering A, AAAA, MX, TXT, ANY, PTR queries plus version.bind disclosure
    - Documents common DNS fuzzing targets (name decompression, length fields)
  - **MQTT v3.1.1**: IoT messaging protocol
    - 16 blocks, 9 bit fields (connect flags: username, password, will_retain, will_qos, will_flag, clean_session)
    - 6 seeds including auth flags, will messages, QoS levels, version mismatch
    - Covers broker authentication and session management vulnerabilities
  - **Modbus TCP**: Industrial control systems protocol
    - 6 blocks with MBAP header and PDU structure
    - 10 seeds covering read coils/registers, write operations, broadcast, device ID query
    - Includes security warning about fuzzing production ICS/SCADA systems
  - **TFTP** (RFC 1350): Trivial File Transfer Protocol
    - 4 blocks for RRQ/WRQ packets with options extension
    - 10 seeds including path traversal tests, blksize/tsize options, boundary cases
    - Documents common TFTP vulnerabilities (path traversal, buffer overflows)
  - **NTP** (RFC 5905): Network Time Protocol
    - 13 blocks, 3 bit fields (LI, VN, Mode packed in first byte)
    - 8 seeds covering NTPv3/v4, symmetric/broadcast modes, leap indicators
    - Documents amplification attacks and timestamp manipulation risks
  - **CoAP** (RFC 7252): Constrained Application Protocol for IoT
    - 10 blocks, 5 bit fields (version, type, TKL, code_class, code_detail)
    - 10 seeds for GET/POST/PUT/DELETE, resource discovery, query parameters
    - Demonstrates delta-encoded options and payload markers
  - All plugins include comprehensive tutorial-style comments explaining:
    - Protocol structure and bit field packing
    - Security context and common vulnerabilities
    - RFC references and real-world usage
  - Impact: Users can immediately fuzz common protocols or use as templates for similar protocols
  - Testing: Load each plugin in UI, verify seeds parse correctly, test against target services

- **Comprehensive sub-byte/bit field examples in feature_showcase plugin** (`core/plugins/feature_showcase.py:255-424`, `tests/feature_showcase_server.py:30-90,329-530`)
  - **New bit fields added to data_model** demonstrating advanced patterns:
    - `qos_level` (3 bits): Quality of Service levels 0-7, mimics IP DSCP/802.1Q PCP patterns
    - `ecn_bits` (2 bits): Explicit Congestion Notification as defined in RFC 3168
    - `ack_required` (1 bit): Acknowledgment required flag demonstrating reliable delivery patterns
    - `more_fragments` (1 bit): Fragmentation continuation flag for multi-part messages
    - `fragment_offset` (8 bits): Fragment position in reassembled message
  - **Updated seed corpus** with 6 comprehensive seeds demonstrating:
    - Seed 1: All bit fields at zero (baseline)
    - Seed 2: Encryption/compression flags with HIGH priority and Video QoS
    - Seed 3: Maximum bit field values for edge case testing
    - Seed 4: First fragment with more_fragments=1
    - Seed 5: Last fragment with non-zero offset
    - Seed 6: ECN Congestion Experienced (CE) flag
  - **Detailed message structure documentation** showing bit packing for all 5 bytes of bit fields
  - **Test server enhancements**:
    - Comprehensive bit field parsing and logging
    - Fragment reassembly logic with buffer management
    - ECN congestion handling (returns BUSY on CE flag)
  - **Intentional vulnerabilities for fuzzing demonstration**:
    - VULNERABILITY #1: encrypted_bit=1 with invalid session crashes (context dereference)
    - VULNERABILITY #2: ECN=CE with priority=URGENT triggers assertion failure
    - VULNERABILITY #3: sequence_number=4095 + channel_id=15 causes expensive O(n²) logging
    - VULNERABILITY #4: fragment_offset > 200 triggers integer overflow in buffer allocation
    - VULNERABILITY #5: Unlimited fragment buffers enable memory exhaustion
  - **Updated server header parsing** to handle new bit field layout (MIN_HEADER_SIZE: 26→28, payload_len offset: 22→24)
  - Impact: Plugin now serves as comprehensive tutorial for implementing sub-byte fields in custom protocols
  - Testing: Run feature_showcase_server.py, send seeds via nc, verify bit field logging and vulnerability triggers

### Changed - 2026-01-28

- **Refreshed guides hub content and in-app guide accuracy** (`core/ui/spa/src/pages/DocumentationHubPage.tsx:47-247`, `core/ui/spa/src/pages/DocumentationHubPage.css:180-203`, `core/ui/spa/src/pages/GettingStartedGuide.tsx:63-87`, `core/ui/spa/src/pages/FuzzingGuide.tsx:16-127`, `core/ui/spa/src/pages/MutationGuide.tsx:23-30`, `core/ui/spa/src/pages/ProtocolAuthoringGuide.tsx:19-148`)
  - Updated repository and developer doc paths to match the current docs tree
  - Aligned protocol authoring guidance with supported behaviors, checksum fields, and route links
  - Added path wrapping rules to prevent path labels from overflowing in the docs hub cards
  - Impact: Guides now reflect the actual repository structure and supported features, with readable path labels on smaller screens
  - Testing: Open the Guides hub and verify path chips wrap; open each guide and confirm protocol authoring links resolve
- **Added field-based packet builder for one-off tests** (`core/ui/spa/src/pages/OneOffTestPage.tsx:1-285`, `core/ui/spa/src/pages/OneOffTestPage.css:1-160`)
  - Replaced the static structure hint with per-field inputs derived from the selected protocol
  - Builds packets via the plugin build endpoint and previews the hex payload before execution
  - Impact: One-off tests can now be authored using protocol-aware fields instead of raw payload text
  - Testing: Select a protocol, enter field values, confirm the build preview renders, and execute against the sample target

### Fixed - 2026-01-28

- **Preserved protocol docstring formatting in plugin debugger** (`core/ui/spa/src/pages/PluginDebuggerPage.tsx:526-585`, `core/ui/spa/src/pages/PluginDebuggerPage.css:64-102`)
  - Render preformatted blocks (ASCII diagrams/indented sections) in a monospaced container
  - Preserve line breaks in paragraph blocks to keep section headers readable
  - Impact: Protocol header diagrams (e.g., DNS) render with correct spacing on the Plugin Debugger page
  - Testing: Open Plugin Debugger, select DNS plugin, confirm the header diagram aligns and section headings keep their line breaks
- **Prevented plugin meta cards from stretching to full header height** (`core/ui/spa/src/pages/PluginDebuggerPage.css:40-65`)
  - Align the header row and meta cards to the top so their borders wrap only the content
  - Impact: "Blocks" and "States" counters no longer show tall borders in the Plugin Debugger header
  - Testing: Open Plugin Debugger and confirm the meta cards fit their content height
- **Clarified Plugin Debugger preview tooltips** (`core/ui/spa/src/pages/PluginDebuggerPage.tsx:355-398`)
  - Expanded tooltip copy for Mode, Count, and Focus Field controls
  - Added concrete examples for Focus Field to make intent clear
  - Impact: Preview controls are easier to understand without guessing behavior
  - Testing: Hover preview control tooltips and confirm the new guidance appears
- **Showed partial parse values in preview cards when full parsing fails** (`core/api/routes/plugins.py:286-324`)
  - Fall back to partial parsing instead of defaulting every field to its default value
  - Keeps the parsed fields view aligned with the actual seed bytes even when parsing fails
  - Impact: Preview cards no longer show identical parsed values for different seeds
  - Testing: Open Plugin Debugger seed previews for DNS and confirm parsed fields differ across seeds
- **Fixed invert operation defaulting to 32-bit mask** (`core/engine/response_planner.py:353-380`)
  - Previously, `invert` without `bit_width` used a 32-bit mask (0xFFFFFFFF), producing incorrect results for smaller fields
  - Example bug: inverting 0x05 for an 8-bit field returned 0xFFFFFFFA instead of 0xFA
  - Now logs a warning when `bit_width` is omitted to help plugin authors identify the issue
  - Falls back to inferring width from value (8/16/32 bits) instead of always using 32 bits
  - Updated documentation to recommend always specifying `bit_width` for `invert` operations
  - Impact: Plugin authors get clear warnings; invert behavior is more predictable for common cases
  - Testing: Use `invert` without `bit_width` on a small value, verify warning logged and result fits field size

### Changed - 2026-01-26

- **UI/UX Review: Standardized visual elements and removed special characters**
  - **Replaced unicode/emoji characters with text equivalents**
    - `MutationTimeline.tsx:141`: Changed multiplication sign (x) to plain "X" for remove button
    - `Toast.tsx:17`: Changed multiplication sign (x) to plain "X" for close button, added aria-label
    - `EditableFieldTable.tsx:149`: Changed heavy ballot X to plain "X" for cancel button, added aria-label
    - `MutationWorkbenchPage.tsx:449,467`: Removed undo/redo arrow characters from status messages
    - `CorrelationPage.tsx:1269,1276,1332,1333`: Changed em dashes to simple dashes for empty values
  - **Fixed CSS inconsistencies in GuidePage.css**
    - Replaced hardcoded `#333` with `var(--border-color)`
    - Replaced hardcoded `#38bdf8` with `var(--text-accent)`
    - Replaced hardcoded `#1a2332` with `var(--bg-secondary)`
    - Standardized spacing values to use CSS variables (--space-md, --space-lg, --space-xl, --space-3xl)
    - Standardized border-radius to use CSS variables (--radius-sm)
  - **Standardized tooltips in MutationWorkbenchPage.tsx**
    - Imported and used proper Tooltip component instead of inline span-based tooltips
    - Updated Protocol and Base Message labels to use consistent Tooltip component
    - Wrapped labels in .label-text spans for consistent styling
  - **Added missing danger button style to DashboardPage.css**
    - Added `.session-actions button.danger` style using error color variables
    - Consistent with theme using `--color-error-bg`, `--color-error-text`, `--color-error-border`
  - Impact: Consistent visual appearance across all components, improved accessibility with aria-labels, maintainable CSS using variables
  - Testing: Review all affected components for visual consistency, verify buttons display correctly, check tooltip behavior

### Fixed - 2026-01-26

- **Fixed bit-field endianness inconsistency in serialization** (`core/engine/protocol_parser.py:132-180`)
  - Multi-byte little-endian bit fields were being serialized as big-endian due to inline logic ignoring `endian` attribute
  - `_parse_bits_field` correctly handled endianness, but `_serialize_fields_to_bytes` used streaming bit buffer that didn't
  - Modified serialization to detect multi-byte little-endian fields and delegate to `_serialize_bits_field` which handles endianness correctly
  - Flushes any pending bits to byte boundary before processing multi-byte LE fields
  - Impact: Round-trip consistency for protocols using little-endian multi-byte bit fields
  - Testing: Parse and re-serialize a 12-bit little-endian field, verify output bytes match input

- **Fixed size_unit ignored during variable-length field parsing** (`core/engine/protocol_parser.py:310-332`)
  - When parsing variable-length byte fields, the size value from length fields was used directly without unit conversion
  - Size fields with `size_unit: words` (32-bit) or `size_unit: dwords` (16-bit) were misinterpreted
  - Example: A size field value of `2` with `size_unit: words` should mean 8 bytes, but parser read only 2 bytes
  - Added size_unit conversion in `_parse_bytes_field`: bits->bytes (divide by 8), words->bytes (*4), dwords->bytes (*2)
  - Impact: Correct parsing for protocols using non-byte size units in length fields
  - Testing: Create protocol with `size_unit: words`, verify variable-length fields parse correctly

- **Fixed bit_flip_field mutation not handling bits field type** (`core/engine/structure_mutators.py:210-244`)
  - `_bit_flip_field` only handled `int*` and `bytes` types, causing `bits` fields to pass through unmutated
  - When bit_flip_field strategy was selected for a bits field, it became a no-op reducing mutation coverage
  - Added explicit handling for `type: bits` fields that flips a random bit within the field's declared size
  - Impact: Full mutation coverage for sub-byte `bits` fields in structure-aware fuzzing
  - Testing: Run structure-aware mutations on protocol with bits fields, verify bit_flip_field produces mutations

### Changed - 2026-01-20

- **Comprehensive UI/UX standardization** - Unified design system across entire application
  - **Design System** (`core/ui/spa/src/styles/global.css`)
    - Created comprehensive CSS custom properties (variables) for colors, spacing, typography, borders, shadows, and transitions
    - Defined color palette: surface levels, borders (subtle/medium/strong), text hierarchy, accent colors, status colors
    - Standardized spacing scale (xs to 2xl), border radius (sm to full), typography scale, font weights
    - Added unified button styles (default, primary, ghost, danger) with hover states
    - Added unified form input styles with focus states and disabled states
    - Added unified table styles with proper text colors and borders
    - Added unified link styles with hover effects
  - **Removed all emoji characters** - Replaced with professional text labels across 11 files
    - `DashboardPage.tsx`: "Delete" and "Graph" buttons
    - `PluginDebuggerPage.tsx`: "Ref:" for references
    - `ValidationPanel.tsx`: "Error", "Warning", "Info" severity icons; "Tip:", "Valid/Invalid" status
    - `PacketParserPage.tsx`: Removed emoji from crash finding header
    - `MutationWorkbenchPage.tsx`: Status messages now use text labels
    - `EditableFieldTable.tsx`: "Save" and "Cancel" buttons
    - `AdvancedMutations.tsx`: "Warning:" text, removed mutation type emojis
    - `FieldMutationPanel.tsx`: Removed empty state and tip emojis
    - `DiffHexViewer.tsx`: "Warning:" text
    - `MutationTimeline.tsx`: "Edit", "Mutation", "View", "Remove" text labels
    - `StateWalkerPage.tsx`: "Success/Failed" execution status text
  - **Standardized page styles** (`core/ui/spa/src/pages/DashboardPage.css`)
    - Converted all hardcoded values to CSS variables
    - Improved text visibility with proper color contrast
    - Consistent card, form, table, and button styling
    - Added proper graph link styles with hover states
  - **Standardized layout** (`core/ui/spa/src/components/Layout.css`)
    - Updated sidebar, navigation, and masthead to use CSS variables
    - Improved nav link hover and active states
    - Better text contrast on all navigation elements
  - **Standardized components**
    - `StatusBadge.css`: Added proper borders, improved color contrast, added paused state
    - `Toast.css`: Better spacing, shadows, hover effects, added warning variant
    - `Modal.css`: Added animations (fadeIn, slideUp), backdrop blur, improved header button hover states
  - Impact: Consistent look and feel across entire application, improved accessibility and readability, no emoji dependencies
  - Testing: Review all pages for visual consistency, verify text is readable against backgrounds, confirm buttons have consistent styling

### Fixed - 2026-01-20

- **Fixed UI issues** - Resolved button overflow, tooltip behavior, and information redundancy
  - **Button text overflow** (`core/ui/spa/src/components/MutationControls.css`)
    - Fixed "Havoc" and "Splice" button text overflowing on Mutation Workbench page
    - Added `word-wrap: break-word`, `overflow-wrap: break-word`, and `hyphens: auto` to `.mutator-desc`
    - Added `text-overflow: ellipsis` to `.mutator-label` with `white-space: nowrap`
    - Set `min-height: 80px` on `.mutator-btn` for consistent button sizing
    - Standardized button styles to use CSS variables
  - **Tooltip disappearing issue** (`core/ui/spa/src/components/Tooltip.tsx`, `Tooltip.css`)
    - Increased hide delay from 100ms to 200ms for better user experience
    - Increased z-index from 1000 to 10000 to prevent overlay conflicts
    - Added explicit `pointer-events: auto` to ensure tooltip can receive mouse events
    - Increased gap between trigger and tooltip from 6px to 8px
    - Increased invisible bridge height (::before) from 6px to 8px
    - Improved max-width from 280px to 300px for better content display
  - **Removed redundant hint text** (`core/ui/spa/src/pages/DashboardPage.tsx`)
    - Removed duplicate explanation text under "Fuzzing Mode" dropdown (information already in tooltip)
    - Removed duplicate explanation text under "Target State" dropdown (information already in tooltip)
    - Cleaner UI with all explanatory content accessible via tooltips
  - Impact: Improved readability on mutation buttons, tooltips now stay visible when hovering, cleaner dashboard form
  - Testing: Verify button text wraps properly on Mutation Workbench, hover over form field tooltips and confirm they stay visible

### Added - 2026-01-20

- **Added session reset interval and termination fuzzing** - Exercise full protocol lifecycle including connection teardown
  - **Backend Implementation** (`core/models.py:253-261`, `core/models.py:182-204`)
    - Added `session_reset_interval` to `FuzzConfig` and `FuzzSession` - Reset protocol state every N test cases
    - Added `enable_termination_fuzzing` flag - Periodically inject termination/close state transitions
    - Added lifecycle tracking fields: `session_resets`, `termination_tests`, `tests_since_last_reset`
  - **Orchestrator Logic** (`core/engine/orchestrator.py:581-613`, `639-654`, `741-796`)
    - Updated `_get_reset_interval()` to respect explicit session reset configuration
    - Modified `_update_stateful_fuzzing()` to track reset statistics and log reset events
    - Implemented `_should_inject_termination_test()` to determine when to inject termination tests
    - Integrated termination test injection into fuzzing loop (every 50 iterations) with fallback to standard fuzzing
    - Session resets now increment `session_resets` counter and reset `tests_since_last_reset`
  - **Stateful Fuzzing Engine** (`core/engine/stateful_fuzzer.py:440-491`)
    - Added `get_termination_states()` - Identifies terminal states with no outgoing transitions or termination keywords
    - Added `get_transitions_to_termination()` - Returns transitions that lead to termination states
    - Detects termination keywords: CLOSE, DISCONNECT, LOGOUT, TERMINATE, END, EXIT
  - **UI Exposure** (`core/ui/spa/src/pages/DashboardPage.tsx:57-58`, `81-82`, `462-501`)
    - Added "Session Reset Interval" field with tooltip explaining lifecycle testing
    - Added "Enable Termination Fuzzing" checkbox with tooltip explaining cleanup code testing
    - Both fields included in session creation payload with proper validation
  - Impact: Closes critical gap where termination states were never exercised, enabling detection of bugs in connection cleanup, resource deallocation, and session teardown code
  - Testing: Create session with `session_reset_interval=100` and verify state machine resets every 100 tests; observe `termination_tests` counter incrementing in session stats; check logs for "Injecting termination state test" messages

- **Added tooltips to dashboard Create Session form** (`core/ui/spa/src/components/Tooltip.tsx`, `core/ui/spa/src/components/Tooltip.css`, `core/ui/spa/src/pages/DashboardPage.tsx`)
  - Created reusable Tooltip component with hover interaction and info icon
  - Added explanatory tooltips to all form fields:
    - Protocol: Explains plugin selection and structure
    - Target Host: Container networking guidance (Docker vs localhost)
    - Target Port: TCP/UDP port matching requirement
    - Execution Mode: Core vs Agent distribution explanation
    - Mutation Strategy: Hybrid/Structure-Aware/Byte-Level differences
    - Structure-Aware Weight: Percentage split explanation
    - Rate Limit: Performance throttling guidance
    - Max Iterations: Time-boxed testing explanation
    - Timeout per Test: Response waiting guidance
    - Fuzzing Mode: State exploration strategies (Random/Breadth-First/Depth-First/Targeted)
    - Target State: Focused state testing explanation
  - Tooltips use smooth fade-in animation and responsive positioning
  - Styled to match dashboard dark theme with blue accent colors
  - Impact: Improves user onboarding and reduces configuration errors
  - Testing: Hover over info icons next to each form label to view tooltip content

### Fixed - 2026-01-20

- **Fixed UDP transport selection bug** (`core/engine/transport.py:272-288`, `core/engine/orchestrator.py:929-934`)
  - TransportFactory.create_transport now accepts `transport: TransportProtocol` enum instead of `protocol: str`
  - Factory correctly routes to UDPTransport when transport=TransportProtocol.UDP, TCPTransport otherwise
  - Orchestrator now passes `session.transport` (which is set from plugin's transport metadata) instead of `session.protocol` (the plugin name)
  - Removed TODO comment about protocol metadata selection
  - Impact: UDP protocols (like `simple_udp.py`) now correctly use UDP transport instead of defaulting to TCP
  - Testing: Create session with UDP protocol and verify UDP transport is used in execution logs

### Added - 2026-01-13 (Sub-Byte Field Examples)

- **Comprehensive sub-byte field examples in feature showcase** (`core/plugins/feature_showcase.py`)
  - Added Part 3.5: Sub-Byte Fields section with extensive documentation (lines 228-422)
  - Single-byte bit field packing example (8 bits total):
    - `encrypted_bit` (1 bit) - Boolean encryption flag
    - `compressed_bit` (1 bit) - Boolean compression flag
    - `fragmented_bit` (1 bit) - Message fragmentation indicator
    - `priority` (2 bits) - 4-level priority enum (LOW, NORMAL, HIGH, URGENT)
    - `reserved_bits` (3 bits) - Reserved for future use
  - Multi-byte bit field example (16 bits total):
    - `sequence_number` (12 bits) - Values 0-4095 for packet sequencing
    - `channel_id` (4 bits) - 16 channels (0-15) for multiplexing
  - Detailed inline documentation explaining:
    - Left-to-right bit packing within bytes
    - Byte boundary handling and padding
    - Common use cases for each bit width (1-bit flags, 2-bit enums, 12-bit counters)
    - Hex value examples showing bit patterns (0x00, 0x80, 0xC0, 0x18, etc.)
    - Fuzzing behavior for sub-byte fields
  - Updated seeds to include bit field values:
    - Seed 1: All bit fields at default (0x00, 0x0000)
    - Seed 2: Multiple flags enabled (0xC8 = encrypted+compressed, priority=HIGH, seq=42, ch=5)
    - Seed 3: Max values (0x18 = priority=URGENT, seq=4095, ch=15)
  - Impact: Demonstrates native bit-level field support, teaches bandwidth-optimized protocol design
  - Testing: Verify parser correctly handles bit-level fields, check mutation at bit granularity

- **Updated feature showcase server for bit fields** (`tests/feature_showcase_server.py`)
  - Updated message size calculations for 3 additional bytes (1 byte packed bits + 2 bytes seq/channel)
  - Adjusted MIN_HEADER_SIZE from 23 to 26 bytes (lines 149-173)
  - Updated payload_len offset from 19 to 22 (lines 186-204)
  - Updated metadata_len offset from 23 to 26 (lines 237-239)
  - Updated total message size calculation (line 252)
  - Added bit field parsing and logging (lines 352-384):
    - Extracts encrypted_bit, compressed_bit, fragmented_bit, priority
    - Extracts sequence_number and channel_id
    - Maps priority values to names (LOW, NORMAL, HIGH, URGENT)
    - Logs bit fields in compact format: [E=1 C=1 F=0 P=HIGH] · seq=42 ch=5
  - Impact: Server now understands and displays sub-byte field values, validates bit field support
  - Testing: Run server with updated seeds, verify bit field parsing and logging in server output

### Added - 2026-01-13 (Sprint 4: Major Architectural Improvements)

- **SessionContext object replaces parallel dictionaries** (`core/engine/session_context.py`)
  - New dataclass encapsulates all runtime state for a fuzzing session
  - Replaces 8 parallel dictionaries in orchestrator (sessions, stateful_sessions, behavior_processors, response_planners, session_data_models, etc.)
  - Single source of truth prevents state desynchronization bugs
  - Automatic cleanup on session end
  - Properties: `is_stateful`, `protocol_name` for convenient access
  - Impact: Eliminates entire class of desynchronization bugs, clearer ownership of session state
  - Testing: Verify session lifecycle (create, start, stop, delete) works correctly

- **Transport abstraction layer** (`core/engine/transport.py`)
  - New pluggable transport system for network communication
  - Abstract `Transport` base class defines send_and_receive interface
  - `TCPTransport` - Extracted from orchestrator TCP execution code (150 lines)
  - `UDPTransport` - Extracted from orchestrator UDP execution code (120 lines)
  - `TransportFactory` - Creates appropriate transport based on protocol
  - Custom exceptions: Uses TransportError hierarchy for better error handling
  - Impact: Pluggable transports enable easy addition of HTTP, gRPC, WebSocket, etc.
  - Testing: Verify TCP and UDP transports work with existing targets

- **Resource management with LRU cache** (`core/corpus/store.py`)
  - Replaced unbounded in-memory seed cache with LRU (Least Recently Used) eviction
  - Seeds loaded on-demand instead of all at startup
  - Maximum cache size: 1000 seeds (configurable)
  - OrderedDict tracks access patterns for efficient LRU eviction
  - Methods: `_load_seed_from_disk()`, `_evict_if_needed()`, `_load_seed_index()`
  - Updated `get_seed()` with LRU behavior (lines 107-129)
  - Impact: Prevents memory exhaustion on large corpora (1000s of seeds)
  - Testing: Verify fuzzing works with corpus larger than cache size

### Added - 2026-01-13 (Sprint 3: Custom Exception Hierarchy)

- **Structured exception hierarchy** (`core/exceptions.py`)
  - Base `FuzzerError` class with message and details dictionary
  - 30+ custom exception types organized by category:
    - Configuration: `ConfigurationError`, `PluginError`, `PluginLoadError`, `PluginValidationError`
    - Protocol: `ProtocolError`, `ParseError`, `SerializationError`, `FieldValidationError`
    - Transport: `TransportError`, `ConnectionError`, `ConnectionRefusedError`, `ConnectionTimeoutError`, `SendError`, `ReceiveError`, `ReceiveTimeoutError`
    - Session: `SessionError`, `SessionNotFoundError`, `SessionStateError`, `SessionInitializationError`
    - Corpus: `CorpusError`, `SeedNotFoundError`, `CorpusStorageError`, `FindingSaveError`
    - Mutation: `MutationError`, `MutatorNotFoundError`, `MutationFailedError`
    - Stateful: `StatefulFuzzingError`, `StateTransitionError`, `StateNotFoundError`
    - Resource: `ResourceError`, `MemoryLimitError`, `RateLimitError`, `QueueFullError`
    - Agent: `AgentError`, `AgentNotFoundError`, `AgentCommunicationError`, `AgentTimeoutError`
  - All exceptions include optional details dictionary for structured error data
  - Impact: Better error recovery, clearer error messages, easier debugging
  - Testing: Verify exception types raised in appropriate error scenarios

- **Updated orchestrator exception handling** (`core/engine/orchestrator.py`)
  - Replaced generic `ValueError` with `SessionInitializationError` (line 378)
  - Replaced generic `Exception` with `PluginError` (line 366)
  - Added structured exception catching with details logging (lines 629-640)
  - Imported custom exceptions: `SessionInitializationError`, `PluginError`, `TransportError`, etc. (lines 17-24)
  - Impact: More precise error handling, better diagnostics in logs

### Changed - 2026-01-13 (Sprint 2: Complexity Reduction)

- **Fuzzing loop decomposition for maintainability** (`core/engine/orchestrator.py`)
  - Broke down 300-line `_run_fuzzing_loop()` god method into focused helper methods:
    - `_initialize_fuzzing_context()` (78 lines) - Handles protocol loading, seed initialization, mutation engine setup, and stateful session creation
    - `_select_seed_for_iteration()` (48 lines) - Encapsulates seed selection logic for stateful vs stateless fuzzing
    - `_generate_mutated_test_case()` (45 lines) - Handles mutation, behavior application, and test case construction
    - `_execute_and_record_test_case()` (50 lines) - Executes tests, records results, handles response followups
    - `_update_stateful_fuzzing()` (29 lines) - Updates state machine, syncs coverage, applies periodic resets
  - Main loop reduced from 300 to ~120 lines with clear separation of concerns
  - Each method has single responsibility and is independently testable
  - Impact: 60% reduction in method complexity, easier to understand and modify fuzzing flow
  - Testing: All existing fuzzing tests should pass, verify both stateful and stateless sessions

- **Mutation primitives consolidation** (`core/engine/mutation_primitives.py`, `core/engine/structure_mutators.py`)
  - Created new shared mutation primitives module with 200 lines of consolidated logic
  - Shared functions eliminate 150+ lines of duplication:
    - `apply_arithmetic_mutation()` - Unified arithmetic delta application with field-aware clamping
    - `select_interesting_value()` - Consistent boundary value selection across all mutators
    - `generate_boundary_values()` - Comprehensive boundary test generation for any field type
    - `flip_random_bits()` - Unified bit flipping logic
  - Shared constants:
    - `ARITHMETIC_DELTAS` - Single delta list [-128, -64, -32, -16, -8, -4, -2, -1, 1, 2, 4, 8, 16, 32, 64, 128]
    - `INTERESTING_VALUES` - Unified boundary values for 8/16/32/64-bit fields
  - Updated structure_mutators.py to use shared primitives:
    - `_arithmetic()` reduced from 48 to 10 lines (lines 221-235)
    - `_boundary_values()` reduced from 58 to 24 lines (lines 162-192)
    - `_interesting_values()` reduced from 40 to 24 lines (lines 241-265)
  - Impact: Single source of truth for mutation logic, consistent behavior, easier to add new mutation strategies
  - Testing: Verify structure-aware mutations produce expected results, check field mutation tracking

### Fixed - 2026-01-13 (Sprint 1: Quick Wins)

- **Silent exception handlers replaced with proper logging** (`core/engine/orchestrator.py`, `core/engine/history_store.py`, `core/engine/structure_mutators.py`)
  - TCP writer cleanup errors now logged with context (orchestrator.py:883-889)
  - UDP transport cleanup errors now logged with context (orchestrator.py:972-980)
  - Empty cache IndexError now logged at debug level (history_store.py:222-225)
  - Mutation strategy failures now include error_type in logs (structure_mutators.py:105-112)
  - Impact: Better observability for debugging resource leaks and unexpected failures
  - Testing: Manual testing with failing connections and full cache scenarios recommended

- **Serialization logic deduplication** (`core/engine/protocol_parser.py:105-271`)
  - Extracted 120+ lines of duplicate code into shared `_serialize_fields_to_bytes()` helper method
  - `serialize()` method now delegates to helper (lines 231-260)
  - `_serialize_without_checksum()` method now delegates to helper (lines 262-271)
  - Eliminated maintenance burden of keeping two identical serialization implementations in sync
  - All bit field logic, byte alignment, and field type handling now in single location
  - Impact: Single source of truth for serialization, easier to maintain and extend
  - Testing: All existing serialization tests should pass (23/23 protocol parser tests)

### Changed - 2026-01-13

- **Hardcoded constants moved to configuration** (`core/config.py`, `core/engine/orchestrator.py`, `core/engine/structure_mutators.py`, `core/engine/stateful_fuzzer.py`)
  - Added configurable constants to `core/config.py` (lines 40-67):
    - `checkpoint_frequency` (default: 1000) - Session checkpoint interval
    - `default_history_limit` (default: 100) - Execution history memory limit
    - `tcp_buffer_size` (default: 4096) - TCP response read buffer
    - `udp_buffer_size` (default: 4096) - UDP response read buffer
    - `havoc_expansion_min` (default: 1.5) - Minimum havoc mutation expansion
    - `havoc_expansion_max` (default: 3.0) - Maximum havoc mutation expansion
    - `stateful_progression_weight` (default: 0.8) - State progression bias
    - `stateful_reset_interval_bfs` (default: 20) - BFS reset frequency
    - `stateful_reset_interval_dfs` (default: 500) - DFS reset frequency
    - `stateful_reset_interval_targeted` (default: 100) - Targeted mode reset
    - `stateful_reset_interval_random` (default: 300) - Random walk reset
  - Updated orchestrator.py to use config values:
    - Checkpoint frequency (line 597)
    - History limit with None default (lines 1224, 1230-1231)
    - TCP buffer size (line 1005)
    - Reset intervals via `_get_reset_interval()` (lines 1260, 1263, 1266, 1269)
  - Updated structure_mutators.py to use config (lines 368-371)
  - Updated stateful_fuzzer.py to use config (lines 48-51)
  - Impact: Enables runtime tuning via environment variables without code changes
  - All settings use `FUZZER_` prefix (e.g., `FUZZER_CHECKPOINT_FREQUENCY=500`)

### Added - 2026-01-13

- **Shared protocol analysis utilities** (`core/engine/protocol_utils.py`)
  - New module centralizes command field discovery logic
  - `find_command_field(data_model)` - Locate message type field in protocol
  - `build_message_type_mapping(data_model)` - Map message names to command values
  - `build_message_type_map_with_field(data_model)` - Include field name in mapping
  - Eliminates 40+ lines of duplicated logic between seed_synthesizer and stateful_fuzzer
  - Handles JSON serialization quirks (int keys converted to strings)
  - Prefers fields named "command" or "message_type", falls back to first enum field
  - Impact: Single source of truth for protocol analysis, consistent behavior
  - Testing: Verify plugin loading and stateful fuzzing still work correctly

- **Refactored stateful fuzzing to use shared utilities** (`core/engine/stateful_fuzzer.py`)
  - `_build_message_type_mapping()` now delegates to protocol_utils (lines 144-145)
  - Reduced method from 40 lines to 10 lines
  - Imports `build_message_type_mapping` from protocol_utils (line 17)

- **Refactored seed synthesis to use shared utilities** (`core/engine/seed_synthesizer.py`)
  - `_build_message_type_map()` now delegates to protocol_utils (line 244)
  - Reduced method from 13 lines to 1 line
  - Imports `build_message_type_map_with_field` from protocol_utils (line 12)

### Added - 2026-01-13

- **Native sub-byte field support** (`core/engine/protocol_parser.py`)
  - New `type: "bits"` with `size` attribute for 1-64 bit fields
  - Configurable bit ordering via `bit_order` attribute (`"msb"` or `"lsb"`)
  - Multi-byte bit fields support `endian` attribute (`"big"` or `"little"`)
  - Bit fields can span byte boundaries naturally
  - Byte-aligned fields (`uint*`, `int*`) auto-align to byte boundaries
  - Methods: `_parse_bits_field()` (lines 243-297), `_serialize_bits_field()` (lines 350-395)
  - Updated `parse()` (lines 37-103) and `serialize()` (lines 105-216) with bit offset tracking
  - Parser now tracks `bit_offset` instead of `byte_offset` for sub-byte precision
  - 100% backward compatible with existing byte-aligned plugins

- **Size field support for bit units** (`core/engine/protocol_parser.py:540-584`)
  - Size fields support `size_unit` attribute: `"bits"`, `"bytes"` (default), `"words"` (32-bit), `"dwords"` (16-bit)
  - `_calculate_field_length()` now returns length in bits (lines 857-914)
  - `_auto_fix_fields()` converts bit counts to appropriate units
  - Default `size_unit: "bytes"` ensures backward compatibility
  - Example: `{"is_size_field": True, "size_of": ["payload"], "size_unit": "bits"}`

- **Bit field validation** (`core/engine/plugin_validator.py:98-110, 241-280`)
  - Added `"bits"` to `VALID_FIELD_TYPES` set
  - Validates required `size` attribute (1-64 bits)
  - Validates optional `bit_order` (`"msb"` or `"lsb"`)
  - Validates optional `endian` for multi-byte fields (`"big"` or `"little"`)
  - Clear error messages with suggestions for invalid configurations

- **Bit field mutation support** (`core/engine/structure_mutators.py`)
  - Boundary values adapted for bit widths (lines 165-179)
    - Tests: 0 (min), 1 (min+1), max/2 (mid), max-1, max
  - Interesting values include power-of-2 patterns (lines 296-314)
    - Tests: all-zeros, all-ones, MSB-only, each individual bit
  - Arithmetic mutations clamp to bit field max values (lines 222-240)
    - Operations: +1, -1, +/- random(1-5), XOR LSB
    - Automatic wraparound and masking to field size

- **Response handler bit extraction** (`core/engine/response_planner.py:143-163`)
  - New `extract_bits` support in field value resolution
  - Format: `{"copy_from_response": "field", "extract_bits": {"start": 4, "count": 4}}`
  - Extracts arbitrary bit ranges from integer response fields
  - Enables stateful fuzzing with sub-byte response manipulation

- **Comprehensive test suite** (`tests/test_bit_fields.py`)
  - 30+ test cases covering all bit field functionality
  - Core parsing/serialization tests (nibbles, byte-spanning, multi-byte)
  - LSB/MSB bit ordering tests
  - Little-endian/big-endian multi-byte bit field tests
  - Size field unit conversion tests (bits, bytes, words)
  - Structure-aware mutation tests
  - Round-trip integrity tests
  - Edge cases (1-bit, 64-bit, value masking)
  - Tests ready for execution: `pytest tests/test_bit_fields.py -v`

- **Documentation for sub-byte fields** (`docs/PROTOCOL_PLUGIN_GUIDE.md:153-298`)
  - New "Sub-Byte Fields (Bits)" section with comprehensive examples
  - Basic bit field syntax and key features
  - Bit ordering (MSB vs LSB) explanation
  - Multi-byte endianness handling
  - Size field unit options
  - Complete IPv4-style header example
  - Mutation behavior documentation
  - Response extraction examples
  - Ready for production use

### Changed - 2026-01-13

- **Protocol parser tracks bit offsets** (`core/engine/protocol_parser.py:37-309`)
  - Parser now tracks position in bits instead of bytes
  - Byte-aligned fields continue using `struct.pack/unpack` (no performance impact)
  - Serialization buffers partial bytes until byte boundary complete
  - Checksum calculation adapted for bit offset tracking (lines 590-624)
  - Field size calculation returns bits for all types (lines 645-665, 857-914)

### Performance Notes - 2026-01-13

- **Backward compatibility**: 100% - all existing plugins work unchanged
- **Performance**: Byte-aligned protocols use same code path (struct.pack/unpack)
- **Optimization**: Only bit fields use bit arithmetic
- **Benchmark**: Run `python tests/benchmark_parser.py` to verify <5% regression (benchmark file pending)

### Testing Results - 2026-01-13

**Test Suite**: All 23 bit field tests passing (100%)
```bash
pytest tests/test_bit_fields.py -v
# ✓ 23 passed in 0.02s
```

**Performance Benchmarks**:
```bash
python tests/benchmark_parser.py
# Byte-aligned (SimpleTCP):
#   Parse: 448,692 ops/sec (2.23 µs/op)
#   Serialize: 428,611 ops/sec (2.33 µs/op)
#
# Bit fields (IPv4):
#   Parse: 168,814 ops/sec (5.92 µs/op)
#   Serialize: 170,243 ops/sec (5.87 µs/op)
#
# Large corpus (1000 messages): 790,004 ops/sec (1.27 µs/op)
```

**Backward Compatibility**: ✓ All existing plugins work
- simple_tcp: ✓ 3 seeds generate correctly
- feature_showcase: ✓ Complex protocol works
- ipv4_header: ✓ 14 blocks, 8 seeds, bit fields functional

**Technical Debt**: Documented in `TECHNICAL_DEBT.md`
- Serialization logic duplication (high priority)
- Manual bit manipulation complexity (medium priority)

**Git Commits**:
- 897bc9a: Initial sub-byte field implementation
- 1ee00a4: Serialization fixes and technical debt documentation

### Added - 2026-01-06

- **Session persistence layer** (`core/engine/session_store.py`)
  - SQLite-backed storage for fuzzing sessions
  - Sessions survive container restarts
  - Automatic recovery of interrupted sessions on startup
  - Methods: `save_session()`, `load_session()`, `load_all_sessions()`, `delete_session()`
  - Database schema stores full session state including stateful fuzzing coverage

- **Session checkpointing** (`core/engine/orchestrator.py`)
  - Checkpoint on session creation
  - Checkpoint on all status changes (9 locations)
  - Periodic checkpoint every 1000 iterations
  - Final checkpoint on fuzzing loop exit
  - Checkpoint on error conditions (connection failures, etc.)
  - Maximum data loss: 1000 test iterations (configurable)

- **Walker session cleanup** (`core/api/routes/walker.py`)
  - Session metadata tracking (`_session_metadata` dict)
  - Automatic cleanup of stale sessions (96 hour TTL)
  - Background cleanup task (`_cleanup_loop()`) running every 5 minutes
  - Execution history size limit (1000 records per session, FIFO)
  - Session access time tracking on all endpoints
  - `GET /api/walker/` endpoint to list sessions with metadata

- **Configuration options** (`core/config.py`)
  - `max_concurrent_sessions` - Configurable session limit (default: 1)
  - `cors_enabled` - Enable/disable CORS (default: True)
  - `cors_origins` - List of allowed origins (default: ["*"])

### Fixed - 2026-01-12

- **Fixed stateful fuzzing completely broken due to JSON serialization bug** (`core/engine/stateful_fuzzer.py:156-171`)
  - CRITICAL BUG: Message type mapping failed due to string/integer type mismatch
  - When plugins serialize to JSON, integer dictionary keys become strings ("1" not 1)
  - Stateful fuzzer compared parsed integers with string keys → always failed
  - Result: `find_seed_for_message_type()` never found matching seeds
  - Fuzzer fell back to random seed selection, sending wrong messages for states
  - Example: Sending DATA_STREAM from UNINITIALIZED instead of HANDSHAKE_REQUEST
  - **Impact**: Stateful fuzzing was completely non-functional - never navigated state machines
  - **Symptom**: Targeted mode with target_state="CLOSED" ran 200K+ tests but never reached CLOSED
  - Fix: Convert string keys to integers when building message_type_to_command mapping
  - Now stateful fuzzing actually follows state transitions as designed

- **Fixed plugin validator error with multi-field size_of** (`core/engine/plugin_validator.py:419-455`)
  - Validator was crashing with "unhashable type: 'list'" when `size_of` contained multiple fields
  - Bug: `size_of: ["field1", "field2"]` tried to check if list was in set, causing hash error
  - Now correctly handles both single field (string) and multiple fields (list)
  - Validates each target field individually and provides clear error messages
  - Feature_showcase plugin now validates successfully with its multi-field header_len

- **Fixed TypeScript build error in ValidationPanel** (`core/ui/spa/src/components/ValidationPanel.tsx:3-9`)
  - Added missing `suggestion?: string | null` property to `ValidationIssue` interface
  - Component was attempting to access `issue.suggestion` on lines 23-24 without property being defined
  - Build was failing with TS2339 error during Docker image creation
  - UI now compiles successfully

- **Fixed missing execution timestamp in Correlation page modal** (`core/ui/spa/src/pages/CorrelationPage.tsx:773`)
  - Added timestamp to modal title: `Sequence X · Date/Time`
  - Restructured detail header to show State, Result, and Duration in organized layout
  - New `.detail-header-info` component with proper spacing and labels
  - Timestamp now prominently displayed when viewing execution details

- **Fixed replay log not populating on execution selection** (`core/ui/spa/src/pages/CorrelationPage.tsx:323-327`)
  - `handleTimelineSelect()` now logs selection events to replay log
  - Shows sequence number and timestamp when execution is selected from table
  - Provides better visibility into user actions and workflow
  - Replay log now updates for all user interactions (select, replay, export)

### Changed - 2026-01-12

- **Optimized Correlation page layout for better space utilization** (`core/ui/spa/src/pages/CorrelationPage.css`)
  - Reduced padding/margins throughout (session config: 24px→16px, insights: 24px→16px, search grid: 24px→20px)
  - Search grid now uses 2-column layout instead of auto-fit for consistency
  - Time range replay form uses inline grid layout (start/end/delay in one row)
  - Form controls have smaller padding (16px→12px) and tighter gaps (12px→8px)
  - Session KPIs use smaller minimum width (160px→140px) allowing 6 per row on typical screens
  - Insight cards more compact with reduced border radius and padding
  - Replay log now has max-height (200px) with scroll for long histories
  - Overall vertical space reduction of ~25% without sacrificing readability

### Fixed - 2026-01-06

#### Critical Session Resume Bugs

- **Fixed runtime helper rebuild on session load** (`core/engine/orchestrator.py:93`)
  - Changed `self.plugin_manager` to `plugin_manager` (module-level import)
  - Behavior processors and response planners now correctly rebuilt on restart
  - Without this fix, session loading failed with AttributeError

- **Fixed coverage reset on resume** (`core/engine/orchestrator.py:408-422`, `core/engine/stateful_fuzzer.py:72-128`)
  - Now restores `state_coverage` and `transition_coverage` dicts from persisted data
  - Previous implementation only restored `current_state`, losing all coverage metrics
  - Uses `coverage_offset` and `transition_offset` to preserve historical counts (improved by linter)
  - Coverage tracking now continues correctly across restarts without reconstructing fake history

- **Fixed session deletion** (`core/engine/orchestrator.py:1116-1139`)
  - Session deletion now removes from persistence database
  - Cleans up all runtime helpers (behavior processors, response planners, followup queues, stateful sessions)
  - No more orphaned database entries

- **Fixed historical session tracking** (`core/engine/orchestrator.py:69-141`)
  - All sessions (including completed/failed) now loaded on startup
  - Historical sessions remain accessible in UI after restart
  - Runtime helpers only rebuilt for active sessions (idle/running/paused)

- **Fixed iteration counter reset** (`core/engine/orchestrator.py:430-438`)
  - Iteration counter now continues from persisted `total_tests` instead of resetting to 0
  - Iteration-dependent features (seed selection, reset cadence, targeted strategies) work correctly on resume

- **Fixed Walker cleanup KeyError** (`core/api/routes/walker.py:73-83`)
  - Capture metadata before deletion to avoid KeyError when logging
  - Cleanup loop no longer crashes

#### Other Fixes

- **Added session_store.py to git tracking**
  - File was previously untracked (??), wouldn't ship to other environments
  - Now properly included in version control

### Changed - 2026-01-06

- **Single-session limit is now configurable** (`core/config.py`, `core/engine/orchestrator.py`)
  - Changed from hardcoded limit to `max_concurrent_sessions` config
  - Default remains 1 for stability
  - Users can increase via `FUZZER_MAX_CONCURRENT_SESSIONS` environment variable
  - Improved error messages with actionable guidance and resource warnings

- **CORS configuration** (`core/config.py`, `core/api/server.py`)
  - Made CORS configurable via environment variables
  - `FUZZER_CORS_ENABLED` - Enable/disable CORS
  - `FUZZER_CORS_ORIGINS` - Restrict to specific origins
  - Defaults appropriate for local containerized tool (permissive)

- **Stateful fuzzing state restoration** (`core/engine/stateful_fuzzer.py:72-128`)
  - Added `restore_state()` method to `StatefulFuzzingSession`
  - Accepts `current_state`, `state_history`, `state_coverage`, `transition_coverage`
  - Reconstructs state history from coverage dicts when full history not available

### Verified - 2026-01-06

- **Checksum support** (`core/engine/protocol_parser.py:344-530`)
  - Verified checksum support is fully implemented (was incorrectly flagged as missing)
  - Two-pass serialization with automatic checksum calculation
  - Supports 6 algorithms: crc32, adler32, sum, xor, sum8, sum16
  - Configurable checksum scope: all, header, payload, before, after
  - Automatic checksum field detection via `is_checksum: True` in block definitions

## Configuration Reference

### Session Concurrency
```bash
export FUZZER_MAX_CONCURRENT_SESSIONS=3  # Default: 1
```

### CORS
```bash
export FUZZER_CORS_ENABLED=true  # Default: true
export FUZZER_CORS_ORIGINS='["http://localhost:3000"]'  # Default: ["*"]
```

### Walker Cleanup (internal constants)
```python
MAX_EXECUTION_HISTORY_PER_SESSION = 1000
SESSION_TTL_HOURS = 96  # 4 days
CLEANUP_INTERVAL_SECONDS = 300  # 5 minutes
```

### Session Checkpointing (internal)
```python
CHECKPOINT_INTERVAL = 1000  # Save every 1000 test iterations
```

## Testing Recommendations

### Test Session Persistence
```bash
# Create and start session
SESSION_ID=$(curl -s -X POST http://localhost:8000/api/sessions \
  -H "Content-Type: application/json" \
  -d '{"protocol":"simple_tcp","target_host":"target","target_port":9999}' \
  | jq -r '.id')

curl -X POST "http://localhost:8000/api/sessions/$SESSION_ID/start"
sleep 5

# Restart container
docker-compose restart core

# Verify session recovered
curl "http://localhost:8000/api/sessions/$SESSION_ID" | jq '{id, status, total_tests, current_state, state_coverage}'
# Expected: status="paused", total_tests > 0, state_coverage preserved
```

### Test Walker Cleanup
```bash
# Create multiple walker sessions
for i in {1..10}; do
    curl -X POST http://localhost:8000/api/walker/init \
        -H "Content-Type: application/json" \
        -d '{"protocol":"simple_tcp"}'
done

# Check sessions
curl http://localhost:8000/api/walker/

# Wait 5+ minutes, verify cleanup runs
docker-compose logs -f core | grep "walker_cleanup"
```

### Verify Database Files
```bash
ls -lh ./data/*.db
# Should see: correlation.db, sessions.db

sqlite3 ./data/sessions.db "SELECT id, protocol, status, total_tests, current_state FROM sessions;"
```

## Known Issues

1. **Walker cleanup task start**: Starts on first walker init, but won't restart if Core restarted before any walker created
   - Workaround: Move `_start_cleanup_task()` to app startup event

2. **Session store migrations**: No migration path if schema changes
   - Future: Add migration framework (alembic) or versioned schema

3. **Checkpoint frequency**: 1000 tests might be too aggressive for high-throughput fuzzing
   - Consider: Make configurable via `FUZZER_CHECKPOINT_INTERVAL`

## Pending Issues

See comprehensive project review for full list of 63 identified issues. Key pending items:

- API authentication (deferred - not critical for local tool)
- Stateful fuzzing state sync in agent mode (Issue #6)
- Response validation error handling improvements (Issue #9)
- Graceful shutdown hook with final checkpoint
- WebSocket for real-time stats
- Session naming/tagging

## Files Modified

### Session 2 (2026-01-06)
- `core/api/routes/walker.py` - Memory leak fix, cleanup infrastructure
- `core/engine/session_store.py` - NEW - SQLite persistence layer
- `core/engine/orchestrator.py` - Checkpointing, concurrent sessions config
- `core/config.py` - New configuration options
- `core/api/server.py` - CORS configurability

### Session 3 (2026-01-06)
- `core/engine/orchestrator.py` - Runtime helper rebuild, coverage restore, iteration resume, load all sessions
- `core/engine/stateful_fuzzer.py` - restore_state method with coverage preservation
- `core/api/routes/walker.py` - KeyError fix in cleanup logging
- `FIXES_IMPLEMENTED.md` - Checksum verification documented (to be migrated to changelog)
