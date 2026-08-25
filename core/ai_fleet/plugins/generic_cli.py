"""Generic Zero-Code CLI Adapter for AI Fleet OS."""

import shutil
from typing import Any, Dict, List, Optional
from .base import BaseAgentPlugin
from ..engine.process_manager import process_manager


class GenericCLIAdapter(BaseAgentPlugin):
    """Zero-code adapter capable of running any CLI AI tool via format templates."""

    def __init__(
        self,
        plugin_id: str,
        name: str,
        binary_or_cmd: str,
        version_flag: str = "--version",
        prompt_template: str = "{prompt}",
        workspace_template: str = "",
        capabilities: Optional[List[str]] = None,
    ):
        self._plugin_id = plugin_id
        self._name = name
        self._cmd = binary_or_cmd
        self._version_flag = version_flag
        self._prompt_template = prompt_template
        self._workspace_template = workspace_template
        self._capabilities = capabilities or ["general"]

    @property
    def plugin_id(self) -> str:
        return self._plugin_id

    @property
    def name(self) -> str:
        return self._name

    async def detect(self) -> bool:
        bin_name = self._cmd.split()[0]
        return shutil.which(bin_name) is not None

    async def get_version(self) -> str:
        res = await process_manager.execute_command(
            cmd=f"{self._cmd} {self._version_flag}",
            task_id=f"ver-{self._plugin_id}",
            timeout_seconds=5,
        )
        return res["stdout"].strip().split("\n")[0] if res["success"] else "Unknown"

    async def get_capabilities(self) -> List[str]:
        return self._capabilities

    async def run_prompt(
        self,
        prompt: str,
        workspace: Optional[str] = None,
        on_chunk: Optional[any] = None,
    ) -> Dict[str, Any]:
        arg_prompt = self._prompt_template.replace("{prompt}", prompt)
        arg_workspace = self._workspace_template.replace("{workspace}", workspace) if workspace and self._workspace_template else ""
        
        full_cmd = f"{self._cmd} {arg_workspace} {arg_prompt}".strip()
        
        result = await process_manager.execute_command(
            cmd=full_cmd,
            task_id=f"run-{self._plugin_id}",
            cwd=workspace,
            on_chunk=on_chunk,
        )
        return result
