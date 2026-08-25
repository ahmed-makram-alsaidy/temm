import json
import tempfile
import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from ..environment_discovery import EnvironmentInventory, discover_environment
from ..engine.process_manager import ProcessManager
from ..storage.models import ModelRecord, ProviderInstanceRecord
from .run_output import RunOutputService
from .runs import RunLifecycleService
from .executor_capabilities import ExecutorCapabilityService
from .execution_policy import executable_availability_ttl_seconds


class ExternalEnvironmentService:
    async def refresh(self, session: AsyncSession) -> dict:
        inventory = discover_environment()
        await self.import_inventory(session, inventory)
        return inventory.to_dict()

    async def import_inventory(self, session: AsyncSession, inventory: EnvironmentInventory) -> None:
        now = datetime.utcnow()
        availability_ttl = timedelta(seconds=executable_availability_ttl_seconds())
        providers = {provider.provider_id: provider for provider in inventory.providers}
        successful = {probe.get("model_id") for probe in inventory.execution_probes if probe.get("success")}
        verified_providers = {model.provider_id for model in inventory.models if model.model_id in successful}
        for provider in inventory.providers:
            record = await session.get(ProviderInstanceRecord, provider.provider_id)
            values = {
                "name": provider.display_name,
                "adapter_id": provider.source_tool,
                "capabilities": json.dumps(["model_selection", "credential_reference"]),
                "configuration": json.dumps({"protocol": provider.protocol, "base_url": provider.base_url}),
                "secret_refs": json.dumps([provider.auth_reference]),
                "health_state": "available" if provider.verified or provider.provider_id in verified_providers else "unknown",
                "health_evidence": json.dumps({"source": "execution_probe" if provider.provider_id in verified_providers else "external_environment_discovery"}),
                "health_checked_at": now,
                "health_expires_at": now + availability_ttl,
            }
            if record:
                for key, value in values.items():
                    setattr(record, key, value)
                record.revision = (record.revision or 0) + 1
            else:
                session.add(ProviderInstanceRecord(id=provider.provider_id, **values))
        for model in inventory.models:
            if model.source_tool != "opencode-cli":
                continue
            provider = providers.get(model.provider_id)
            provider_name = model.model_id.split("/", 1)[0]
            verified = model.verified or model.model_id in successful
            record = await session.get(ModelRecord, model.model_id)
            values = {
                "name": model.display_name,
                "provider": provider_name,
                "category": "coding",
                "source_type": "external_tool",
                "source_uri": model.source_tool,
                "source_checked_at": now,
                "metadata_provenance": "observed",
                "availability_checked_at": now,
            }
            if verified:
                values.update({
                    "availability_state": "available",
                    "availability_evidence": json.dumps({"source": "probe", "provider_id": model.provider_id, "credential_reference": provider.auth_reference if provider else None}),
                    "availability_expires_at": now + availability_ttl,
                })
            elif not record:
                values.update({"availability_state": "unknown", "availability_evidence": json.dumps({"source": "discovery", "provider_id": model.provider_id, "credential_reference": provider.auth_reference if provider else None}), "availability_expires_at": None})
            else:
                # A refresh supersedes stale availability evidence even when the
                # current inventory does not verify this particular route.
                values.update({
                    "availability_state": "unknown",
                    "availability_evidence": json.dumps({"source": "external_environment_discovery", "provider_id": model.provider_id, "credential_reference": provider.auth_reference if provider else None}),
                    "availability_expires_at": now + availability_ttl,
                })
            if record:
                for key, value in values.items():
                    setattr(record, key, value)
                record.revision = (record.revision or 0) + 1
            else:
                session.add(ModelRecord(id=model.model_id, **values))
        await session.commit()

    async def verify_opencode_model(self, session: AsyncSession, manager: ProcessManager, inventory: EnvironmentInventory, model_id: str, cwd: str, project_id: str | None = None, workspace_id: str | None = None, timeout_seconds: float = 120) -> dict:
        model = next((item for item in inventory.models if item.model_id == model_id and item.source_tool == "opencode-cli"), None)
        if not model:
            raise ValueError("The requested model was not discovered through OpenCode.")
        tool = next((item for item in inventory.tools if item.tool_id == "opencode-cli"), None)
        if not tool:
            raise ValueError("OpenCode is not available for verification.")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        runs = RunLifecycleService()
        output = RunOutputService()
        prompt = "Return exactly TEMM_ROUTE_VERIFIED. Do not use tools and do not modify files."
        await runs.create(session, run_id=run_id, prompt=prompt, routing_mode="external_environment_verification", workspace_id=workspace_id, project_id=project_id)
        await runs.start(session, run_id)
        attempt = await runs.start_attempt(session, run_id, "agent", agent_id="opencode-cli", model_id=model_id, provider_instance_id=model.provider_id)
        chunks = []

        async def on_chunk(text, stream):
            chunks.append({"stream": stream, "content": text})

        receipt = await manager.execute_argv([tool.executable_path, "run", "--agent", "coder", "--model", model_id, "--auto", "--format", "json", prompt], f"environment-probe-{attempt.id}", cwd=cwd, timeout_seconds=timeout_seconds, on_chunk=on_chunk)
        await output.append_many(session, run_id, chunks, attempt.id)
        status = "completed" if receipt["outcome"] == "completed" and "TEMM_ROUTE_VERIFIED" in receipt.get("stdout", "") else "failed"
        error_code = receipt.get("error_code") if status == "failed" else None
        if status == "failed" and receipt["outcome"] == "completed":
            error_code = "verification_output_missing"
        await runs.finalize_attempt(session, attempt.id, status=status, outcome=receipt["outcome"], receipt={key: value for key, value in receipt.items() if key not in {"stdout", "stderr"}}, error_code=error_code)
        await runs.finalize(session, run_id, status, error_code)
        probe = {"tool_id": "opencode-cli", "provider_id": model.provider_id, "model_id": model_id, "run_id": run_id, "attempt_id": attempt.id, "success": status == "completed", "error_code": error_code}
        inventory.execution_probes.append(probe)
        if probe["success"]:
            model.verified = True
            provider = next((item for item in inventory.providers if item.provider_id == model.provider_id), None)
            if provider:
                provider.verified = True
        await self.import_inventory(session, inventory)
        await ExecutorCapabilityService().observe(session, model_id, "text_generation", probe["success"], {"run_id": run_id, "attempt_id": attempt.id, "probe": "exact_text"})
        return probe

    async def verify_opencode_coding_model(self, session: AsyncSession, manager: ProcessManager, inventory: EnvironmentInventory, model_id: str, timeout_seconds: float = 180) -> dict:
        model = next((item for item in inventory.models if item.model_id == model_id and item.source_tool == "opencode-cli"), None)
        tool = next((item for item in inventory.tools if item.tool_id == "opencode-cli"), None)
        if not model or not tool:
            raise ValueError("The requested OpenCode route was not discovered.")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        runs = RunLifecycleService()
        output = RunOutputService()
        prompt = "Create a file named temm-route-proof.txt containing exactly TEMM_CODING_ROUTE_VERIFIED and no newline. Do not create or modify any other file."
        await runs.create(session, run_id=run_id, prompt=prompt, routing_mode="external_coding_verification")
        await runs.start(session, run_id)
        attempt = await runs.start_attempt(session, run_id, "agent", agent_id="opencode-cli", model_id=model_id, provider_instance_id=model.provider_id)
        chunks = []

        async def on_chunk(text, stream):
            chunks.append({"stream": stream, "content": text})

        with tempfile.TemporaryDirectory(prefix="temm-route-proof-") as cwd:
            receipt = await manager.execute_argv([tool.executable_path, "run", "--agent", "coder", "--model", model_id, "--auto", "--format", "json", prompt], f"coding-probe-{attempt.id}", cwd=cwd, timeout_seconds=timeout_seconds, on_chunk=on_chunk)
            proof = __import__("pathlib").Path(cwd) / "temm-route-proof.txt"
            filesystem_verified = proof.is_file() and proof.read_text(encoding="utf-8") == "TEMM_CODING_ROUTE_VERIFIED" and sorted(item.name for item in __import__("pathlib").Path(cwd).iterdir()) == ["temm-route-proof.txt"]
        await output.append_many(session, run_id, chunks, attempt.id)
        status = "completed" if receipt["outcome"] == "completed" and filesystem_verified else "failed"
        error_code = receipt.get("error_code") if status == "failed" else None
        if status == "failed" and receipt["outcome"] == "completed":
            error_code = "coding_verification_failed"
        await runs.finalize_attempt(session, attempt.id, status=status, outcome=receipt["outcome"], receipt={**{key: value for key, value in receipt.items() if key not in {"stdout", "stderr"}}, "filesystem_verified": filesystem_verified}, error_code=error_code)
        await runs.finalize(session, run_id, status, error_code)
        probe = {"tool_id": "opencode-cli", "provider_id": model.provider_id, "model_id": model_id, "capability": "coding", "run_id": run_id, "attempt_id": attempt.id, "success": status == "completed", "filesystem_verified": filesystem_verified, "error_code": error_code}
        inventory.execution_probes.append(probe)
        if probe["success"]:
            model.verified = True
            provider = next((item for item in inventory.providers if item.provider_id == model.provider_id), None)
            if provider:
                provider.verified = True
        await self.import_inventory(session, inventory)
        await ExecutorCapabilityService().certify(session, model_id, {
            "text_generation": receipt["outcome"] == "completed",
            "coding": probe["success"],
            "file_read": probe["success"],
            "file_write": filesystem_verified,
        }, {"run_id": run_id, "attempt_id": attempt.id, "probe": "single_file_write", "filesystem_verified": filesystem_verified})
        return probe

    async def verify_opencode_repair_model(self, session: AsyncSession, manager: ProcessManager, inventory: EnvironmentInventory, model_id: str, timeout_seconds: float = 240) -> dict:
        model = next((item for item in inventory.models if item.model_id == model_id and item.source_tool == "opencode-cli"), None)
        tool = next((item for item in inventory.tools if item.tool_id == "opencode-cli"), None)
        if not model or not tool:
            raise ValueError("The requested OpenCode route was not discovered.")
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        runs = RunLifecycleService()
        output = RunOutputService()
        prompt = "In this disposable npm project: remove only alpha and beta from root dependencies, run npm install --package-lock-only so the lockfile root is synchronized, delete obsolete.txt, create proof-a.txt containing A and proof-b.txt containing B, then run npm run build. Do not modify any other file."
        await runs.create(session, run_id=run_id, prompt=prompt, routing_mode="external_repair_verification")
        await runs.start(session, run_id)
        attempt = await runs.start_attempt(session, run_id, "agent", agent_id="opencode-cli", model_id=model_id, provider_instance_id=model.provider_id)
        chunks = []
        async def on_chunk(text, stream): chunks.append({"stream": stream, "content": text})
        with tempfile.TemporaryDirectory(prefix="temm-repair-proof-") as cwd:
            root = __import__("pathlib").Path(cwd)
            package = {"scripts": {"build": "node -e \"process.exit(0)\""}, "dependencies": {"alpha": "1.0.0", "beta": "1.0.0"}}
            (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
            (root / "package-lock.json").write_text(json.dumps({"name": "proof", "lockfileVersion": 3, "packages": {"": {"dependencies": {"alpha": "1.0.0", "beta": "1.0.0"}}}}), encoding="utf-8")
            (root / "obsolete.txt").write_text("obsolete", encoding="utf-8")
            receipt = await manager.execute_argv([tool.executable_path, "run", "--agent", "coder", "--model", model_id, "--auto", "--format", "json", prompt], f"repair-probe-{attempt.id}", cwd=cwd, timeout_seconds=timeout_seconds, on_chunk=on_chunk)
            try:
                current_package = json.loads((root / "package.json").read_text(encoding="utf-8"))
                current_lock = json.loads((root / "package-lock.json").read_text(encoding="utf-8"))
                dependencies_verified = not current_package.get("dependencies") and not current_lock.get("packages", {}).get("", {}).get("dependencies")
            except (OSError, json.JSONDecodeError):
                dependencies_verified = False
            multi_file_verified = (root / "proof-a.txt").read_text(encoding="utf-8") == "A" and (root / "proof-b.txt").read_text(encoding="utf-8") == "B" if (root / "proof-a.txt").is_file() and (root / "proof-b.txt").is_file() else False
            deletion_verified = not (root / "obsolete.txt").exists()
            command_verified = receipt["outcome"] == "completed" and dependencies_verified
        await output.append_many(session, run_id, chunks, attempt.id)
        success = receipt["outcome"] == "completed" and dependencies_verified and multi_file_verified and deletion_verified
        status = "completed" if success else "failed"
        error_code = receipt.get("error_code") or (None if success else "repair_verification_failed")
        proof = {"dependency_management": dependencies_verified, "multi_file_edit": multi_file_verified and deletion_verified, "command_execution": command_verified}
        await runs.finalize_attempt(session, attempt.id, status=status, outcome=receipt["outcome"], receipt={**{key: value for key, value in receipt.items() if key not in {"stdout", "stderr"}}, "capability_proof": proof}, error_code=error_code)
        await runs.finalize(session, run_id, status, error_code)
        await ExecutorCapabilityService().certify(session, model_id, {"coding": success, "file_read": success, "file_write": multi_file_verified, **proof}, {"run_id": run_id, "attempt_id": attempt.id, "probe": "multi_file_dependency_command"})
        if success:
            model.verified = True
            provider = next((item for item in inventory.providers if item.provider_id == model.provider_id), None)
            if provider:
                provider.verified = True
            inventory.execution_probes.append({"model_id": model_id, "success": True})
            await self.import_inventory(session, inventory)
        return {"tool_id": "opencode-cli", "provider_id": model.provider_id, "model_id": model_id, "run_id": run_id, "attempt_id": attempt.id, "success": success, "capabilities": proof, "error_code": error_code}


external_environment_service = ExternalEnvironmentService()
