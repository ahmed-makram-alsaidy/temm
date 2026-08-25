"""Multi-agent workflow boundary for future real DAG execution."""

from typing import Any, Callable, Dict, Optional


class WorkflowEngine:
    """Refuse workflow execution until every node has a real executor."""

    async def execute_workflow(
        self,
        workflow_id: str,
        initial_input: str,
        on_node_event: Optional[Callable[[str, str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Reject simulated DAG completion and fabricated consensus reports."""
        raise RuntimeError(
            "Simulated workflow execution is disabled. Configure real node "
            "executors, routing, retries, and artifact handoff first."
        )


workflow_engine = WorkflowEngine()
