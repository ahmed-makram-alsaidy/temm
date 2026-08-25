import asyncio
import ctypes
import os
import sys
from abc import ABC, abstractmethod
from typing import Dict, Optional, Sequence


class PtyUnavailableError(RuntimeError):
    pass


class PtySession(ABC):
    @property
    @abstractmethod
    def pid(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def read(self, size: int = 65536) -> str:
        raise NotImplementedError

    @abstractmethod
    async def write(self, data: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def resize(self, columns: int, rows: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def wait(self) -> int:
        raise NotImplementedError

    @abstractmethod
    async def is_alive(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def terminate(self, force: bool = False) -> None:
        raise NotImplementedError

    @abstractmethod
    async def close(self) -> None:
        raise NotImplementedError


class PtyFactory(ABC):
    @property
    @abstractmethod
    def available(self) -> bool:
        raise NotImplementedError

    @property
    @abstractmethod
    def backend_name(self) -> Optional[str]:
        raise NotImplementedError

    @property
    def reason(self) -> Optional[str]:
        return None

    @abstractmethod
    async def start(
        self,
        args: Sequence[str],
        cwd: str,
        env: Dict[str, str],
        columns: int,
        rows: int,
    ) -> PtySession:
        raise NotImplementedError


class WindowsConPtySession(PtySession):
    def __init__(self, process):
        self._process = process
        self._closed = False

    @property
    def pid(self) -> int:
        return self._process.pid

    async def read(self, size: int = 65536) -> str:
        if self._closed:
            return ""
        try:
            return await asyncio.to_thread(self._process.read, size)
        except (EOFError, OSError):
            return ""

    async def write(self, data: str) -> None:
        if self._closed or not await self.is_alive():
            raise RuntimeError("PTY session is not running.")
        await asyncio.to_thread(self._process.write, data)

    async def resize(self, columns: int, rows: int) -> None:
        if self._closed:
            raise RuntimeError("PTY session is closed.")
        await asyncio.to_thread(self._process.setwinsize, rows, columns)

    async def wait(self) -> int:
        if self._closed and self._process.exitstatus is not None:
            return int(self._process.exitstatus)
        status = await asyncio.to_thread(self._process.wait)
        return int(status if status is not None else self._process.exitstatus or 0)

    async def is_alive(self) -> bool:
        if self._closed:
            return False
        return bool(await asyncio.to_thread(self._process.isalive))

    async def terminate(self, force: bool = False) -> None:
        if self._closed:
            return
        try:
            await asyncio.to_thread(self._process.terminate, force)
        except (EOFError, OSError):
            pass

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await asyncio.to_thread(self._process.close, True)
        except (EOFError, OSError):
            pass


class PlatformPtyFactory(PtyFactory):
    def __init__(self):
        self._process_type = None
        self._backend = None
        self._reason = None
        if sys.platform != "win32":
            self._reason = "No PTY backend is installed for this platform."
            return
        try:
            from winpty import Backend, PtyProcess

            self._process_type = PtyProcess
            self._backend = Backend.ConPTY
        except ImportError:
            self._reason = "pywinpty is required for ConPTY support on Windows."

    @property
    def available(self) -> bool:
        return self._process_type is not None

    @property
    def backend_name(self) -> Optional[str]:
        return "conpty" if self.available else None

    @property
    def reason(self) -> Optional[str]:
        return self._reason

    async def start(
        self,
        args: Sequence[str],
        cwd: str,
        env: Dict[str, str],
        columns: int,
        rows: int,
    ) -> PtySession:
        if not self.available:
            raise PtyUnavailableError(self.reason or "PTY execution is unavailable.")
        if not args:
            raise ValueError("At least one executable argument is required.")
        launch_args = list(args)
        launch_args[0] = self._windows_executable_path(launch_args[0])
        process = await asyncio.to_thread(
            self._process_type.spawn,
            launch_args,
            cwd=cwd or os.getcwd(),
            env=env,
            dimensions=(rows, columns),
            backend=self._backend,
        )
        return WindowsConPtySession(process)

    def _windows_executable_path(self, executable: str) -> str:
        if " " not in executable or not os.path.isabs(executable):
            return executable
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(executable, buffer, len(buffer))
        return buffer.value if length else executable
