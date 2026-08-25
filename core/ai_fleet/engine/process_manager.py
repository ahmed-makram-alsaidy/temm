"""Unified process and PTY lifecycle for AI Fleet OS."""

import asyncio
import inspect
import os
import signal
import subprocess
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union

import psutil

from .pty import PlatformPtyFactory, PtyFactory, PtySession, PtyUnavailableError
from ..security import SensitiveDataRedactor
from ..storage.secret_vault import secret_vault


ChunkCallback = Callable[[str, str], Union[None, Awaitable[None]]]


class ProcessState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    TERMINATING = "terminating"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


class ProcessOutcome(str, Enum):
    COMPLETED = "completed"
    NON_ZERO_EXIT = "non_zero_exit"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    LAUNCH_FAILED = "launch_failed"


class DuplicateTaskIdError(RuntimeError):
    def __init__(self, task_id: str):
        super().__init__(f"Task id '{task_id}' already has an active execution.")
        self.task_id = task_id


@dataclass
class ActiveProcess:
    task_id: str
    execution_mode: str
    state: ProcessState = ProcessState.STARTING
    process: Optional[asyncio.subprocess.Process] = None
    pty: Optional[PtySession] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cancellation_requested: bool = False
    stop_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    io_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Descendants seen while the execution was running, pid -> creation time.
    # Sampled continuously because a process that exits normally orphans its
    # children: by the time the root is gone the tree can no longer be walked
    # from it, so anything not recorded during the run cannot be reaped after.
    descendants: Dict[int, float] = field(default_factory=dict)
    reaped: List[int] = field(default_factory=list)

    @property
    def pid(self) -> Optional[int]:
        if self.process:
            return self.process.pid
        if self.pty:
            return self.pty.pid
        return None


