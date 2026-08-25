import json
from typing import List, Optional

from .storage.models import AgentRecord


def build_cli_args(agent: AgentRecord, prompt: str, workspace: Optional[str] = None) -> List[str]:
    executable = agent.detected_path or agent.cli_command
    if not executable:
        raise ValueError(f"No executable is configured for {agent.name}.")
    if agent.input_method not in {"argument", "stdin"} or agent.output_method not in {"stdout", "json"}:
        raise ValueError(f"{agent.name} uses an unsupported input/output method.")
    try:
        invocation_args = json.loads(agent.invocation_args or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid invocation configuration for {agent.name}.") from exc
    if not isinstance(invocation_args, list) or any(not isinstance(item, str) for item in invocation_args):
        raise ValueError(f"Invalid invocation configuration for {agent.name}.")
    rendered = [item.replace("{prompt}", prompt).replace("{workspace}", workspace or "") for item in invocation_args if agent.input_method == "argument" or "{prompt}" not in item]
    return [executable, *rendered]
