"""Plugin SDK Base and Adapter Contract for AI Fleet OS."""

from abc import ABC, abstractmethod
from typing import Any, AsyncGenerator, Dict, List, Optional


class BaseAgentPlugin(ABC):
    """Abstract Adapter Contract for all Agent plugins."""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """Unique plugin identifier."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name."""
        pass

    @abstractmethod
    async def detect(self) -> bool:
        """Check if binary/CLI tool is installed and reachable."""
        pass

    @abstractmethod
    async def get_version(self) -> str:
        """Return CLI tool version."""
        pass

    @abstractmethod
    async def get_capabilities(self) -> List[str]:
        """Return capabilities: coding, shell, read_files, write_files, vision, etc."""
        pass

    @abstractmethod
    async def run_prompt(
        self,
        prompt: str,
        workspace: Optional[str] = None,
        on_chunk: Optional[any] = None,
    ) -> Dict[str, Any]:
        """Execute a prompt through the CLI tool."""
        pass
