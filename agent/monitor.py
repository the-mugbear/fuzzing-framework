"""
Host-level monitoring for target processes

Implements the "Adverse Effects Monitor" from the blueprint:
- CPU usage monitoring
- Memory leak detection
- Crash detection
- Process state tracking
"""
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

import psutil
import structlog

logger = structlog.get_logger()


@dataclass
class MonitoringResult:
    """Result of monitoring a test case execution"""

    success: bool
    cpu_usage: float  # percent
    memory_usage_mb: float
    execution_time_ms: float
    exit_code: Optional[int] = None
    signal: Optional[int] = None
    crashed: bool = False
    hung: bool = False
    cpu_spike: bool = False
    memory_leak: bool = False
    verdict: str = "pass"
    response: bytes = b""


class ProcessMonitor:
    """
    Monitors a process for adverse effects during fuzzing

    Tracks:
    - CPU usage
    - Memory consumption
    - Process crashes (exit codes, signals)
    - Hangs (timeout detection)
    """

    def __init__(
        self,
        cpu_threshold: float = 90.0,
        memory_threshold_mb: int = 500,
        timeout_sec: float = 5.0,
    ):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold_mb = memory_threshold_mb
        self.timeout_sec = timeout_sec
        self.baseline_memory_mb: Optional[float] = None

    def monitor_process(self, process: psutil.Process, duration_sec: float = 1.0) -> MonitoringResult:
        """
        Monitor a process for adverse effects

        Args:
            process: Process to monitor
            duration_sec: How long to monitor

        Returns:
            MonitoringResult with metrics
        """
        start_time = time.time()
        cpu_samples = []
        memory_samples = []
        crashed = False
        hung = False
        exit_code = None
        signal_num = None

        try:
            # Initial baseline
            if self.baseline_memory_mb is None:
                self.baseline_memory_mb = process.memory_info().rss / (1024 * 1024)

            # Monitor for duration
            end_time = start_time + duration_sec
            while time.time() < end_time:
                try:
                    # Check if process is still alive
                    if not process.is_running():
                        crashed = True
                        try:
                            exit_code = process.wait(timeout=0.1)
                        except:
                            pass
                        break

                    # Sample CPU and memory
                    cpu_percent = process.cpu_percent(interval=0.1)
                    mem_info = process.memory_info()
                    memory_mb = mem_info.rss / (1024 * 1024)

                    cpu_samples.append(cpu_percent)
                    memory_samples.append(memory_mb)

                    time.sleep(0.1)

                except psutil.NoSuchProcess:
                    crashed = True
                    break
                except psutil.AccessDenied:
                    logger.warning("access_denied_monitoring_process", pid=process.pid)
                    break

            # Check for hang (timeout)
            if time.time() >= end_time and process.is_running():
                hung = True

            execution_time = (time.time() - start_time) * 1000

            # Calculate averages
            avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0
            avg_memory = sum(memory_samples) / len(memory_samples) if memory_samples else 0

            # Detect anomalies
            cpu_spike = avg_cpu > self.cpu_threshold
            memory_leak = (avg_memory - self.baseline_memory_mb) > self.memory_threshold_mb

            return MonitoringResult(
                success=not (crashed or hung or cpu_spike or memory_leak),
                cpu_usage=avg_cpu,
                memory_usage_mb=avg_memory,
                execution_time_ms=execution_time,
                exit_code=exit_code,
                signal=signal_num,
                crashed=crashed,
                hung=hung,
                cpu_spike=cpu_spike,
                memory_leak=memory_leak,
            )

        except Exception as e:
            logger.error("monitoring_error", error=str(e))
            return MonitoringResult(
                success=False,
                cpu_usage=0,
                memory_usage_mb=0,
                execution_time_ms=(time.time() - start_time) * 1000,
                crashed=True,
            )


class TargetExecutor:
    """
    Executes test cases against a target and monitors results

    Handles:
    - Sending fuzzed inputs to target
    - Monitoring target process
    - Detecting crashes and anomalies
    """

    def __init__(self, target_host: str, target_port: int, launch_cmd: Optional[str] = None):
        self.target_host = target_host
        self.target_port = target_port
        self.launch_cmd = launch_cmd
        self.monitor = ProcessMonitor()
        self._process_handle: Optional[psutil.Process] = None
        self._popen: Optional[subprocess.Popen] = None
        if self.launch_cmd:
            self._ensure_target_process()

    async def execute_test_case(
        self, test_data: bytes, timeout_sec: float = 5.0
    ) -> MonitoringResult:
        """
        Execute a test case against the target

        Args:
            test_data: Fuzzed input to send
            timeout_sec: Execution timeout

        Returns:
            MonitoringResult
        """
        import socket

        start_time = time.time()
        response = b""
        verdict = "pass"

        try:
            self._ensure_target_process()

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_sec)
            sock.connect((self.target_host, self.target_port))
            sock.sendall(test_data)

            try:
                response = sock.recv(4096)
            except socket.timeout:
                response = b""
                verdict = "hang"
            finally:
                sock.close()

        except ConnectionRefusedError:
            verdict = "crash"
            logger.error("target_connection_refused", host=self.target_host, port=self.target_port)
        except socket.timeout:
            verdict = "hang"
            logger.warning("target_timeout", host=self.target_host, port=self.target_port)
        except Exception as exc:
            verdict = "crash"
            logger.error("execution_error", error=str(exc))

        metrics: Optional[MonitoringResult] = None
        if self._process_handle:
            try:
                metrics = self.monitor.monitor_process(self._process_handle, duration_sec=min(1.0, timeout_sec))
            except Exception as exc:
                logger.warning("process_monitor_failed", error=str(exc))

        execution_time = (time.time() - start_time) * 1000

        if not metrics:
            metrics = MonitoringResult(
                success=verdict == "pass",
                cpu_usage=0.0,
                memory_usage_mb=0.0,
                execution_time_ms=execution_time,
            )

        metrics.execution_time_ms = execution_time
        metrics.response = response
        metrics.verdict = verdict
        if verdict != "pass":
            metrics.success = False
            metrics.crashed = verdict == "crash"
            metrics.hung = verdict == "hang"

        return metrics

    def _ensure_target_process(self) -> None:
        """Launch the target process if a command was provided"""
        if not self.launch_cmd or self._process_handle:
            return

        creationflags = 0
        kwargs = {"shell": True}
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            kwargs["creationflags"] = creationflags
        else:
            kwargs["preexec_fn"] = os.setsid

        self._popen = subprocess.Popen(self.launch_cmd, **kwargs)
        self._process_handle = psutil.Process(self._popen.pid)
        logger.info("launched_target_process", pid=self._popen.pid)

    async def shutdown(self) -> None:
        """Terminate launched target processes"""
        if not self._popen:
            return

        try:
            if os.name == "nt":
                self._popen.terminate()
            else:
                os.killpg(os.getpgid(self._popen.pid), signal.SIGTERM)
            self._popen.wait(timeout=5)
        except Exception as exc:
            logger.warning("failed_to_shutdown_target", error=str(exc))
        finally:
            self._popen = None
            self._process_handle = None
