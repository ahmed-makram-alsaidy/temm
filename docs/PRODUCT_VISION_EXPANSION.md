# AI Fleet OS Product Vision Expansion

## Authority

Owner-approved canonical expansion dated 2026-08-16. This document extends `AI_FLEET_SOL_MASTER_SPEC.md`; it does not delete, weaken, renumber, summarize away, or replace requirements 1–143. Where delivery sequencing conflicts, stable foundations remain prerequisites.

## Product outcome

The product is a professional, open-source AI production operating system. It must progress beyond model management, routing, launching, dashboards, and isolated agents. A user should eventually provide an outcome such as “Build a complete website for this company” or “Research, design, and implement this business system,” and receive a genuinely working deliverable with the required intelligence, research, assets, implementation, evidence, and quality controls.

The target flow is:

`User Goal → Project Understanding → Project Blueprint → Requirement Graph → Missing-Needs Detection → Research / Asset Acquisition → Execution Plan → Task Graph → Routing / Agent Assignment → Implementation → Quality Gates → Completeness Audit → Working Deliverable`

The Router remains an infrastructure decision service. A higher-level Project Orchestrator owns outcome understanding and production coordination.

## Project-centered product model

Projects and outcomes become the primary mental model. Models, Agents, Providers, Runtimes, and Skills remain distinct infrastructure.

A project workspace should progressively provide:

- Overview
- Plan
- Tasks
- Assets
- Research
- Decisions
- Runs
- Agents
- Quality
- Costs
- History

## Project Brain

Project Brain is persistent structured project truth, independent of chat history and model choice. It records:

- identity, purpose, target users, and stakeholders
- business, technical, brand, quality, and production requirements
- architecture, design system, typography, and constraints
- assets, dependencies, integrations, and environments
- decisions, reasons, impacts, supersession, and approval state
- completed work, pending work, blockers, known problems, and evidence
- delivery state, readiness state, and unresolved risks

Project state must survive sessions, process restarts, and model changes. Chat remains conversation history, not the source of project truth. Changes require versioning and auditable history.

## Blueprint Engine

Before substantial implementation, the system should generate an extensible structured blueprint appropriate to project type. Templates supply capabilities and sections; no universal hardcoded blueprint is acceptable.

Website blueprints may include brand, sitemap, content, typography, imagery, illustrations, icons, responsive behavior, frontend, backend, database, forms, SEO, performance, accessibility, deployment, and QA.

Business-system blueprints may include roles, permissions, workflows, frontend, backend, database, authentication, notifications, integrations, documents, reporting, backup, security, and QA.

Blueprint output must distinguish known facts, assumptions, questions, proposed requirements, and owner-approved requirements.

## Decisions and memory

Decisions are first-class records with statement, rationale, impact, rule, status, author, timestamps, evidence, and supersession. Relevant decisions must enter task context packs. Settled choices may not be silently replaced.

## Requirements and dependency graph

Requirements are first-class, versioned, traceable entities. They support hierarchy, dependencies, blockers, acceptance criteria, evidence, status, source, priority, and affected deliverables.

Dependent work cannot be classified production-ready while required dependencies are unresolved. Graph validation must prevent invalid cycles and expose impact when a requirement changes.

## Asset intelligence

Assets are first-class entities rather than generic images. Supported architecture includes:

- raster images: PNG, JPG, JPEG, WEBP, AVIF, GIF
- vector: SVG, AI, EPS
- design: PSD, PDF
- fonts: TTF, OTF, WOFF, WOFF2
- audio: WAV, MP3, OGG
- video: MP4, WEBM
- motion: Lottie / JSON
- 3D: GLB, GLTF
- documents, datasets, CSV, Excel, templates, code artifacts, and other project files

### Asset manifest

Each asset may record identity, project/library scope, path, type, MIME type, hash, source, provenance, license, dimensions, size, variants, usage, dependencies, origin state, transformation history, and validation timestamps.

The system should detect missing files, broken paths, duplicates, unused assets where practical, placeholders, incompatible formats, and oversized assets.

### Asset dependency graph

Asset usage links components and deliverables to assets. Changes or disappearance must expose affected components.

### Acquisition policy

Missing assets should resolve in this order where appropriate:

1. current project assets
2. reusable user asset library
3. connected sources
4. licensed/free external sources
5. generation
6. user approval where required

No arbitrary blind download is allowed. Paid acquisition always requires explicit user approval.

### Licensing and provenance

Unknown-license material may never be represented as commercially safe. Source, license, retrieval, ownership, restrictions, and confidence are recorded where available. Unknown and incompatible licenses are visible blockers where project policy requires safe commercial use.

### Transformations

The architecture supports controlled resize, crop, optimization, compression, conversion, responsive variants, thumbnails, SVG optimization, audio conversion, waveform generation, and legally appropriate font processing. Derivatives retain links to originals, parameters, tools, hashes, and provenance.

