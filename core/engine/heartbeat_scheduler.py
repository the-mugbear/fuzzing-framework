"""
Heartbeat Scheduler - Sends periodic keepalive messages on persistent connections.

Coordinates with the fuzz loop to prevent message interleaving via mutex,
detects failures, and triggers reconnection when configured.

Key features:
- Runs concurrently with fuzz loop as an async task
- Coordinates sends via ConnectionManager.send_with_lock()
- Supports jitter to avoid predictable patterns
- Supports context-based interval (from_context)
- Configurable failure detection and handling
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Optional, TYPE_CHECKING

import structlog

from core.engine.protocol_parser import ProtocolParser

if TYPE_CHECKING:
    from core.engine.connection_manager import ConnectionManager
    from core.engine.protocol_context import ProtocolContext
    from core.models import FuzzSession

logger = structlog.get_logger()


class HeartbeatStatus(str, Enum):
    """Status of heartbeat for a session."""
    HEALTHY = "healthy"
    WARNING = "warning"  # Some failures but below threshold
    FAILED = "failed"    # Max failures reached
    DISABLED = "disabled"
    STOPPED = "stopped"  # Explicitly stopped


class HeartbeatAbortError(Exception):
    """Raised when heartbeat failures exceed threshold and action is 'abort'."""
    pass


@dataclass
class HeartbeatState:
    """Runtime state for a heartbeat task."""
    session_id: str
    task: Optional[asyncio.Task] = None
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    status: HeartbeatStatus = HeartbeatStatus.DISABLED
    last_sent: Optional[datetime] = None
    last_ack: Optional[datetime] = None
    failures: int = 0
    total_sent: int = 0
    total_acks: int = 0
    interval_ms: int = 0  # Configured interval for status reporting


class HeartbeatScheduler:
    """
    Sends periodic heartbeats without colliding with fuzz traffic.

    Uses the ConnectionManager's send_with_lock() to coordinate sends
    and prevent message interleaving with the main fuzz loop.

    Example usage:
        scheduler = HeartbeatScheduler(connection_manager)

        # Start heartbeat for session
        scheduler.start(session, heartbeat_config, context)

        # ... fuzz loop runs concurrently ...

        # Stop on session end
        scheduler.stop(session.id)

    Configuration example (from plugin):
        heartbeat = {
            "enabled": True,
            "interval_ms": 30000,
            "jitter_ms": 5000,
            "message": {
                "data_model": {
                    "blocks": [
                        {"name": "magic", "type": "bytes", "size": 4, "default": b"BEAT"},
                        {"name": "token", "type": "uint64", "from_context": "auth_token"},
                    ]
                }
            },
            "expect_response": True,
            "response_timeout_ms": 5000,
            "on_timeout": {
                "action": "reconnect",
                "max_failures": 3,
                "rebootstrap": True,
            }
        }
    """

    def __init__(
        self,
        connection_manager: "ConnectionManager",
        reconnect_callback: Optional[Callable[["FuzzSession", bool], Any]] = None,
    ):
        """
        Initialize the HeartbeatScheduler.

        Args:
            connection_manager: ConnectionManager for send coordination
            reconnect_callback: Optional callback when reconnect is triggered
                               (session, rebootstrap) -> None
        """
        self._connection_manager = connection_manager
        self._reconnect_callback = reconnect_callback
        self._states: Dict[str, HeartbeatState] = {}

    def start(
        self,
        session: "FuzzSession",
        config: Dict[str, Any],
        context: "ProtocolContext",
    ) -> None:
        """
        Start heartbeat for a session.

        Args:
            session: The fuzzing session
            config: Heartbeat configuration from plugin
            context: Protocol context for message building
        """
        if not config.get("enabled", False):
            logger.debug(
                "heartbeat_disabled",
                session_id=session.id,
            )
            return

        # Create or reset state
        if session.id in self._states:
            # Stop existing heartbeat first
            self.stop(session.id)

        interval_ms = self._get_interval(config, context)
        jitter_ms = config.get("jitter_ms", 0)

        state = HeartbeatState(session_id=session.id)
        state.status = HeartbeatStatus.HEALTHY
        state.stop_event = asyncio.Event()
        state.interval_ms = interval_ms

        self._states[session.id] = state

        # Start heartbeat task
        state.task = asyncio.create_task(
            self._heartbeat_loop(session, config, context, state)
        )

        logger.info(
            "heartbeat_started",
            session_id=session.id,
            interval_ms=interval_ms,
            jitter_ms=jitter_ms,
        )

        # Update session state
        session.heartbeat_enabled = True

    def stop(self, session_id: str) -> None:
        """
        Stop heartbeat for a session.

        Args:
            session_id: ID of the session to stop heartbeat for
        """
        state = self._states.get(session_id)
        if not state:
            return

        # Signal stop
        state.stop_event.set()
        state.status = HeartbeatStatus.STOPPED

        # Cancel task
        if state.task and not state.task.done():
            state.task.cancel()

        logger.info(
            "heartbeat_stopped",
            session_id=session_id,
            total_sent=state.total_sent,
            total_acks=state.total_acks,
        )

    def stop_all(self) -> None:
        """Stop all heartbeat tasks."""
        for session_id in list(self._states.keys()):
            self.stop(session_id)
        self._states.clear()

    def get_status(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get heartbeat status for a session.

        Returns:
            Status dictionary or None if no heartbeat for session
        """
        state = self._states.get(session_id)
        if not state:
            return None

        return {
            "status": state.status.value,
            "interval_ms": state.interval_ms,
            "last_sent": state.last_sent.isoformat() if state.last_sent else None,
            "last_ack": state.last_ack.isoformat() if state.last_ack else None,
            "failures": state.failures,
            "total_sent": state.total_sent,
            "total_acks": state.total_acks,
        }

    def is_running(self, session_id: str) -> bool:
        """Check if heartbeat is running for a session."""
        state = self._states.get(session_id)
        if not state:
            return False
        return state.task is not None and not state.task.done()

    def reset_failures(self, session_id: str) -> None:
        """Reset failure count for a session (e.g., after successful reconnect)."""
        state = self._states.get(session_id)
        if state:
            state.failures = 0
            state.status = HeartbeatStatus.HEALTHY
            logger.debug(
                "heartbeat_failures_reset",
                session_id=session_id,
            )

    async def _heartbeat_loop(
        self,
        session: "FuzzSession",
        config: Dict[str, Any],
        context: "ProtocolContext",
        state: HeartbeatState,
    ) -> None:
        """
        Main heartbeat loop - runs concurrently with fuzz loop.

        Sends periodic heartbeats and handles failures.
        """
        try:
            while not state.stop_event.is_set():
                # Calculate wait time with jitter
                interval_ms = self._get_interval(config, context)
                jitter_ms = config.get("jitter_ms", 0)

                if jitter_ms > 0:
                    # Add random jitter in range [-jitter, +jitter]
                    jitter = random.randint(-jitter_ms, jitter_ms)
                    wait_ms = max(100, interval_ms + jitter)  # Min 100ms
                else:
                    wait_ms = interval_ms

                # Wait for interval or stop signal
                try:
                    await asyncio.wait_for(
                        state.stop_event.wait(),
                        timeout=wait_ms / 1000,
                    )
                    # Stop event was set
                    break
                except asyncio.TimeoutError:
                    # Normal timeout - time to send heartbeat
                    pass

                # Build heartbeat message
                try:
                    message = self._build_heartbeat(config, context)
                except Exception as e:
                    logger.error(
                        "heartbeat_build_failed",
                        session_id=session.id,
                        error=str(e),
                    )
                    await self._handle_failure(session, config, state, e)
                    continue

                # Send heartbeat with coordination lock
                try:
                    response_timeout_ms = config.get("response_timeout_ms", 5000)

                    response = await self._connection_manager.send_with_lock(
                        session,
                        message,
                        timeout_ms=response_timeout_ms,
                    )

                    state.last_sent = datetime.utcnow()
                    state.total_sent += 1
                    session.heartbeat_last_sent = state.last_sent

                    # Process response if expected
                    if config.get("expect_response", False):
                        if self._is_valid_response(response, config):
                            state.last_ack = datetime.utcnow()
                            state.total_acks += 1
                            state.failures = 0
                            state.status = HeartbeatStatus.HEALTHY
                            session.heartbeat_last_ack = state.last_ack
                            session.heartbeat_failures = 0
                        else:
                            await self._handle_failure(session, config, state)
                    else:
                        # No response expected - consider sent successful
                        state.failures = 0
                        state.status = HeartbeatStatus.HEALTHY

                    logger.debug(
                        "heartbeat_sent",
                        session_id=session.id,
                        response_size=len(response) if response else 0,
                    )

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(
                        "heartbeat_send_failed",
                        session_id=session.id,
                        error=str(e),
                    )
                    await self._handle_failure(session, config, state, e)

        except asyncio.CancelledError:
            logger.debug(
                "heartbeat_loop_cancelled",
                session_id=session.id,
            )
        except HeartbeatAbortError:
            logger.error(
                "heartbeat_aborted",
                session_id=session.id,
                failures=state.failures,
            )
            state.status = HeartbeatStatus.FAILED
        except Exception as e:
            logger.error(
                "heartbeat_loop_error",
                session_id=session.id,
                error=str(e),
            )
            state.status = HeartbeatStatus.FAILED

    async def _handle_failure(
        self,
        session: "FuzzSession",
        config: Dict[str, Any],
        state: HeartbeatState,
        error: Optional[Exception] = None,
    ) -> None:
        """
        Handle heartbeat failure.

        Updates failure count and takes action based on configuration.
        """
        state.failures += 1
        session.heartbeat_failures = state.failures

        on_timeout = config.get("on_timeout", {})
        max_failures = on_timeout.get("max_failures", 3)
        action = on_timeout.get("action", "warn")
        rebootstrap = on_timeout.get("rebootstrap", True)

        logger.warning(
            "heartbeat_failure",
            session_id=session.id,
            failures=state.failures,
            max_failures=max_failures,
            action=action,
        )

        if state.failures < max_failures:
            state.status = HeartbeatStatus.WARNING
            return

        # Max failures reached - take action
        state.status = HeartbeatStatus.FAILED

        if action == "abort":
            raise HeartbeatAbortError(
                f"Heartbeat failed {max_failures} consecutive times"
            )

        elif action == "reconnect":
            try:
                # Trigger reconnection
                await self._connection_manager.reconnect(session, rebootstrap)
                state.failures = 0
                state.status = HeartbeatStatus.HEALTHY
                session.heartbeat_failures = 0

                # Notify callback if registered (supports both sync and async callbacks)
                if self._reconnect_callback:
                    result = self._reconnect_callback(session, rebootstrap)
                    # Await if callback returns a coroutine
                    if asyncio.iscoroutine(result):
                        await result

                logger.info(
                    "heartbeat_triggered_reconnect",
                    session_id=session.id,
                    rebootstrap=rebootstrap,
                )

            except Exception as e:
                logger.error(
                    "heartbeat_reconnect_failed",
                    session_id=session.id,
                    error=str(e),
                )
                raise HeartbeatAbortError(
                    f"Heartbeat reconnect failed: {e}"
                )

        # "warn" action - just log (already done above)

    def _get_interval(
        self,
        config: Dict[str, Any],
        context: "ProtocolContext",
    ) -> int:
        """
        Get heartbeat interval, possibly from context.

        The interval can be:
        - A fixed integer: {"interval_ms": 30000}
        - From context: {"interval_ms": {"from_context": "hb_interval"}}

        Args:
            config: Heartbeat configuration
            context: Protocol context

        Returns:
            Interval in milliseconds
        """
        interval = config.get("interval_ms", 30000)

        if isinstance(interval, dict) and "from_context" in interval:
            context_key = interval["from_context"]
            context_value = context.get(context_key)

            if context_value is not None:
                try:
                    return int(context_value)
                except (TypeError, ValueError):
                    logger.warning(
                        "heartbeat_interval_context_invalid",
                        key=context_key,
                        value=context_value,
                    )

        if isinstance(interval, int):
            return interval

        # Fallback
        return 30000

    def _build_heartbeat(
        self,
        config: Dict[str, Any],
        context: "ProtocolContext",
    ) -> bytes:
        """
        Build heartbeat message from configuration.

        Args:
            config: Heartbeat configuration with message data_model
            context: Protocol context for field resolution

        Returns:
            Serialized heartbeat message

        Raises:
            ValueError: If configuration is invalid
        """
        message_config = config.get("message", {})

        if "data_model" in message_config:
            # Use ProtocolParser to build message
            data_model = message_config["data_model"]
            parser = ProtocolParser(data_model)
            return parser.serialize(parser.build_default_fields(), context=context)

        elif "raw" in message_config:
            # Raw bytes (for simple keepalive)
            raw = message_config["raw"]
            if isinstance(raw, bytes):
                return raw
            elif isinstance(raw, str):
                return bytes.fromhex(raw)

        raise ValueError(
            "Heartbeat message configuration missing 'data_model' or 'raw'"
        )

    def _is_valid_response(
        self,
        response: bytes,
        config: Dict[str, Any],
    ) -> bool:
        """
        Check if heartbeat response is valid.

        Simple validation - checks that we got a non-empty response.
        Can be extended to parse response and check specific fields.

        Args:
            response: Response bytes from server
            config: Heartbeat configuration

        Returns:
            True if response is valid
        """
        if not response:
            return False

        # Check expected magic/type if configured
        expected = config.get("expected_response")
        if expected:
            if isinstance(expected, bytes):
                return response.startswith(expected)
            elif isinstance(expected, str):
                return response.startswith(bytes.fromhex(expected))

        # Any non-empty response is considered valid by default
        return True
