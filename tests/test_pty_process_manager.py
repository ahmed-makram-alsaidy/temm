import asyncio
import re
import sys
import unittest

import psutil

from core.ai_fleet.engine.process_manager import ProcessManager
from core.ai_fleet.engine.pty import PtyFactory, PtySession, PtyUnavailableError


class FakePtySession(PtySession):
    def __init__(self, pid=45678, output=""):
        self._pid = pid
        self.output = asyncio.Queue()
        if output:
            self.output.put_nowait(output)
            self.output.put_nowait("")
        self.writes = []
        self.sizes = []
        self.alive = True
        self.exit_code = 0
        self.terminated = []
        self.closed = False
        self.done = asyncio.Event()
        if output:
            self.done.set()
            self.alive = False

    @property
    def pid(self):
        return self._pid

    async def read(self, size=65536):
        return await self.output.get()

    async def write(self, data):
        if not self.alive:
            raise RuntimeError("PTY session is not running.")
        self.writes.append(data)
        if data.strip() == "finish":
            self.output.put_nowait("finished\r\n")
            self.output.put_nowait("")
            self.exit_code = 0
            self.alive = False
            self.done.set()

    async def resize(self, columns, rows):
        self.sizes.append((columns, rows))

    async def wait(self):
        await self.done.wait()
        return self.exit_code

    async def is_alive(self):
        return self.alive

    async def terminate(self, force=False):
        self.terminated.append(force)
        self.exit_code = 1
        self.alive = False
        self.output.put_nowait("")
        self.done.set()

    async def close(self):
        self.closed = True


class FakePtyFactory(PtyFactory):
    def __init__(self, session=None, available=True, error=None):
        self.session = session or FakePtySession(output="ready\r\n")
        self._available = available
        self.error = error
        self.started = None

    @property
    def available(self):
        return self._available

    @property
    def backend_name(self):
        return "fake" if self.available else None

    @property
    def reason(self):
        return None if self.available else "PTY backend missing."

    async def start(self, args, cwd, env, columns, rows):
        if self.error:
            raise self.error
        self.started = (list(args), cwd, columns, rows)
        return self.session


class PtyProcessManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if hasattr(self, "manager"):
            await self.manager.shutdown()

    async def test_pty_completion_streams_terminal_output_and_receipt(self):
        factory = FakePtyFactory()
        self.manager = ProcessManager(pty_factory=factory)
        chunks = []
        result = await self.manager.execute_pty(
            ["fake"],
            task_id="pty-complete",
            on_chunk=lambda text, stream: chunks.append((stream, text)),
            columns=100,
            rows=24,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["execution_mode"], "pty")
        self.assertIn("ready", result["stdout"])
        self.assertEqual(chunks[0][0], "terminal")
        self.assertEqual(factory.started[2:], (100, 24))
        self.assertTrue(factory.session.closed)
        self.assertEqual(self.manager.get_receipt("pty-complete"), result)

    async def test_pty_stdin_and_resize(self):
        session = FakePtySession()
        factory = FakePtyFactory(session=session)
        self.manager = ProcessManager(pty_factory=factory)
        execution = asyncio.create_task(self.manager.execute_pty(["fake"], task_id="pty-io"))
        await self._wait_until_running("pty-io")

        self.assertTrue(await self.manager.resize("pty-io", 140, 42))
        self.assertTrue(await self.manager.write_stdin("pty-io", "finish\r\n"))
        result = await execution

        self.assertEqual(session.sizes, [(140, 42)])
        self.assertEqual(session.writes, ["finish\r\n"])
        self.assertIn("finished", result["stdout"])
        self.assertFalse(await self.manager.write_stdin("pty-io", "late"))

    async def test_initial_stdin_is_written_after_start(self):
        session = FakePtySession()
        self.manager = ProcessManager(pty_factory=FakePtyFactory(session=session))
        result = await self.manager.execute_pty(
            ["fake"],
            task_id="pty-initial-stdin",
            initial_stdin="finish\r\n",
        )

        self.assertEqual(session.writes, ["finish\r\n"])
        self.assertIn("finished", result["stdout"])

    async def test_pty_cancellation_is_repeated_and_cleans_up(self):
        session = FakePtySession()
        self.manager = ProcessManager(graceful_shutdown_seconds=0.01, pty_factory=FakePtyFactory(session=session))
        execution = asyncio.create_task(self.manager.execute_pty(["fake"], task_id="pty-cancel"))
        await self._wait_until_running("pty-cancel")

        first, second = await asyncio.gather(
            self.manager.cancel("pty-cancel"),
            self.manager.cancel("pty-cancel"),
        )
        result = await execution

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertTrue(result["cancelled"])
        self.assertTrue(session.closed)
        self.assertFalse(await self.manager.cancel("pty-cancel"))

    async def test_pty_startup_failure_creates_receipt(self):
        self.manager = ProcessManager(pty_factory=FakePtyFactory(error=FileNotFoundError("missing")))
        result = await self.manager.execute_pty(["missing"], task_id="pty-missing")

        self.assertEqual(result["outcome"], "launch_failed")
        self.assertEqual(result["error_code"], "executable_not_found")
        self.assertEqual(result["execution_mode"], "pty")
        self.assertFalse(self.manager.is_active("pty-missing"))

    async def test_missing_pty_capability_is_explicit(self):
        self.manager = ProcessManager(pty_factory=FakePtyFactory(available=False))
        with self.assertRaises(PtyUnavailableError):
            await self.manager.execute_pty(["fake"], task_id="pty-unavailable")
        self.assertFalse(self.manager.is_active("pty-unavailable"))
        self.assertFalse(self.manager.pty_capability()["supported"])

    async def test_invalid_resize_is_rejected(self):
        self.manager = ProcessManager(pty_factory=FakePtyFactory())
        with self.assertRaises(ValueError):
            await self.manager.resize("unknown", 0, 0)

    @unittest.skipUnless(sys.platform == "win32", "ConPTY integration requires Windows")
    async def test_windows_conpty_exercises_stdin_output_resize_and_exit(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.2)
        if not self.manager.pty_capability()["supported"]:
            self.skipTest("ConPTY backend is not installed")
        code = "import sys;print('ready',flush=True);value=sys.stdin.readline().strip();print('echo:'+value,flush=True)"
        execution = asyncio.create_task(
            self.manager.execute_pty(
                [sys.executable, "-c", code],
                task_id="conpty-real",
                timeout_seconds=10,
            )
        )
        await self._wait_until_running("conpty-real")
        self.assertTrue(await self.manager.resize("conpty-real", 132, 36))
        self.assertTrue(await self.manager.write_stdin("conpty-real", "hello\r\n"))
        result = await execution

        self.assertTrue(result["success"])
        self.assertIn("ready", result["stdout"])
        self.assertIn("echo:hello", result["stdout"])
        self.assertFalse(psutil.pid_exists(result["pid"]))

    @unittest.skipUnless(sys.platform == "win32", "ConPTY integration requires Windows")
    async def test_windows_conpty_cancellation_terminates_process(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.2)
        if not self.manager.pty_capability()["supported"]:
            self.skipTest("ConPTY backend is not installed")
        execution = asyncio.create_task(
            self.manager.execute_pty(
                [sys.executable, "-c", "import time;print('waiting',flush=True);time.sleep(30)"],
                task_id="conpty-cancel",
                timeout_seconds=30,
            )
        )
        await self._wait_until_running("conpty-cancel")
        self.assertTrue(await self.manager.cancel("conpty-cancel"))
        result = await execution

        self.assertTrue(result["cancelled"])
        self.assertEqual(result["execution_mode"], "pty")
        self.assertFalse(psutil.pid_exists(result["pid"]))

    @unittest.skipUnless(sys.platform == "win32", "ConPTY integration requires Windows")
    async def test_windows_conpty_cancellation_cleans_child_tree(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.2)
        if not self.manager.pty_capability()["supported"]:
            self.skipTest("ConPTY backend is not installed")
        output = []
        child_ready = asyncio.Event()

        def record_output(text, _stream):
            output.append(text)
            if re.search(r"child_pid:(\d+)", "".join(output)):
                child_ready.set()

        parent_code = "import subprocess,sys,time;child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);print(f'child_pid:{child.pid}',flush=True);time.sleep(30)"
        execution = asyncio.create_task(
            self.manager.execute_pty(
                [sys.executable, "-c", parent_code],
                task_id="conpty-tree-cancel",
                timeout_seconds=30,
                on_chunk=record_output,
            )
        )
        await self._wait_until_running("conpty-tree-cancel")
        try:
            await asyncio.wait_for(child_ready.wait(), timeout=10)
        except asyncio.TimeoutError:
            self.fail(f"ConPTY child did not report a pid: {''.join(output)!r}")
        child_match = re.search(r"child_pid:(\d+)", "".join(output))
        self.assertIsNotNone(child_match)
        child_pid = int(child_match.group(1))
        parent_pid = self.manager.get_status("conpty-tree-cancel")["pid"]
        children = []
        for _ in range(500):
            try:
                children = psutil.Process(parent_pid).children(recursive=True)
            except psutil.NoSuchProcess:
                children = []
            if any(child.pid == child_pid for child in children):
                break
            await asyncio.sleep(0.01)
        self.assertTrue(any(child.pid == child_pid for child in children))
        child_pids = [child.pid for child in children]
        self.assertTrue(await self.manager.cancel("conpty-tree-cancel"))
        result = await execution
        for _ in range(200):
            if not any(psutil.pid_exists(pid) for pid in child_pids):
                break
            await asyncio.sleep(0.01)

        self.assertTrue(result["cancelled"])
        self.assertFalse(psutil.pid_exists(result["pid"]))
        self.assertFalse(any(psutil.pid_exists(pid) for pid in child_pids))

    async def _wait_until_running(self, task_id):
        for _ in range(200):
            if self.manager.get_state(task_id) == "running":
                return
            await asyncio.sleep(0.01)
        self.fail(f"{task_id} did not become active: {self.manager.get_receipt(task_id)}")


if __name__ == "__main__":
    unittest.main()
