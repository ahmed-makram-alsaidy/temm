import asyncio
import sys
import tempfile
import unittest
from pathlib import Path

import psutil

from core.ai_fleet.engine.process_manager import DuplicateTaskIdError, ProcessManager


class ProcessManagerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = ProcessManager(graceful_shutdown_seconds=0.2)

    async def asyncTearDown(self):
        await self.manager.shutdown()

    async def test_normal_completion_streams_stdout_and_stderr(self):
        chunks = []

        async def on_chunk(text, stream_type):
            chunks.append((stream_type, text))

        result = await self.manager.execute_argv(
            [sys.executable, "-c", "import sys;print('stdout-value');print('stderr-value',file=sys.stderr)"],
            task_id="normal",
            on_chunk=on_chunk,
            timeout_seconds=5,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["outcome"], "completed")
        self.assertIn("stdout-value", result["stdout"])
        self.assertIn("stderr-value", result["stderr"])
        self.assertTrue(any(kind == "stdout" for kind, _ in chunks))
        self.assertTrue(any(kind == "stderr" for kind, _ in chunks))
        self.assertEqual(self.manager.get_receipt("normal"), result)

    async def test_non_zero_exit_is_normalized(self):
        result = await self.manager.execute_argv(
            [sys.executable, "-c", "import sys;print('failure',file=sys.stderr);sys.exit(7)"],
            task_id="non-zero",
            timeout_seconds=5,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["outcome"], "non_zero_exit")
        self.assertEqual(result["error_code"], "non_zero_exit")

    async def test_child_pwd_matches_the_launch_directory(self):
        """A child must never inherit the launcher's PWD.

        Executors that follow the POSIX convention read PWD instead of their real
        working directory, so a stale value moved them outside the workspace they
        were granted while TEMM measured the diff of the workspace they were not
        in.
        """
        script = "import os;print(os.environ.get('PWD', ''));print(os.environ.get('OLDPWD', '<absent>'))"
        with tempfile.TemporaryDirectory() as directory:
            for mode, run in (
                ("argv", lambda: self.manager.execute_argv([sys.executable, "-c", script], task_id="pwd-argv", cwd=directory, env={"PWD": "/somewhere/else", "OLDPWD": "/previous"}, timeout_seconds=10)),
                ("command", lambda: self.manager.execute_command(f'"{sys.executable}" -c "{script}"', task_id="pwd-command", cwd=directory, env={"PWD": "/somewhere/else", "OLDPWD": "/previous"}, timeout_seconds=10)),
            ):
                with self.subTest(mode=mode):
                    result = await run()
                    reported = result["stdout"].splitlines()
                    self.assertEqual(Path(reported[0]).resolve(), Path(directory).resolve())
                    self.assertEqual(reported[1], "<absent>")

    async def test_timeout_cleans_up_process(self):
        result = await self.manager.execute_argv(
            [sys.executable, "-c", "import time;time.sleep(30)"],
            task_id="timeout",
            timeout_seconds=0.1,
        )

        self.assertTrue(result["timed_out"])
        self.assertEqual(result["state"], "timed_out")
        self.assertFalse(psutil.pid_exists(result["pid"]))

    async def test_explicit_cancellation_is_idempotent_while_active(self):
        execution = asyncio.create_task(
            self.manager.execute_argv(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                task_id="cancel",
                timeout_seconds=30,
            )
        )
        await self._wait_until_active("cancel")

        first, second = await asyncio.gather(
            self.manager.cancel("cancel"),
            self.manager.cancel("cancel"),
        )
        result = await execution

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertTrue(result["cancelled"])
        self.assertEqual(result["outcome"], "cancelled")
        self.assertFalse(psutil.pid_exists(result["pid"]))
        self.assertFalse(await self.manager.cancel("cancel"))

    @unittest.skipUnless(sys.platform == "win32", "Windows graceful process-group signal")
    async def test_windows_cancellation_waits_before_force_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "graceful.txt"
            ready = Path(folder) / "ready.txt"
            code = (
                "import pathlib,signal,sys,time;"
                f"marker=pathlib.Path({str(marker)!r});"
                f"ready=pathlib.Path({str(ready)!r});"
                "signal.signal(signal.SIGBREAK,lambda *_:(marker.write_text('graceful'),sys.exit(0)));"
                "ready.write_text('ready');"
                "time.sleep(30)"
            )
            execution = asyncio.create_task(
                self.manager.execute_argv(
                    [sys.executable, "-c", code],
                    task_id="graceful-cancel",
                    timeout_seconds=30,
                )
            )
            await self._wait_until_active("graceful-cancel")
            await self._wait_for_file(ready)
            await self.manager.cancel("graceful-cancel")
            result = await execution

            self.assertTrue(result["cancelled"])
            self.assertGreaterEqual(result["duration_ms"], 200)
            self.assertFalse(psutil.pid_exists(result["pid"]))
            if marker.exists():
                self.assertEqual(marker.read_text(), "graceful")

    async def test_timeout_cleans_up_child_process_tree(self):
        with tempfile.TemporaryDirectory() as folder:
            pid_file = Path(folder) / "child.pid"
            child_code = "import time;time.sleep(30)"
            parent_code = (
                "import pathlib,subprocess,sys,time;"
                f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));"
                "time.sleep(30)"
            )
            execution = asyncio.create_task(
                self.manager.execute_argv(
                    [sys.executable, "-c", parent_code],
                    task_id="tree-timeout",
                    timeout_seconds=0.5,
                )
            )
            await self._wait_for_file(pid_file)
            child_pid = int(pid_file.read_text())
            result = await execution

            self.assertTrue(result["timed_out"])
            await self._wait_for_pid_exit(child_pid)
            self.assertFalse(psutil.pid_exists(child_pid))

    async def test_timeout_returns_when_descendant_keeps_inherited_pipes_open(self):
        with tempfile.TemporaryDirectory() as folder:
            child_pid_file = Path(folder) / "child.pid"
            parent_code = (
                "import pathlib,subprocess,sys,time;"
                f"p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                f"pathlib.Path({str(child_pid_file)!r}).write_text(str(p.pid));"
                "time.sleep(30)"
            )
            started = asyncio.get_running_loop().time()
            result = await self.manager.execute_argv(
                [sys.executable, "-c", parent_code],
                task_id="inherited-pipe-timeout",
                timeout_seconds=0.2,
            )
            elapsed = asyncio.get_running_loop().time() - started
            self.assertTrue(result["timed_out"])
            self.assertLess(elapsed, 3.0)
            if child_pid_file.exists():
                self.assertFalse(psutil.pid_exists(int(child_pid_file.read_text())))

    async def test_clean_exit_reaps_the_background_process_it_orphaned(self):
        """A process the execution left running is the execution's to stop.

        Reaping only ran when TEMM stopped the process itself, so exiting 0 was
        the one path that leaked. An executor that starts a dev server and then
        exits leaves it writing inside the workspace, and TEMM attributed those
        writes to the attempt: attempt-1da3a15c1323 created none of its
        contracted files yet was recorded as having changed the SQLite file its
        orphaned backend touched after the run.
        """
        manager = ProcessManager(graceful_shutdown_seconds=0.2, descendant_sample_seconds=0.05)
        try:
            with tempfile.TemporaryDirectory() as folder:
                pid_file = Path(folder) / "server.pid"
                parent_code = (
                    "import pathlib,subprocess,sys,time;"
                    "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],"
                    "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);"
                    f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid));"
                    "time.sleep(0.5)"
                )
                result = await manager.execute_argv(
                    [sys.executable, "-c", parent_code],
                    task_id="orphan-clean-exit",
                    timeout_seconds=20,
                )
                self.assertEqual(result["exit_code"], 0, result["stderr"])
                self.assertTrue(result["success"])
                orphan_pid = int(pid_file.read_text())
                self.assertIn(orphan_pid, result["orphans_reaped"])
                await self._wait_for_pid_exit(orphan_pid)
                self.assertFalse(psutil.pid_exists(orphan_pid))
        finally:
            await manager.shutdown()

    async def test_reaping_spares_a_pid_the_operating_system_reused(self):
        """Identity is pid plus creation time, never pid alone.

        Pids are recycled. Killing on a bare pid match would let one attempt stop
        an unrelated process that happened to inherit a number it once saw.
        """
        manager = ProcessManager(graceful_shutdown_seconds=0.2, descendant_sample_seconds=0.05)
        bystander = await asyncio.create_subprocess_exec(
            sys.executable, "-c", "import time;time.sleep(30)",
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            active = manager._active.setdefault("reuse", __import__("core.ai_fleet.engine.process_manager", fromlist=["ActiveProcess"]).ActiveProcess(task_id="reuse", execution_mode="pipe"))
            # The same pid, recorded with a creation time that is not this process's.
            active.descendants[bystander.pid] = psutil.Process(bystander.pid).create_time() - 3600
            await manager._reap_descendants(active)
            self.assertEqual(active.reaped, [])
            self.assertIsNone(bystander.returncode)
        finally:
            bystander.terminate()
            await bystander.wait()
            manager._active.pop("reuse", None)
            await manager.shutdown()

    async def test_duplicate_active_task_id_is_rejected(self):
        first = asyncio.create_task(
            self.manager.execute_argv(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                task_id="duplicate",
                timeout_seconds=30,
            )
        )
        await self._wait_until_active("duplicate")

        with self.assertRaises(DuplicateTaskIdError):
            await self.manager.execute_argv(
                [sys.executable, "-c", "print('must not run')"],
                task_id="duplicate",
                timeout_seconds=5,
            )

        await self.manager.cancel("duplicate")
        await first

    async def test_missing_executable_returns_launch_receipt(self):
        result = await self.manager.execute_argv(
            ["ai-fleet-executable-that-does-not-exist-9281"],
            task_id="missing",
            timeout_seconds=5,
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["outcome"], "launch_failed")
        self.assertEqual(result["error_code"], "executable_not_found")
        self.assertIsNone(result["pid"])

    async def test_large_stdout_and_stderr_are_drained(self):
        size = 2_000_000
        code = f"import sys;sys.stdout.write('o'*{size});sys.stderr.write('e'*{size})"
        result = await self.manager.execute_argv(
            [sys.executable, "-c", code],
            task_id="large-output",
            timeout_seconds=15,
        )

        self.assertTrue(result["success"])
        self.assertEqual(len(result["stdout"]), size)
        self.assertEqual(len(result["stderr"]), size)

    async def _wait_until_active(self, task_id):
        for _ in range(100):
            if self.manager.is_active(task_id) and self.manager.get_state(task_id) == "running":
                return
            await asyncio.sleep(0.01)
        self.fail(f"{task_id} did not become active")

    async def _wait_for_file(self, path):
        """Wait until the child has written the file, not merely created it.

        `write_text` creates the file and then writes to it, so a reader that stops at
        `exists()` can win that race and read zero bytes - which is why
        `test_timeout_cleans_up_child_process_tree` raised `int('')` inside a loaded
        full suite on 2026-08-22 and passed four times out of four when run alone.
        Both callers write content, and content arriving is what "the child reached
        this point" actually means.
        """
        for _ in range(200):
            try:
                if path.stat().st_size > 0:
                    return
            except OSError:
                pass
            await asyncio.sleep(0.01)
        self.fail(f"{path} was never written")

    async def _wait_for_pid_exit(self, pid):
        for _ in range(200):
            if not psutil.pid_exists(pid):
                return
            await asyncio.sleep(0.01)


if __name__ == "__main__":
    unittest.main()
