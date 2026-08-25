import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import OrchestrationTaskRecord, ProjectNeedRecord
from .orchestration_tasks import OrchestrationTaskService


class QualityRepairDecompositionService:
    async def decompose(self, session: AsyncSession, finding_id: str, parent_task_id: str) -> dict:
        finding = await session.get(ProjectNeedRecord, finding_id)
        parent = await session.get(OrchestrationTaskRecord, parent_task_id)
        if not finding or not parent or finding.project_id != parent.project_id or finding.state != "open" or parent.state not in {"failed", "blocked"}:
            raise DomainError("resource_conflict", message="Open finding and failed/blocked parent repair task are required.")
        existing = (await session.execute(select(OrchestrationTaskRecord).where(OrchestrationTaskRecord.project_id == parent.project_id))).scalars().all()
        children = [task for task in existing if any(ref.get("source_type") == "quality_repair_parent" and ref.get("parent_task_id") == parent.id for ref in json.loads(task.context_refs_json or "[]"))]
        parent_workspace_id = next((ref.get("workspace_id") for ref in json.loads(parent.context_refs_json or "[]") if ref.get("workspace_id")), None)
        if children:
            changed = False
            for child in children:
                refs = json.loads(child.context_refs_json or "[]")
                for ref in refs:
                    if ref.get("source_type") == "files" and not ref.get("workspace_id") and parent_workspace_id:
                        ref["workspace_id"] = parent_workspace_id
                        changed = True
                child.context_refs_json = json.dumps(refs)
                if child.task_type == "verification":
                    acceptance = json.loads(child.acceptance_json or "[]")
                    if acceptance and acceptance[0].get("evaluator", {}).get("type") == "parent_repair_satisfied":
                        child.acceptance_json = json.dumps([self._architecture_criterion()])
                        changed = True
            if changed:
                await session.commit()
            return self._result(finding.id, parent.id, children)

        common_refs = [{"source_type": "quality_finding", "source_id": finding.source_id, "finding_id": finding.id}, {"source_type": "quality_repair_parent", "parent_task_id": parent.id}]
        task_service = OrchestrationTaskService()
        package = await task_service.create(session, parent.project_id, {
            "task_type": "implementation", "title": "Restore localization dependency state",
            "description": "Remove only i18next and react-i18next from root dependencies, synchronize package-lock root dependencies, and remove src/i18n/index.ts. Do not modify application source files.",
            "acceptance": [
                {"criterion_id": "repair:package-json", "description": "Incorrect localization root dependencies are absent.", "evaluator": {"type": "json_root_dependencies_absent", "path": "package.json", "names": ["i18next", "react-i18next"]}},
                {"criterion_id": "repair:package-lock", "description": "Lockfile root dependencies are synchronized.", "evaluator": {"type": "json_root_dependencies_absent", "path": "package-lock.json", "names": ["i18next", "react-i18next"]}},
                {"criterion_id": "repair:i18n-bootstrap", "description": "Incorrect i18n bootstrap is absent.", "evaluator": {"type": "path_absent", "path": "src/i18n/index.ts"}},
                {"criterion_id": "repair:dependency-scope", "description": "Only dependency/bootstrap files changed.", "evaluator": {"type": "changed_files_subset", "paths": ["package.json", "package-lock.json", "src/i18n/index.ts"]}},
            ], "context_refs": [*common_refs, {"source_type": "files", "workspace_id": parent_workspace_id, "paths": ["package.json", "package-lock.json", "src/i18n/index.ts"]}],
            "executor_needs": {"capabilities": ["coding", "file_read", "file_write", "multi_file_edit", "dependency_management", "command_execution"]},
        })
        context = await task_service.create(session, parent.project_id, {
            "task_type": "implementation", "title": "Restore localization context architecture",
            "description": "Restore src/context/LanguageContext.tsx with the project's LanguageProvider and useTranslation implementation and the required useLanguage hook. Do not modify other files.",
            "dependency_ids": [package.id],
            "acceptance": [
                {"criterion_id": "repair:context", "description": "LanguageContext provides LanguageProvider, useTranslation, and useLanguage.", "evaluator": {"type": "path_exists_contains", "path": "src/context/LanguageContext.tsx", "contains": ["LanguageProvider", "useTranslation", "useLanguage", "toggleLanguage"]}},
                {"criterion_id": "repair:context-scope", "description": "Only LanguageContext changed.", "evaluator": {"type": "changed_files_subset", "paths": ["src/context/LanguageContext.tsx"]}},
            ], "context_refs": [*common_refs, {"source_type": "file", "path": "src/context/LanguageContext.tsx"}],
            "executor_needs": {"capabilities": ["coding", "file_read", "file_write", "debugging"]},
        })
        integration = await task_service.create(session, parent.project_id, {
            "task_type": "implementation", "title": "Restore localization application integration",
            "description": "Restore direct App rendering in main.tsx, remove the rejected LanguageSwitcher insertion from App.tsx, remove only failed-attempt locale additions, and make LanguageSwitcher use useLanguage and toggleLanguage without react-i18next or t.",
            "dependency_ids": [context.id],
            "acceptance": [
                {"criterion_id": "repair:main", "description": "main.tsx directly renders App without i18next bootstrap.", "evaluator": {"type": "file_contains_excludes", "path": "src/main.tsx", "contains": ["<App />"], "excludes": ["I18nextProvider", "./i18n"]}},
                {"criterion_id": "repair:switcher", "description": "LanguageSwitcher uses project context without react-i18next or t.", "evaluator": {"type": "file_contains_excludes", "path": "src/components/LanguageSwitcher.tsx", "contains": ["../context/LanguageContext", "useLanguage", "toggleLanguage"], "excludes": ["react-i18next", "useTranslation", "{ t", ", t"]}},
                {"criterion_id": "repair:integration-scope", "description": "Only integration and locale files changed.", "evaluator": {"type": "changed_files_subset", "paths": ["src/main.tsx", "src/App.tsx", "src/components/LanguageSwitcher.tsx", "src/locales/en.json", "src/locales/ar.json"]}},
            ], "context_refs": [*common_refs, {"source_type": "files", "paths": ["src/main.tsx", "src/App.tsx", "src/components/LanguageSwitcher.tsx", "src/locales/en.json", "src/locales/ar.json"]}],
            "executor_needs": {"capabilities": ["coding", "file_read", "file_write", "multi_file_edit", "project_refactor"]},
        })
        verify = await task_service.create(session, parent.project_id, {
            "task_type": "verification", "title": "Verify localization repair architecture",
            "description": "Programmatically verify dependency, lockfile, bootstrap, context, main integration, and LanguageSwitcher criteria. Do not modify files.",
            "dependency_ids": [integration.id],
            "acceptance": [self._architecture_criterion()],
            "context_refs": common_refs, "executor_needs": {"capabilities": ["file_read", "quality_gate"]},
        })
        build = await task_service.create(session, parent.project_id, {
            "task_type": "command", "title": "Build verified localization repair", "description": "npm run build",
            "dependency_ids": [verify.id],
            "acceptance": [{"criterion_id": "repair:build", "description": "Production build passes.", "evaluator": {"type": "gate_passed", "kind": "build"}}],
            "context_refs": common_refs, "executor_needs": {"capabilities": ["command_execution"]},
        })
        return self._result(finding.id, parent.id, [package, context, integration, verify, build])

    def _architecture_criterion(self) -> dict:
        return {"criterion_id": "repair:architecture", "description": "All parent repair architecture criteria pass.", "evaluator": {"type": "all_of", "checks": [
                {"type": "json_root_dependencies_absent", "path": "package.json", "names": ["i18next", "react-i18next"]},
                {"type": "json_root_dependencies_absent", "path": "package-lock.json", "names": ["i18next", "react-i18next"]},
                {"type": "path_absent", "path": "src/i18n/index.ts"},
                {"type": "path_exists_contains", "path": "src/context/LanguageContext.tsx", "contains": ["LanguageProvider", "useTranslation", "useLanguage", "toggleLanguage"]},
                {"type": "file_contains_excludes", "path": "src/main.tsx", "contains": ["<App />"], "excludes": ["I18nextProvider", "./i18n"]},
                {"type": "file_contains_excludes", "path": "src/components/LanguageSwitcher.tsx", "contains": ["../context/LanguageContext", "useLanguage", "toggleLanguage"], "excludes": ["react-i18next", "useTranslation", "{ t", ", t"]},
            ]}}

    def _result(self, finding_id: str, parent_id: str, children: list[OrchestrationTaskRecord]) -> dict:
        return {"finding_id": finding_id, "parent_task_id": parent_id, "child_tasks": [item.to_dict() for item in children], "graph_version": "quality_repair_v1"}


quality_repair_decomposition_service = QualityRepairDecompositionService()
