"""Delegate Skills Adapter and Folder Importer."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from sqlalchemy import select
from ..storage.database import AsyncSessionLocal
from ..storage.models import DelegateSkillRecord
from ..filesystem import path_policy
from ..permissions import Operation, permission_policy
from .process_manager import process_manager


class SkillAdapter:
    """Executes Delegate Skills across PowerShell, Python, and Prompts."""

    async def run_skill(
        self,
        skill_id: str,
        task_input: str,
        workspace: Optional[str] = None,
        permission_profile: str = "safe",
        on_chunk: Optional[any] = None,
    ) -> Dict[str, Any]:
        """Execute a delegate skill."""
        async with AsyncSessionLocal() as session:
            res = await session.execute(select(DelegateSkillRecord).where(DelegateSkillRecord.id == skill_id))
            skill = res.scalar_one_or_none()

        if not skill:
            raise ValueError(f"Skill '{skill_id}' not found.")

        # 1. Prompt-based skill
        if skill.adapter_type == "prompt":
            formatted_prompt = skill.prompt_template.replace("{task}", task_input) if skill.prompt_template else task_input
            return {
                "skill_id": skill_id,
                "skill_name": skill.name,
                "adapter_type": "prompt",
                "formatted_prompt": formatted_prompt,
                "required_capabilities": skill.to_dict()["required_capabilities"],
            }

        # 2. PowerShell Script (.ps1)
        elif skill.adapter_type == "ps1" and skill.script_path:
            if not workspace:
                raise ValueError("An approved workspace is required for script skills.")
            if not permission_policy.allows(permission_profile, {Operation.SHELL, Operation.FILE_READ}):
                raise PermissionError("Workspace permission profile does not allow script execution.")
            script_path = path_policy.contained_file(workspace, skill.script_path)
            result = await process_manager.execute_argv(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script_path), task_input],
                task_id=f"skill-{skill_id}",
                cwd=workspace,
                on_chunk=on_chunk,
            )
            return {
                "skill_id": skill_id,
                "skill_name": skill.name,
                "adapter_type": "ps1",
                "result": result,
            }

        # 3. Python Script (.py)
        elif skill.adapter_type == "python" and skill.script_path:
            if not workspace:
                raise ValueError("An approved workspace is required for script skills.")
            if not permission_policy.allows(permission_profile, {Operation.SHELL, Operation.FILE_READ}):
                raise PermissionError("Workspace permission profile does not allow script execution.")
            script_path = path_policy.contained_file(workspace, skill.script_path)
            result = await process_manager.execute_argv(
                [sys.executable, str(script_path), task_input],
                task_id=f"skill-{skill_id}",
                cwd=workspace,
                on_chunk=on_chunk,
            )
            return {
                "skill_id": skill_id,
                "skill_name": skill.name,
                "adapter_type": "python",
                "result": result,
            }

        return {"skill_id": skill_id, "status": "unsupported_adapter"}

    async def import_skills_folder(self, folder_path: str) -> Dict[str, Any]:
        """Scan a folder and automatically convert .ps1, .py, and .md files into skills."""
        p = path_policy.existing_directory(folder_path)

        imported = []
        for file in p.glob("**/*"):
            if file.is_file() and file.suffix.lower() in [".ps1", ".py", ".md", ".sh"]:
                skill_name = file.stem.replace("-", " ").replace("_", " ").title()
                adapter = "ps1" if file.suffix == ".ps1" else ("python" if file.suffix == ".py" else "prompt")
                
                skill_id = f"custom-{file.stem.lower()[:32]}"
                
                # Check if already exists
                async with AsyncSessionLocal() as session:
                    existing = await session.get(DelegateSkillRecord, skill_id)
                    if not existing:
                        record = DelegateSkillRecord(
                            id=skill_id,
                            name=skill_name,
                            description=f"Auto-imported skill from {file.name}",
                            category="custom",
                            adapter_type=adapter,
                            script_path=str(file.resolve()),
                            prompt_template="{task}" if adapter == "prompt" else "",
                        )
                        session.add(record)
                        await session.commit()
                        imported.append(record.to_dict())

        return {
            "folder": folder_path,
            "imported_count": len(imported),
            "skills": imported,
        }


skill_adapter = SkillAdapter()