### Global asset library

Reusable local user-owned brands, logos, fonts, icons, illustrations, audio, photos, and templates should not be reacquired unnecessarily.

## Research and source intelligence

Research is a structured subsystem with extensible connectors for web search, official and technical documentation, factual research, image/icon/illustration/font/audio/video discovery, packages, libraries, datasets, and other searchable resources.

Fresh or externally verifiable information must not be invented from model memory. Research records source, retrieval time, source type, freshness, confidence, supported claims, project usage, and citations. Official and authoritative sources are preferred where appropriate.

Network access, download policy, content type, size, hashes, redirects, licenses, and unsafe file handling require explicit controls.

## Project Orchestrator

The Project Orchestrator answers “What complete process is required to achieve this outcome?” It progressively owns:

- project analysis and clarification
- blueprint creation and requirement decomposition
- dependency and missing-needs detection
- research and asset planning
- task graph creation and agent assignment
- model routing and task-specific context preparation
- execution monitoring, fallback, escalation, and recovery
- human approval boundaries
- quality-gate coordination and completion assessment

It consumes capability-based contracts and must not hardcode brands.

## Context packs

Task-specific context packs minimize irrelevant context and token waste. A pack may include the task, relevant requirements, files, decisions, assets, architecture constraints, coding/design rules, acceptance criteria, and prior execution evidence. Packs require provenance, size/token accounting, freshness, redaction, and deterministic reconstruction where practical.

## Definition of Done

“Agent said done” is never sufficient. Tasks support explicit acceptance criteria and evidence. Criteria are project-type appropriate and may include responsive behavior, real assets/fonts, no placeholders, functional interactions, accessibility, performance, visual QA, tests, builds, security, and owner approval.

Completion states distinguish implementation complete, verification complete, blocked, failed, waived, and production-ready. Waivers are explicit, reasoned, and auditable.

## Quality gates

A configurable quality-gate architecture supports engineering, design, asset, content, security, accessibility, performance, SEO, responsive, and business-requirement gates. Not every project uses every gate. Gates expose inputs, checks, evidence, severity, outcomes, retries, waivers, and affected requirements.

## Completeness audit

Before delivery readiness, the system should check applicable unfinished TODOs, placeholders, missing assets/fonts, broken imports/links, default favicons, metadata, responsive behavior, tests, builds, accessibility, performance, incomplete requirements, and blockers. Readiness is evidence-based and cannot be fabricated.

## Working deliverables

Suitable project delivery may include source code, assets, fonts, images, audio, configuration, database, migrations, tests, documentation, production build, checksums, and a readiness report. Delivery packaging must never imply deployment success without evidence.

## Value measurement

Value expands beyond token savings while preserving truth labels:

- actual API spend
- reference API cost
- estimated avoided cost
- tasks automated
- repeated work avoided
- missing dependencies discovered
- QA defects caught
- rework prevented
- estimated manual time avoided

Every value records whether it is measured, provider-reported, estimated, or unknown, plus formula/source where applicable.

## Product identity workstream

“AI Fleet OS” is a codename, not immutable public branding. Repository identifiers must not be prematurely renamed. A later evidence-driven identity workstream covers positioning, naming research, symbol direction, typography, color, iconography, motion, product language, GitHub, documentation, and website identity.

Desired personality: calm, intelligent, technical, precise, confident, and professional. Avoid robot heads, brains, sparkles, generic neon gradients, glowing AI orbs, and excessive glassmorphism.

## Open-source extension surface

External developers should eventually extend Agents, Models, Providers, Runtimes, CLI adapters, Skills, Benchmarks, Judges, Workflows, Research connectors, Asset sources, Project templates, and Quality gates without invasive Core changes.

The governing rule remains: **The Core understands capabilities, not brands.**

## Safety and truth constraints

- Never fabricate models, availability, quality, benchmarks, prices, quotas, savings, subscriptions, capabilities, task success, tests, licenses, provenance, or completion.
- Use UNKNOWN, UNVERIFIED, and NOT AVAILABLE where evidence is absent.
- Never purchase autonomously.
- Never expose secrets in logs, receipts, events, frontend payloads, exports, or errors.
- Continuously review injection, argv, path traversal, workspace boundaries, plugin permissions, unsafe files, downloads, network access, arbitrary execution, and user-controlled configuration.

## Delivery order

Expanded product systems do not leapfrog foundations. Immediate prerequisites remain Agent Registry lifecycle, Model Registry truthfulness, Provider/plugin contracts, versioned migrations, security/configuration/error foundations, and trustworthy run telemetry. Project Brain, assets, research, and orchestration begin with schemas/contracts only after these boundaries are stable enough to support them truthfully.