class ProcessManager:
    def __init__(
        self,
        graceful_shutdown_seconds: float = 2.0,
        receipt_limit: int = 200,
        pty_factory: Optional[PtyFactory] = None,
        descendant_sample_seconds: float = 1.0,
    ):
        self._active: Dict[str, ActiveProcess] = {}
        self._registry_lock = asyncio.Lock()
        self._graceful_shutdown_seconds = graceful_shutdown_seconds
        self._receipt_limit = receipt_limit
        self._receipts: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._pty_factory = pty_factory or PlatformPtyFactory()
        self._descendant_sample_seconds = descendant_sample_seconds

    def pty_capability(self) -> Dict[str, Any]:
        return {
            "supported": self._pty_factory.available,
            "backend": self._pty_factory.backend_name,
            "reason": self._pty_factory.reason,
            "features": ["stdin", "resize", "stream", "cancel"] if self._pty_factory.available else [],
        }

    def _child_env(self, cwd: str, env: Optional[Dict[str, str]]) -> Dict[str, str]:
        """Build the environment for a child process rooted at `cwd`.

        POSIX-style tools read `PWD` in preference to their real working
        directory, and CLI executors do exactly that. An inherited `PWD` from
        whichever shell started TEMM therefore moved executors outside the
        workspace they were granted: launched from Git Bash in the TEMM
        repository, an OpenCode route ran its tools against that repository
        instead of the approved workspace, so the diff TEMM measured and the
        files the executor actually edited were different directories.
        `OLDPWD` is dropped for the same reason - it names a directory the child
        was never granted. The launch cwd is the authoritative binding, so it
        wins over any inherited or caller-supplied value.
        """
        full_env = os.environ.copy()
        if env:
            full_env.update(env)
        full_env["PWD"] = os.path.abspath(cwd)
        full_env.pop("OLDPWD", None)
        return full_env

    async def execute_command(
        self,
        cmd: str,
        task_id: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        on_chunk: Optional[ChunkCallback] = None,
        timeout_seconds: float = 300,
    ) -> Dict[str, Any]:
        resolved_cwd = cwd or os.getcwd()
        return await self._execute(
            task_id=task_id,
            launch=lambda full_env: asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE,
                cwd=resolved_cwd,
                env=full_env,
                **self._platform_launch_options(),
            ),
            env=env,
            cwd=resolved_cwd,
            on_chunk=on_chunk,
            timeout_seconds=timeout_seconds,
        )

    async def execute_argv(
        self,
        args: Sequence[str],
        task_id: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        on_chunk: Optional[ChunkCallback] = None,
        timeout_seconds: float = 600,
        stdin_data: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not args:
            raise ValueError("At least one executable argument is required.")
        launch_args = list(args)
        if sys.platform == "win32" and launch_args[0].lower().endswith((".cmd", ".bat")):
            launch_args = ["cmd.exe", "/d", "/c", "call", *launch_args]
        elif sys.platform == "win32" and launch_args[0].lower().endswith(".ps1"):
            launch_args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", *launch_args]
        resolved_cwd = cwd or os.getcwd()
        return await self._execute(
            task_id=task_id,
            launch=lambda full_env: asyncio.create_subprocess_exec(
                *launch_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.PIPE if stdin_data is not None else asyncio.subprocess.DEVNULL,
                cwd=resolved_cwd,
                env=full_env,
                **self._platform_launch_options(),
            ),
            env=env,
            cwd=resolved_cwd,
            on_chunk=on_chunk,
            timeout_seconds=timeout_seconds,
            initial_stdin=stdin_data,
        )

    async def execute_pty(
        self,
        args: Sequence[str],
        task_id: str,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        on_chunk: Optional[ChunkCallback] = None,
        timeout_seconds: float = 600,
        columns: int = 120,
        rows: int = 30,
        initial_stdin: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not args:
            raise ValueError("At least one executable argument is required.")
        self._validate_dimensions(columns, rows)
        if not self._pty_factory.available:
            raise PtyUnavailableError(self._pty_factory.reason or "PTY execution is unavailable.")
        self._validate_execution(task_id, timeout_seconds)
        active = await self._reserve(task_id, "pty")
        output_chunks: List[str] = []
        outcome = ProcessOutcome.LAUNCH_FAILED
        error_code: Optional[str] = None
        exit_code = -1
        external_cancellation = False
        resolved_cwd = cwd or os.getcwd()
        full_env = self._child_env(resolved_cwd, env)

        try:
            active.pty = await self._pty_factory.start(
                list(args),
                resolved_cwd,
                full_env,
                columns,
                rows,
            )
            if active.cancellation_requested:
                await self._stop_process(active)
            else:
                active.state = ProcessState.RUNNING
            reader = asyncio.create_task(self._read_pty(active.pty, output_chunks, on_chunk))
            if initial_stdin:
                await active.pty.write(initial_stdin)
            waiter = asyncio.create_task(active.pty.wait())
            try:
                exit_code = await asyncio.wait_for(asyncio.shield(waiter), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                active.state = ProcessState.TIMED_OUT
                error_code = "execution_timeout"
                outcome = ProcessOutcome.TIMED_OUT
                await self._stop_process(active)
                exit_code = await waiter
            finally:
                await reader

            if active.cancellation_requested:
                active.state = ProcessState.CANCELLED
                error_code = "execution_cancelled"
                outcome = ProcessOutcome.CANCELLED
            elif outcome == ProcessOutcome.TIMED_OUT:
                active.state = ProcessState.TIMED_OUT
            elif exit_code == 0:
                active.state = ProcessState.COMPLETED
                outcome = ProcessOutcome.COMPLETED
            else:
                active.state = ProcessState.FAILED
                error_code = "non_zero_exit"
                outcome = ProcessOutcome.NON_ZERO_EXIT
        except asyncio.CancelledError:
            external_cancellation = True
            active.cancellation_requested = True
            active.state = ProcessState.CANCELLATION_REQUESTED
            if active.pty is not None:
                await asyncio.shield(self._stop_process(active))
            active.state = ProcessState.CANCELLED
            error_code = "execution_cancelled"
            outcome = ProcessOutcome.CANCELLED
        except FileNotFoundError as exc:
            active.state = ProcessState.FAILED
            error_code = "executable_not_found"
            output_chunks.append(str(exc))
        except Exception as exc:
            active.state = ProcessState.FAILED
            error_code = "launch_failed" if active.pty is None else "execution_failed"
            output_chunks.append(str(exc))
        finally:
            if active.pty is not None:
                await active.pty.close()
            receipt = self._build_receipt(
                active=active,
                outcome=outcome,
                exit_code=exit_code,
                stdout="".join(output_chunks),
                stderr="",
                error_code=error_code,
                timeout_seconds=timeout_seconds,
            )
            await self._release(active, receipt)

        if external_cancellation:
            raise asyncio.CancelledError
        return receipt

    async def write_stdin(self, task_id: str, data: str) -> bool:
        active = self._active.get(task_id)
        if not active or active.state != ProcessState.RUNNING or active.pty is None:
            return False
        async with active.io_lock:
            await active.pty.write(data)
        return True

    async def resize(self, task_id: str, columns: int, rows: int) -> bool:
        self._validate_dimensions(columns, rows)
        active = self._active.get(task_id)
        if not active or active.state != ProcessState.RUNNING or active.pty is None:
            return False
        async with active.io_lock:
            await active.pty.resize(columns, rows)
        return True

    async def cancel(self, task_id: str) -> bool:
        async with self._registry_lock:
            active = self._active.get(task_id)
            if not active:
                return False
            active.cancellation_requested = True
            if active.state not in {ProcessState.TERMINATING, ProcessState.CANCELLED}:
                active.state = ProcessState.CANCELLATION_REQUESTED
        if active.process is not None or active.pty is not None:
            await self._stop_process(active)
        return True

    async def kill_process(self, task_id: str) -> bool:
        return await self.cancel(task_id)

    def is_active(self, task_id: str) -> bool:
        return task_id in self._active

    def get_state(self, task_id: str) -> Optional[str]:
        active = self._active.get(task_id)
        if active:
            return active.state.value
        receipt = self._receipts.get(task_id)
        return receipt.get("state") if receipt else None

    def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        active = self._active.get(task_id)
        if active:
            return {
                "task_id": task_id,
                "state": active.state.value,
                "active": True,
                "execution_mode": active.execution_mode,
                "pid": active.pid,
                "interactive": active.pty is not None,
            }
        receipt = self._receipts.get(task_id)
        if not receipt:
            return None
        return {
            "task_id": task_id,
            "state": receipt["state"],
            "active": False,
            "execution_mode": receipt["execution_mode"],
            "pid": receipt["pid"],
            "interactive": receipt["execution_mode"] == "pty",
            "receipt": dict(receipt),
        }

    def get_receipt(self, task_id: str) -> Optional[Dict[str, Any]]:
        receipt = self._receipts.get(task_id)
        return dict(receipt) if receipt else None

    async def shutdown(self) -> None:
        async with self._registry_lock:
            task_ids = list(self._active)
        await asyncio.gather(*(self.cancel(task_id) for task_id in task_ids), return_exceptions=True)

    async def _execute(
        self,
        task_id: str,
        launch: Callable[[Dict[str, str]], Awaitable[asyncio.subprocess.Process]],
        env: Optional[Dict[str, str]],
        on_chunk: Optional[ChunkCallback],
        timeout_seconds: float,
        cwd: Optional[str] = None,
        initial_stdin: Optional[str] = None,
    ) -> Dict[str, Any]:
        self._validate_execution(task_id, timeout_seconds)
        active = await self._reserve(task_id, "pipe")
        stdout_chunks: List[str] = []
        stderr_chunks: List[str] = []
        outcome = ProcessOutcome.LAUNCH_FAILED
        error_code: Optional[str] = None
        exit_code = -1
        external_cancellation = False
        full_env = self._child_env(cwd or os.getcwd(), env)

        try:
            process = await launch(full_env)
            active.process = process
            if active.cancellation_requested:
                await self._stop_process(active)
            else:
                active.state = ProcessState.RUNNING
            if initial_stdin is not None and process.stdin is not None:
                process.stdin.write(initial_stdin.encode("utf-8"))
                await process.stdin.drain()
                process.stdin.close()
                await process.stdin.wait_closed()
            readers = [
                asyncio.create_task(self._read_stream(process.stdout, "stdout", stdout_chunks, on_chunk)),
                asyncio.create_task(self._read_stream(process.stderr, "stderr", stderr_chunks, on_chunk)),
            ]
            watcher = asyncio.create_task(self._watch_descendants(active))
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                active.state = ProcessState.TIMED_OUT
                error_code = "execution_timeout"
                outcome = ProcessOutcome.TIMED_OUT
                await self._stop_process(active)
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)
                # Descendants can inherit the pipes after the root is killed.
                # Never let pipe draining extend the caller's process timeout.
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*readers, return_exceptions=True),
                        timeout=max(1.0, self._graceful_shutdown_seconds * 3),
                    )
                except asyncio.TimeoutError:
                    for reader in readers:
                        reader.cancel()
                    await asyncio.gather(*readers, return_exceptions=True)

            exit_code = process.returncode if process.returncode is not None else -1
            if active.cancellation_requested:
                active.state = ProcessState.CANCELLED
                error_code = "execution_cancelled"
                outcome = ProcessOutcome.CANCELLED
            elif outcome == ProcessOutcome.TIMED_OUT:
                active.state = ProcessState.TIMED_OUT
            elif exit_code == 0:
                active.state = ProcessState.COMPLETED
                outcome = ProcessOutcome.COMPLETED
            else:
                active.state = ProcessState.FAILED
                error_code = "non_zero_exit"
                outcome = ProcessOutcome.NON_ZERO_EXIT
        except asyncio.CancelledError:
            external_cancellation = True
            active.cancellation_requested = True
            active.state = ProcessState.CANCELLATION_REQUESTED
            if active.process is not None:
                await asyncio.shield(self._stop_process(active))
            active.state = ProcessState.CANCELLED
            error_code = "execution_cancelled"
            outcome = ProcessOutcome.CANCELLED
        except FileNotFoundError as exc:
            active.state = ProcessState.FAILED
            error_code = "executable_not_found"
            stderr_chunks.append(str(exc))
        except Exception as exc:
            active.state = ProcessState.FAILED
            error_code = "launch_failed" if active.process is None else "execution_failed"
            stderr_chunks.append(str(exc))
        finally:
            try:
                # Shielded: a caller cancelling the dispatch must not leave the
                # workspace with live processes writing into it.
                await asyncio.shield(self._reap_descendants(active))
            except (Exception, asyncio.CancelledError):
                pass
            receipt = self._build_receipt(
                active=active,
                outcome=outcome,
                exit_code=exit_code,
                stdout="".join(stdout_chunks),
                stderr="".join(stderr_chunks),
                error_code=error_code,
                timeout_seconds=timeout_seconds,
            )
            await self._release(active, receipt)

        if external_cancellation:
            raise asyncio.CancelledError
        return receipt

    def _validate_execution(self, task_id: str, timeout_seconds: float) -> None:
        if not task_id or not task_id.strip():
            raise ValueError("task_id must not be empty.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")

    def _validate_dimensions(self, columns: int, rows: int) -> None:
        if not 20 <= columns <= 500 or not 5 <= rows <= 200:
            raise ValueError("PTY dimensions must be between 20x5 and 500x200.")

    async def _reserve(self, task_id: str, execution_mode: str) -> ActiveProcess:
        async with self._registry_lock:
            if task_id in self._active:
                raise DuplicateTaskIdError(task_id)
            active = ActiveProcess(task_id=task_id, execution_mode=execution_mode)
            self._active[task_id] = active
            return active

    async def _release(self, active: ActiveProcess, receipt: Dict[str, Any]) -> None:
        async with self._registry_lock:
            if self._active.get(active.task_id) is active:
                self._active.pop(active.task_id, None)
            self._receipts[active.task_id] = receipt
            self._receipts.move_to_end(active.task_id)
            while len(self._receipts) > self._receipt_limit:
                self._receipts.popitem(last=False)

    async def _read_stream(
        self,
        stream: Optional[asyncio.StreamReader],
        stream_type: str,
        chunks: List[str],
        on_chunk: Optional[ChunkCallback],
    ) -> None:
        if stream is None:
            return
        while True:
            data = await stream.read(65536)
            if not data:
                return
            decoded = data.decode("utf-8", errors="replace")
            chunks.append(decoded)
            await self._emit_chunk(decoded, stream_type, on_chunk)

    async def _read_pty(
        self,
        pty: PtySession,
        chunks: List[str],
        on_chunk: Optional[ChunkCallback],
    ) -> None:
        while True:
            data = await pty.read()
            if not data:
                return
            chunks.append(data)
            await self._emit_chunk(data, "terminal", on_chunk)

    async def _emit_chunk(self, text: str, stream_type: str, on_chunk: Optional[ChunkCallback]) -> None:
        if not on_chunk:
            return
        redacted = SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact_text(text)
        try:
            callback_result = on_chunk(redacted, stream_type)
            if inspect.isawaitable(callback_result):
                await callback_result
        except Exception:
            pass

    async def _stop_process(self, active: ActiveProcess) -> None:
        async with active.stop_lock:
            if active.process is not None:
                await self._stop_pipe_process(active)
            elif active.pty is not None:
                await self._stop_pty_process(active)

    async def _stop_pipe_process(self, active: ActiveProcess) -> None:
        process = active.process
        if process is None or process.returncode is not None:
            return
        active.state = ProcessState.TERMINATING
        process_tree = await asyncio.to_thread(self._snapshot_process_tree, process.pid)
        await self._request_graceful_exit(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=self._graceful_shutdown_seconds)
        except asyncio.TimeoutError:
            pass
        alive = [item for item in process_tree if item.is_running()]
        if alive:
            await asyncio.to_thread(self._force_terminate_processes, alive)
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=max(self._graceful_shutdown_seconds, 1.0))
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    async def _stop_pty_process(self, active: ActiveProcess) -> None:
        pty = active.pty
        if pty is None or not await pty.is_alive():
            return
        active.state = ProcessState.TERMINATING
        process_tree = await asyncio.to_thread(self._snapshot_process_tree, pty.pid)
        await pty.terminate(False)
        deadline = asyncio.get_running_loop().time() + self._graceful_shutdown_seconds
        while await pty.is_alive() and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.02)
        alive = [item for item in process_tree if item.is_running()]
        if alive:
            await asyncio.to_thread(self._force_terminate_processes, alive)
        if await pty.is_alive():
            await pty.terminate(True)

    async def _request_graceful_exit(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            if sys.platform == "win32":
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, ValueError, OSError):
            try:
                process.terminate()
            except ProcessLookupError:
                pass

    def _snapshot_process_tree(self, pid: int) -> List[psutil.Process]:
        try:
            parent = psutil.Process(pid)
            return [*parent.children(recursive=True), parent]
        except psutil.NoSuchProcess:
            return []

    async def _watch_descendants(self, active: ActiveProcess) -> None:
        """Record the execution's descendants for as long as it runs.

        A process tree can only be walked from a living root. An executor that
        starts a background server (`npm run dev`) and then exits normally leaves
        that server orphaned, and at that moment nothing links it back to the
        attempt - so it survives, keeps writing inside the workspace, and holds
        its ports. Both effects corrupt measurement rather than merely leaking:
        attempt-1da3a15c1323 exited 0 having created none of its contracted files,
        and the only workspace change TEMM recorded was the SQLite file its
        orphaned backend wrote after the run, which registered as an effect the
        attempt did not produce.

        Sampling is why this is polling rather than a single snapshot, and its
        limit is the sampling interval: a grandchild whose parent both spawned it
        and exited between two samples is never linked to the attempt. The chains
        that leak in practice - a package runner supervising a watcher supervising
        a server - live for the whole run and are seen on the first sample.
        """
        pid = active.pid
        if pid is None:
            return
        while True:
            for child, created in await asyncio.to_thread(self._sample_descendants, pid):
                active.descendants[child] = created
            await asyncio.sleep(self._descendant_sample_seconds)

    def _sample_descendants(self, pid: int) -> List[tuple[int, float]]:
        seen: List[tuple[int, float]] = []
        try:
            for child in psutil.Process(pid).children(recursive=True):
                try:
                    seen.append((child.pid, child.create_time()))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return seen
        return seen

    async def _reap_descendants(self, active: ActiveProcess) -> None:
        """Terminate anything the execution left running, whatever its outcome.

        Reaping used to happen only when TEMM stopped the process itself, so a
        clean exit was the one path that leaked. Creation time is matched as well
        as pid: the operating system reuses pids, and an unrelated process that
        inherited one must never be killed on this attempt's behalf.
        """
        if not active.descendants:
            return
        survivors = await asyncio.to_thread(self._resolve_survivors, dict(active.descendants))
        if not survivors:
            return
        active.reaped = sorted(item.pid for item in survivors)
        await asyncio.to_thread(self._force_terminate_processes, survivors)

    def _resolve_survivors(self, descendants: Dict[int, float]) -> List[psutil.Process]:
        survivors: List[psutil.Process] = []
        for pid, created in descendants.items():
            try:
                process = psutil.Process(pid)
                if process.is_running() and abs(process.create_time() - created) < 1.0:
                    survivors.append(process)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return survivors

    def _force_terminate_processes(self, processes: List[psutil.Process]) -> None:
        for item in reversed(processes):
            try:
                item.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(processes, timeout=max(self._graceful_shutdown_seconds, 0.5))
        for item in alive:
            try:
                item.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.wait_procs(alive, timeout=max(self._graceful_shutdown_seconds, 0.5))

    def _platform_launch_options(self) -> Dict[str, Any]:
        if sys.platform == "win32":
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        return {"start_new_session": True}

    def _build_receipt(
        self,
        active: ActiveProcess,
        outcome: ProcessOutcome,
        exit_code: int,
        stdout: str,
        stderr: str,
        error_code: Optional[str],
        timeout_seconds: float,
    ) -> Dict[str, Any]:
        completed_at = datetime.now(timezone.utc)
        duration_ms = max(0, int((completed_at - active.started_at).total_seconds() * 1000))
        if outcome == ProcessOutcome.TIMED_OUT:
            timeout_message = f"Execution timed out after {timeout_seconds:g}s."
            stderr = f"{stderr.rstrip()}\n{timeout_message}".lstrip()
        elif outcome == ProcessOutcome.CANCELLED:
            cancel_message = "Execution was cancelled."
            stderr = f"{stderr.rstrip()}\n{cancel_message}".lstrip()
        redactor = SensitiveDataRedactor.from_environment(secret_vault.redaction_values())
        stdout = redactor.redact_text(stdout)
        stderr = redactor.redact_text(stderr)
        return {
            "task_id": active.task_id,
            "state": active.state.value,
            "outcome": outcome.value,
            "execution_mode": active.execution_mode,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "success": outcome == ProcessOutcome.COMPLETED,
            "cancelled": outcome == ProcessOutcome.CANCELLED,
            "timed_out": outcome == ProcessOutcome.TIMED_OUT,
            "error_code": error_code,
            "pid": active.pid,
            "started_at": active.started_at.isoformat(),
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
            "orphans_reaped": list(active.reaped),
        }


process_manager = ProcessManager()
