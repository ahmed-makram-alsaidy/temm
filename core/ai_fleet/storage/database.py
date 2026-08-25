"""Async Database Manager and Initial Seed Data for AI Fleet OS."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select, func, text

from .migrations import MIGRATIONS, MigrationRunner
from .models import (
    Base,
    ProviderInstanceRecord,
    ModelRecord,
    ModelPriceRecord,
    ModelCapabilityEvidenceRecord,
    AgentRecord,
    TaskRun,
    RunAttemptRecord,
    RunArtifactRecord,
    RunOutputChunkRecord,
    BenchmarkRecord,
    BenchmarkScore,
    ArenaVoteRecord,
    DelegateSkillRecord,
    WorkflowRecord,
    SubscriptionRecord,
    SystemSetting,
    WorkspaceRecord,
    CommandRunRecord,
    ApprovalRecord,
    EventJournalRecord,
    AuditRecord,
    UsageObservationRecord,
    LatencyObservationRecord,
    QuotaObservationRecord,
    BudgetRecord,
    ModelFavoriteRecord,
    BenchmarkSuiteVersionRecord,
    BenchmarkCaseRecord,
    JudgeExecutionRecord,
    JudgeConsensusRecord,
    ArenaSessionRecord,
    ProjectRecord,
    ProjectWorkspaceLinkRecord,
    ProjectBrainFactRecord,
    ProjectBrainFactRevisionRecord,
    ProjectDecisionRecord,
    ProjectDecisionRevisionRecord,
    ProjectRequirementRecord,
    ProjectRequirementRevisionRecord,
    ProjectRequirementEdgeRecord,
    BlueprintProposalRecord,
    BlueprintProposalRevisionRecord,
    ProjectNeedRecord,
    ProjectLearningConsentRecord,
    ProjectOutcomeRecord,
    ContextPackRecord,
    ResearchQueryRecord,
    AssetRecord,
    ResearchSourceRecord,
    ResearchClaimRecord,
    ResearchCitationRecord,
    AssetUsageRecord,
    AssetLicenseRecord,
    AssetTransformJobRecord,
    AssetCollectionRecord,
    AssetCollectionMemberRecord,
    AssetCollectionProjectLinkRecord,
    OrchestrationTaskRecord,
    AcceptanceCriterionRecord,
    QualityWaiverRecord,
    OrchestrationCheckpointRecord,
    DeliverableRecord,
)

DB_PATH = Path(os.environ.get("AI_FLEET_DATA_DIR", str(Path.home() / ".ai_fleet"))) / "ai_fleet.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def assert_safe_database_path(path: Path = DB_PATH) -> None:
    """Refuse test initialization against the shared operator database."""
    if os.environ.get("AI_FLEET_TEST_DATABASE") == "1":
        production = (Path.home() / ".ai_fleet" / "ai_fleet.db").resolve()
        if path.resolve() == production:
            raise RuntimeError("Test database isolation violation: production TEMM database is selected.")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# --- Initial Seed Data ---

DEFAULT_MODELS = [
    {
        "id": "gpt-4o",
        "name": "GPT-4o (Omni)",
        "provider": "openai",
        "category": "general",
        "modalities": json.dumps(["text", "vision"]),
        "input_cost_per_m": 2.50,
        "output_cost_per_m": 10.00,
        "cache_cost_per_m": 1.25,
        "reasoning_cost_per_m": 0.0,
        "context_window": 128000,
        "is_local": False,
        "is_free": False,
        "is_active": True,
        "is_reference_baseline": True,  # Reference model for savings calculation
        "quality_score": 96.2,
        "coding_score": 94.8,
        "reasoning_score": 95.1,
        "arabic_score": 92.4,
        "vision_score": 96.0,
        "speed_score": 82.0,
        "reliability_score": 99.1,
        "tokens_per_sec": 75.0,
        "best_for": json.dumps(["Multimodal Tasks", "Complex Reasoning", "Baseline Reference"]),
        "not_ideal_for": json.dumps(["Ultra-low cost high-volume"]),
        "description": "Flagship multimodal intelligence from OpenAI.",
    },
    {
        "id": "claude-3-7-sonnet",
        "name": "Claude 3.7 Sonnet",
        "provider": "anthropic",
        "category": "coding",
        "modalities": json.dumps(["text", "vision"]),
        "input_cost_per_m": 3.00,
        "output_cost_per_m": 15.00,
        "cache_cost_per_m": 0.30,
        "reasoning_cost_per_m": 15.00,
        "context_window": 200000,
        "is_local": False,
        "is_free": False,
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 98.4,
        "coding_score": 99.1,
        "reasoning_score": 98.6,
        "arabic_score": 91.5,
        "vision_score": 95.2,
        "speed_score": 78.0,
        "reliability_score": 98.8,
        "tokens_per_sec": 65.0,
        "best_for": json.dumps(["Software Architecture", "Complex Coding", "Deep Reasoning"]),
        "not_ideal_for": json.dumps(["Sub-second Realtime"]),
        "description": "Anthropic's hybrid reasoning model for elite coding and analysis.",
    },
    {
        "id": "gemini-2-5-flash",
        "name": "Gemini 2.5 Flash",
        "provider": "google",
        "category": "fast",
        "modalities": json.dumps(["text", "vision", "audio"]),
        "input_cost_per_m": 0.075,
        "output_cost_per_m": 0.30,
        "cache_cost_per_m": 0.02,
        "reasoning_cost_per_m": 0.0,
        "context_window": 1000000,
        "is_local": False,
        "is_free": True,  # generous free tier
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 92.5,
        "coding_score": 91.2,
        "reasoning_score": 90.4,
        "arabic_score": 93.8,
        "vision_score": 94.0,
        "speed_score": 97.5,
        "reliability_score": 98.5,
        "tokens_per_sec": 145.0,
        "best_for": json.dumps(["High Throughput", "Massive 1M Context", "Ultra Cheap & Free Tier", "Arabic NLP"]),
        "not_ideal_for": json.dumps(["Extremely Niche Formal Math Proofs"]),
        "description": "Google's lightning fast, multimodal workhorse with 1M context.",
    },
    {
        "id": "gemini-2-5-pro",
        "name": "Gemini 2.5 Pro",
        "provider": "google",
        "category": "reasoning",
        "modalities": json.dumps(["text", "vision", "audio"]),
        "input_cost_per_m": 1.25,
        "output_cost_per_m": 5.00,
        "cache_cost_per_m": 0.31,
        "reasoning_cost_per_m": 5.00,
        "context_window": 2000000,
        "is_local": False,
        "is_free": False,
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 97.1,
        "coding_score": 96.5,
        "reasoning_score": 97.4,
        "arabic_score": 96.0,
        "vision_score": 97.5,
        "speed_score": 75.0,
        "reliability_score": 98.0,
        "tokens_per_sec": 60.0,
        "best_for": json.dumps(["2M Context Analysis", "Multimodal Video/Audio", "Arabic Native Reasoning"]),
        "not_ideal_for": json.dumps(["Sub-second responses"]),
        "description": "State of the art reasoning with 2M token context window.",
    },
    {
        "id": "deepseek-v3",
        "name": "DeepSeek V3",
        "provider": "deepseek",
        "category": "general",
        "modalities": json.dumps(["text"]),
        "input_cost_per_m": 0.14,
        "output_cost_per_m": 0.28,
        "cache_cost_per_m": 0.014,
        "reasoning_cost_per_m": 0.0,
        "context_window": 64000,
        "is_local": False,
        "is_free": False,
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 95.0,
        "coding_score": 94.2,
        "reasoning_score": 93.8,
        "arabic_score": 88.0,
        "vision_score": 60.0,
        "speed_score": 91.0,
        "reliability_score": 96.5,
        "tokens_per_sec": 85.0,
        "best_for": json.dumps(["Unbeatable Price/Performance", "Coding & Logic", "High Volume API"]),
        "not_ideal_for": json.dumps(["Vision Tasks"]),
        "description": "Unprecedented cost-efficiency at frontier performance.",
    },
    {
        "id": "deepseek-r1",
        "name": "DeepSeek R1 (Reasoning)",
        "provider": "deepseek",
        "category": "reasoning",
        "modalities": json.dumps(["text"]),
        "input_cost_per_m": 0.55,
        "output_cost_per_m": 2.19,
        "cache_cost_per_m": 0.14,
        "reasoning_cost_per_m": 2.19,
        "context_window": 64000,
        "is_local": False,
        "is_free": False,
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 97.8,
        "coding_score": 97.2,
        "reasoning_score": 98.9,
        "arabic_score": 89.2,
        "vision_score": 60.0,
        "speed_score": 68.0,
        "reliability_score": 97.0,
        "tokens_per_sec": 42.0,
        "best_for": json.dumps(["Deep Mathematical Reasoning", "Algorithmic Coding", "Complex Logic"]),
        "not_ideal_for": json.dumps(["Low latency fast chat", "Vision"]),
        "description": "Open-weights reasoning champion with chain-of-thought.",
    },
    {
        "id": "qwen-2-5-coder-32b",
        "name": "Qwen 2.5 Coder 32B",
        "provider": "alibaba",
        "category": "coding",
        "modalities": json.dumps(["text"]),
        "input_cost_per_m": 0.20,
        "output_cost_per_m": 0.60,
        "cache_cost_per_m": 0.05,
        "reasoning_cost_per_m": 0.0,
        "context_window": 128000,
        "is_local": False,
        "is_free": False,
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 94.6,
        "coding_score": 96.8,
        "reasoning_score": 92.1,
        "arabic_score": 93.4,
        "vision_score": 65.0,
        "speed_score": 88.0,
        "reliability_score": 97.8,
        "tokens_per_sec": 80.0,
        "best_for": json.dumps(["Code Generation", "Refactoring", "Repository Analysis", "Multilingual"]),
        "not_ideal_for": json.dumps(["Vision Tasks"]),
        "description": "Alibaba's dedicated code intelligence powerhouse.",
    },
    {
        "id": "ollama-llama-3-3-70b",
        "name": "Llama 3.3 70B (Local Ollama)",
        "provider": "ollama",
        "category": "general",
        "modalities": json.dumps(["text"]),
        "input_cost_per_m": 0.00,
        "output_cost_per_m": 0.00,
        "cache_cost_per_m": 0.00,
        "reasoning_cost_per_m": 0.0,
        "context_window": 128000,
        "is_local": True,
        "is_free": True,
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 91.2,
        "coding_score": 89.5,
        "reasoning_score": 90.8,
        "arabic_score": 86.4,
        "vision_score": 60.0,
        "speed_score": 72.0,
        "reliability_score": 99.0,
        "tokens_per_sec": 38.0,
        "best_for": json.dumps(["100% Privacy & Offline", "Zero API Cost", "Local Automation"]),
        "not_ideal_for": json.dumps(["Low VRAM systems"]),
        "description": "Local offline execution with complete data sovereignty.",
    },
    {
        "id": "groq-llama-3-3-70b",
        "name": "Llama 3.3 70B (Groq LPU)",
        "provider": "groq",
        "category": "fast",
        "modalities": json.dumps(["text"]),
        "input_cost_per_m": 0.59,
        "output_cost_per_m": 0.79,
        "cache_cost_per_m": 0.0,
        "reasoning_cost_per_m": 0.0,
        "context_window": 128000,
        "is_local": False,
        "is_free": True,  # generous free tier
        "is_active": True,
        "is_reference_baseline": False,
        "quality_score": 91.8,
        "coding_score": 90.0,
        "reasoning_score": 91.2,
        "arabic_score": 87.0,
        "vision_score": 60.0,
        "speed_score": 99.8,
        "reliability_score": 98.2,
        "tokens_per_sec": 280.0,
        "best_for": json.dumps(["Instant Ultra-Low Latency", "Interactive CLI", "Real-Time Agents"]),
        "not_ideal_for": json.dumps(["Vision Tasks"]),
        "description": "Groq LPU hardware delivering screaming 280+ tokens/sec.",
    },
]

DEFAULT_AGENTS = [
    {
        "id": "qwen-code",
        "name": "Qwen Code CLI",
        "cli_command": "qwen-code",
        "version_command": "qwen-code --version",
        "prompt_arg_format": "--prompt \"{prompt}\"",
        "workspace_arg_format": "--workspace \"{workspace}\"",
        "capabilities": json.dumps(["coding", "shell", "read_files", "write_files"]),
        "permission_profile": "developer",
        "is_installed": False,
        "status": "ready",
        "description": "Alibaba Qwen CLI agent optimized for autonomous code generation and refactoring.",
    },
    {
        "id": "claude-code",
        "name": "Claude Code",
        "cli_command": "claude",
        "version_command": "claude --version",
        "prompt_arg_format": "-p \"{prompt}\"",
        "workspace_arg_format": "--project \"{workspace}\"",
        "capabilities": json.dumps(["coding", "shell", "read_files", "write_files", "git"]),
        "permission_profile": "developer",
        "is_installed": False,
        "status": "ready",
        "description": "Anthropic's official terminal coding agent for deep repo tasks.",
    },
    {
        "id": "codex-cli",
        "name": "OpenAI Codex / GPT CLI",
        "cli_command": "codex",
        "version_command": "codex --version",
        "prompt_arg_format": "\"{prompt}\"",
        "workspace_arg_format": "-C \"{workspace}\"",
        "capabilities": json.dumps(["coding", "shell", "read_files", "write_files"]),
        "permission_profile": "developer",
        "is_installed": False,
        "status": "ready",
        "description": "OpenAI terminal agent for multi-file code editing and terminal executions.",
    },
    {
        "id": "aider-agent",
        "name": "Aider AI Pair Programmer",
        "cli_command": "aider",
        "version_command": "aider --version",
        "prompt_arg_format": "--message \"{prompt}\" --yes",
        "workspace_arg_format": "--cwd \"{workspace}\"",
        "capabilities": json.dumps(["coding", "git", "read_files", "write_files"]),
        "permission_profile": "developer",
        "is_installed": False,
        "status": "ready",
        "description": "Open source AI pair programmer in terminal with Git auto-commit support.",
    },
    {
        "id": "ollama-runner",
        "name": "Ollama Local Agent",
        "cli_command": "ollama",
        "version_command": "ollama --version",
        "prompt_arg_format": "run llama3.3 \"{prompt}\"",
        "workspace_arg_format": "",
        "capabilities": json.dumps(["general", "offline"]),
        "permission_profile": "safe",
        "is_installed": False,
        "status": "ready",
        "description": "Local offline runtime manager for private local LLMs.",
    },
    {
        "id": "gemini-cli",
        "name": "Gemini CLI Tool",
        "cli_command": "gemini",
        "version_command": "gemini --version",
        "prompt_arg_format": "\"{prompt}\"",
        "workspace_arg_format": "",
        "capabilities": json.dumps(["general", "multimodal", "fast"]),
        "permission_profile": "safe",
        "is_installed": False,
        "status": "ready",
        "description": "Google Gemini terminal client for instant search and generation.",
    },
]

DEFAULT_SKILLS = [
    {
        "id": "skill-code-review",
        "name": "Full Code & Architecture Review",
        "description": "Performs deep multi-file code review checking for design patterns, race conditions, memory leaks, and clean code principles.",
        "category": "engineering",
        "adapter_type": "prompt",
        "prompt_template": "Perform an in-depth senior engineering code review for the following code/task. Analyze architecture, edge cases, potential bugs, and provide refactored code snippets:\n\n{task}",
        "required_capabilities": json.dumps(["coding", "reasoning"]),
    },
    {
        "id": "skill-security-audit",
        "name": "Cybersecurity & Vulnerability Audit",
        "description": "Scans code and configurations for OWASP Top 10, SQL injection, XSS, insecure token storage, and permission misconfigurations.",
        "category": "security",
        "adapter_type": "prompt",
        "prompt_template": "Audit the following codebase/task for security vulnerabilities (OWASP, injection risks, auth bypass, secret leaks, CSRF, insecure deps). Provide severity scores and remediation diffs:\n\n{task}",
        "required_capabilities": json.dumps(["coding", "reasoning"]),
    },
    {
        "id": "skill-sql-optimizer",
        "name": "SQL & Query Performance Tuning",
        "description": "Analyzes SQL queries, indexing strategies, join patterns, and suggests optimal execution plans and schema optimizations.",
        "category": "database",
        "adapter_type": "prompt",
        "prompt_template": "Analyze the following SQL queries / schema and provide optimal indexing strategies, query rewrites, and explain-plan improvements:\n\n{task}",
        "required_capabilities": json.dumps(["coding", "reasoning"]),
    },
    {
        "id": "skill-arabic-localization",
        "name": "Arabic Cultural & Technical Localization",
        "description": "Translates and localizes technical concepts, documentation, and copywriting into natural, idiomatic Arabic with accurate technical terminology.",
        "category": "localization",
        "adapter_type": "prompt",
        "prompt_template": "Translate and adapt the following technical content into fluent, modern, highly articulate Arabic, ensuring correct technical terminology and natural phrasing:\n\n{task}",
        "required_capabilities": json.dumps(["arabic", "general"]),
    },
    {
        "id": "skill-bug-hunter",
        "name": "Bug Hunter & Root Cause Fixer",
        "description": "Pinpoints the root cause of elusive runtime bugs, stack traces, and proposes comprehensive drop-in fixes with test cases.",
        "category": "engineering",
        "adapter_type": "prompt",
        "prompt_template": "Investigate the root cause of this bug or stack trace, explain why it happens, and provide the exact patch and unit tests to verify the fix:\n\n{task}",
        "required_capabilities": json.dumps(["coding", "reasoning"]),
    },
]

DEFAULT_WORKFLOWS = [
    {
        "id": "workflow-full-review",
        "name": "Full Multi-Agent Code Review & Security Audit",
        "description": "Multi-agent pipeline: Planner breaks down changes -> Parallel Coding & Security Reviewers analyze -> Judge Model synthesizes final report.",
        "template_type": "code_review",
        "nodes": json.dumps([
            {"id": "node_planner", "type": "planner", "title": "Task Planner", "model": "gemini-2-5-flash"},
            {"id": "node_code_worker", "type": "worker", "title": "Code Quality Reviewer", "model": "qwen-2-5-coder-32b"},
            {"id": "node_sec_worker", "type": "worker", "title": "Security Auditor", "model": "deepseek-r1"},
            {"id": "node_judge", "type": "judge", "title": "Consensus Judge", "model": "claude-3-7-sonnet"},
        ]),
        "edges": json.dumps([
            {"from": "node_planner", "to": "node_code_worker"},
            {"from": "node_planner", "to": "node_sec_worker"},
            {"from": "node_code_worker", "to": "node_judge"},
            {"from": "node_sec_worker", "to": "node_judge"},
        ]),
    },
    {
        "id": "workflow-deep-research",
        "name": "Autonomous Deep Research & Synthesis",
        "description": "Fast multi-angle research worker pool aggregated with structured executive summary.",
        "template_type": "research",
        "nodes": json.dumps([
            {"id": "node_planner", "type": "planner", "title": "Research Decomposer", "model": "gemini-2-5-flash"},
            {"id": "node_worker_1", "type": "worker", "title": "Technical Depth Analyst", "model": "deepseek-v3"},
            {"id": "node_worker_2", "type": "worker", "title": "Market & Ecosystem Analyst", "model": "groq-llama-3-3-70b"},
            {"id": "node_judge", "type": "judge", "title": "Executive Synthesizer", "model": "gpt-4o"},
        ]),
        "edges": json.dumps([
            {"from": "node_planner", "to": "node_worker_1"},
            {"from": "node_planner", "to": "node_worker_2"},
            {"from": "node_worker_1", "to": "node_judge"},
            {"from": "node_worker_2", "to": "node_judge"},
        ]),
    },
]

DEFAULT_BENCHMARKS = [
    {
        "id": "bench-coding",
        "name": "Full Stack & Algorithmic Coding",
        "category": "coding",
        "description": "Tests code correctness, type safety, algorithmic efficiency, and edge case handling across Python, TypeScript, and Go.",
        "difficulty": "hard",
        "test_cases_count": 50,
        "test_dataset": json.dumps([
            {"id": "q1", "category": "coding", "prompt": "Implement a lock-free thread-safe bounded queue in Python using asyncio and compare with ring buffer.", "weight": 1.2},
            {"id": "q2", "category": "coding", "prompt": "Write a TypeScript parser for JSONPath with wildcard and filter expression support.", "weight": 1.5},
            {"id": "q3", "category": "coding", "prompt": "Design a distributed rate limiter with sliding window log using Redis Lua scripts.", "weight": 1.4},
        ]),
    },
    {
        "id": "bench-reasoning",
        "name": "Multi-Step Logic & Mathematics",
        "category": "reasoning",
        "description": "Evaluates deductive reasoning, formal logic proofs, puzzle solving, and complex causal chains.",
        "difficulty": "expert",
        "test_cases_count": 40,
        "test_dataset": json.dumps([
            {"id": "r1", "category": "reasoning", "prompt": "Solve the Monty Hall problem extended to 100 doors where 98 doors are opened. Formulate exact Bayes theorem proof.", "weight": 1.0},
            {"id": "r2", "category": "reasoning", "prompt": "Prove whether any connected planar graph with minimum degree 5 has at least 12 vertices of degree 5.", "weight": 1.5},
        ]),
    },
    {
        "id": "bench-arabic",
        "name": "Arabic Linguistic & Technical Fluency",
        "category": "arabic",
        "description": "Tests Modern Standard Arabic fluency, technical vocabulary accuracy, cultural nuances, and grammar.",
        "difficulty": "medium",
        "test_cases_count": 30,
        "test_dataset": json.dumps([
            {"id": "a1", "category": "arabic", "prompt": "اشرح مفهوم الـ Distributed Consensus (مثل Raft و Paxos) باللغة العربية الفصحى الدقيقة مع صياغة مصطلحات تقنية معتمدة.", "weight": 1.0},
        ]),
    },
    {
        "id": "bench-speed",
        "name": "Throughput & First-Token Latency",
        "category": "speed",
        "description": "Measures Time-To-First-Token (TTFT) and sustainable output generation tokens per second.",
        "difficulty": "easy",
        "test_cases_count": 20,
        "test_dataset": json.dumps([
            {"id": "s1", "category": "speed", "prompt": "Generate a concise 200-word summary of quantum computing milestones.", "weight": 1.0},
        ]),
    },
]

DEFAULT_SYSTEM_SETTINGS = [
    {"key": "reference_baseline_model", "value": "gpt-4o", "description": "Baseline model for calculated avoided cost and savings"},
    {"key": "monthly_ai_budget", "value": "100.0", "description": "Monthly spend ceiling in USD"},
    {"key": "budget_alert_threshold", "value": "80.0", "description": "Percentage at which to trigger budget warning"},
    {"key": "default_routing_strategy", "value": "balanced", "description": "Default router mode (balanced, economy, quality, fast)"},
    {"key": "hourly_productivity_value", "value": "25.0", "description": "User estimated hourly rate for ROI calculations ($/hr)"},
    {"key": "economy_auto_switch", "value": "true", "description": "Automatically fallback to Economy mode when budget > 90%"},
]

async def init_db():
    """Migrate, create tables, record schema versions, and seed initial registries."""
    assert_safe_database_path()
    await engine.dispose()
    await asyncio.to_thread(MigrationRunner(DB_PATH).migrate)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for migration in MIGRATIONS:
            await conn.execute(
                text("INSERT OR IGNORE INTO schema_migrations(version, name, checksum, applied_at) VALUES (:version, :name, :checksum, :applied_at)"),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "checksum": migration.checksum,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
            )

    async with AsyncSessionLocal() as session:
        # 1. Seed Models
        existing_models = await session.execute(select(func.count(ModelRecord.id)))
        if existing_models.scalar() == 0:
            for model_data in DEFAULT_MODELS:
                truthful = dict(model_data)
                for field in ["quality_score", "coding_score", "reasoning_score", "arabic_score", "vision_score", "speed_score", "reliability_score", "tokens_per_sec", "input_cost_per_m", "output_cost_per_m", "cache_cost_per_m", "reasoning_cost_per_m"]:
                    truthful[field] = None
                truthful["best_for"] = "[]"
                truthful["not_ideal_for"] = "[]"
                truthful["is_free"] = False
                session.add(ModelRecord(**truthful))

        # 2. Seed Agents
        existing_agents = await session.execute(select(func.count(AgentRecord.id)))
        if existing_agents.scalar() == 0:
            for a in DEFAULT_AGENTS:
                session.add(AgentRecord(**a))

        # 3. Seed Skills
        existing_skills = await session.execute(select(func.count(DelegateSkillRecord.id)))
        if existing_skills.scalar() == 0:
            for s in DEFAULT_SKILLS:
                session.add(DelegateSkillRecord(**s))

        # 4. Seed Workflows
        existing_workflows = await session.execute(select(func.count(WorkflowRecord.id)))
        if existing_workflows.scalar() == 0:
            for w in DEFAULT_WORKFLOWS:
                session.add(WorkflowRecord(**w))

        # 5. Seed Benchmarks
        existing_benchmarks = await session.execute(select(func.count(BenchmarkRecord.id)))
        if existing_benchmarks.scalar() == 0:
            for b in DEFAULT_BENCHMARKS:
                session.add(BenchmarkRecord(**b))

        # 6. Subscriptions and usage are user-owned facts; never seed demo values.

        # 7. Seed System Settings
        existing_settings = await session.execute(select(func.count(SystemSetting.key)))
        if existing_settings.scalar() == 0:
            for st in DEFAULT_SYSTEM_SETTINGS:
                session.add(SystemSetting(**st))

        # 8. Runs are evidence of real execution; never seed sample receipts.

        await session.commit()
