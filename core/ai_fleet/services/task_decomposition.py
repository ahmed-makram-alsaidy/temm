"""Task decomposition service for TEMM orchestration.

Transforms project requirements into appropriately scoped executable tasks with:
- dependency ordering
- execution type classification (AI vs command)
- capability requirements
- timeout policies
- verification boundaries
"""

import json
import uuid
from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..storage.models import OrchestrationTaskRecord, ProjectRequirementRecord


class TaskDecompositionService:
    """Decomposes project requirements into an executable task graph."""

    def decompose_website_project(self, requirements: List[Dict[str, Any]], project_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Produce a task graph for a website project based on requirements and context."""
        tech_stack = project_context.get("tech_stack", [])
        languages = project_context.get("languages", ["en"])
        has_backend = any(t in tech_stack for t in ["express", "fastify", "node", "sqlite", "postgres"])
        has_react = "react" in tech_stack
        has_vite = "vite" in tech_stack

        tasks: List[Dict[str, Any]] = []
        task_ids: Dict[str, str] = {}

        def add_task(key: str, title: str, description: str, task_type: str, deps: List[str] = None, capabilities: List[str] = None, acceptance: List[str] = None) -> str:
            tid = f"task-{uuid.uuid4().hex[:12]}"
            task_ids[key] = tid
            tasks.append({
                "id": tid,
                "key": key,
                "title": title,
                "description": description,
                "task_type": task_type,
                "dependencies": [task_ids[d] for d in (deps or []) if d in task_ids],
                "capabilities": capabilities or ["coding"],
                "acceptance": [{"criterion_id": f"ac-{i}", "description": a} for i, a in enumerate(acceptance or [title])],
            })
            return tid

        # Phase 1: Scaffold
        if has_vite and has_react:
            add_task("scaffold", "Create Vite React TypeScript project",
                     "Run: npm create vite@latest . -- --template react-ts\nThis creates the base project structure.",
                     "command", acceptance=["package.json exists with react and vite"])

            add_task("install-base", "Install base dependencies",
                     "npm install",
                     "command", deps=["scaffold"], acceptance=["node_modules directory exists"])

            add_task("install-deps", "Install project dependencies",
                     "npm install react-router-dom lucide-react && npm install -D tailwindcss postcss autoprefixer @tailwindcss/vite",
                     "command", deps=["install-base"], acceptance=["react-router-dom in package.json dependencies"])

        # Phase 2: Configuration
        add_task("config", "Configure Tailwind, fonts, design tokens, and project structure",
                 self._config_prompt(project_context),
                 "implementation", deps=["install-deps"] if "install-deps" in task_ids else [],
                 acceptance=["tailwind.config exists with project colors", "index.css has Tailwind directives and font imports"])

        # Phase 3: Core application structure
        if len(languages) > 1:
            add_task("i18n", "Create bilingual content and language system",
                     self._i18n_prompt(project_context),
                     "implementation", deps=["config"],
                     acceptance=["i18n translations file exists with both Arabic and English content", "Language context/provider exists"])

        add_task("layout", "Create application layout, navigation, and routing",
                 self._layout_prompt(project_context),
                 "implementation", deps=["i18n"] if "i18n" in task_ids else ["config"],
                 acceptance=["App.tsx has router setup", "Navbar component exists with responsive mobile menu", "Footer component exists"])

        # Phase 4: Pages
        add_task("homepage", "Create homepage with hero section and overview",
                 self._page_prompt("homepage", project_context),
                 "implementation", deps=["layout"],
                 acceptance=["Hero component exists", "Homepage renders without errors"])

        add_task("services", "Create services page with service cards",
                 self._page_prompt("services", project_context),
                 "implementation", deps=["layout"],
                 acceptance=["Services component exists with service cards"])

        add_task("doctors", "Create doctors/team page",
                 self._page_prompt("doctors", project_context),
                 "implementation", deps=["layout"],
                 acceptance=["Doctors component exists with team cards"])

        add_task("about", "Create about/clinic page",
                 self._page_prompt("about", project_context),
                 "implementation", deps=["layout"],
                 acceptance=["About component exists"])

        add_task("contact", "Create contact page with clinic information",
                 self._page_prompt("contact", project_context),
                 "implementation", deps=["layout"],
                 acceptance=["Contact component exists with clinic details"])

        # Phase 5: Backend
        if has_backend:
            add_task("backend", "Create Express API server with SQLite database",
                     self._backend_prompt(project_context),
                     "implementation", deps=["config"],
                     capabilities=["coding", "shell"],
                     acceptance=["server/index.js exists", "server/database.js exists with schema", "API responds to health check"])

        # Phase 6: Booking (depends on backend + layout)
        booking_deps = ["layout"]
        if "backend" in task_ids:
            booking_deps.append("backend")
        add_task("booking", "Create appointment booking form with validation and API integration",
                 self._booking_prompt(project_context),
                 "implementation", deps=booking_deps,
                 acceptance=["BookingForm component exists", "Form has validation", "Submits to backend API"])

        # Phase 7: Build verification
        add_task("build", "Run TypeScript check and production build",
                 "npx tsc --noEmit && npm run build",
                 "command", deps=[t["key"] for t in tasks if t["task_type"] == "implementation"],
                 acceptance=["Build completes without errors"])

        return tasks

    def _config_prompt(self, ctx: Dict) -> str:
        design = ctx.get("design", {})
        primary = design.get("primary_color", "#0d9488")
        accent = design.get("accent_color", "#d4a853")
        fonts = design.get("fonts", ["Tajawal", "Inter"])
        return f"""Configure the project design system:
1. Update tailwind.config.js/ts with colors: primary teal ({primary}), gold accent ({accent}), font families: {fonts}
2. Update src/index.css with:
   - @tailwind base/components/utilities directives
   - Google Fonts import for {', '.join(fonts)}
   - RTL/LTR base styles
   - Utility classes: .btn-primary, .btn-gold, .section-title, .card
3. Clean up default Vite CSS (remove the template styles)"""

    def _i18n_prompt(self, ctx: Dict) -> str:
        return """Create a complete bilingual (Arabic/English) content system:
1. src/i18n.ts - Full translations object with Arabic and English for: navigation, hero, services (6 dental services with descriptions), doctors (3 specialists), about clinic, booking form labels/validation messages, contact details, footer
2. src/LanguageContext.tsx - React context with language state, toggle function, direction (rtl/ltr), and font family switching
Clinic name: عيادة الأمل لطب الأسنان / Al-Amal Dental Clinic
Use realistic Arabic dental content - no lorem ipsum."""

    def _layout_prompt(self, ctx: Dict) -> str:
        return """Create the application shell:
1. src/App.tsx - Main app with BrowserRouter, routes for /, /services, /doctors, /about, /booking, /contact. Wrap in LanguageProvider.
2. src/components/Navbar.tsx - Sticky responsive navigation with: logo/clinic name, nav links, language toggle (AR/EN), mobile hamburger menu with slide-out, Book Now CTA button
3. src/components/Footer.tsx - Footer with clinic name and copyright
4. src/main.tsx - Entry point rendering App
Use lucide-react icons. Support RTL/LTR via the language context."""

    def _page_prompt(self, page: str, ctx: Dict) -> str:
        prompts = {
            "homepage": """Create src/components/Hero.tsx:
Premium hero section with gradient background (teal to dark teal), clinic name, tagline in current language, CTA button linking to /booking, subtle decorative elements. Use the translation context for all text.""",
            "services": """Create src/components/Services.tsx:
Grid of 6 dental service cards with lucide-react icons, service name and description from translations. Clean card design with hover effects. Section title and subtitle.""",
            "doctors": """Create src/components/Doctors.tsx:
3 doctor cards with placeholder avatar (gradient circle with stethoscope icon), doctor name, specialty, experience years. All from translations.""",
            "about": """Create src/components/About.tsx:
About section with clinic description, establishment year, feature list with checkmarks. Split layout on desktop. Dark background variant for visual contrast.""",
            "contact": """Create src/components/Contact.tsx:
Contact information cards: address, phone, hours, email. Grid layout with icons. All from translations.""",
        }
        return prompts.get(page, f"Create the {page} page component")

    def _backend_prompt(self, ctx: Dict) -> str:
        return """Create the appointment backend:
1. Create directory: server/
2. server/database.js - Initialize SQLite with better-sqlite3. Create appointments table: id (INTEGER PRIMARY KEY AUTOINCREMENT), patient_name (TEXT NOT NULL), phone (TEXT NOT NULL), email (TEXT), preferred_date (TEXT NOT NULL), preferred_time (TEXT), service (TEXT NOT NULL), notes (TEXT), created_at (TEXT DEFAULT datetime('now'))
3. server/index.js - Express server on port 3001 with CORS. Routes:
   - POST /api/appointments (validate required fields, insert, return {id, message})
   - GET /api/appointments (return all appointments ordered by created_at DESC)
   - GET /api/appointments/:id (return single appointment)
Use ES modules (import/export). Add proper error handling."""

    def _booking_prompt(self, ctx: Dict) -> str:
        return """Create src/components/BookingForm.tsx:
Full appointment booking form with:
- Fields: patient name, phone (dir=ltr), email (dir=ltr), preferred date (type=date), preferred time (type=time), service dropdown (from translations), notes textarea
- Client-side validation with Arabic/English error messages from translations
- Form states: idle, loading (with spinner), success (with confirmation), error (with retry)
- Submit to POST http://localhost:3001/api/appointments
- After success, show confirmation message and reset form
- Labels and validation messages from the language context
Use lucide-react icons for submit button and status indicators."""

    async def persist_tasks(self, session: AsyncSession, project_id: str, tasks: List[Dict[str, Any]]) -> List[OrchestrationTaskRecord]:
        """Persist decomposed tasks to the database."""
        records = []
        for task_data in tasks:
            record = OrchestrationTaskRecord(
                id=task_data["id"],
                project_id=project_id,
                title=task_data["title"],
                description=task_data["description"],
                task_type=task_data["task_type"],
                state="planned",
                dependency_ids_json=json.dumps(task_data.get("dependencies", [])),
                acceptance_json=json.dumps(task_data.get("acceptance", [])),
                executor_needs_json=json.dumps({"capabilities": task_data.get("capabilities", ["coding"])}),
                revision=1,
            )
            session.add(record)
            records.append(record)
        await session.flush()
        return records


task_decomposition_service = TaskDecompositionService()
