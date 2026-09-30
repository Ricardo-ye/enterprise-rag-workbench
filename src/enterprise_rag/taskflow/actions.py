from abc import ABC, abstractmethod
from typing import Any, ClassVar
from uuid import uuid4

from enterprise_rag.taskflow.models import ActionResult


class ActionAdapter(ABC):
    @abstractmethod
    def execute(self, intent: str, slots: dict[str, Any]) -> ActionResult:
        """Execute a business action through an external-system adapter."""


class MockBusinessActionAdapter(ActionAdapter):
    """Safe local adapter used until real CRM, claims, and scheduling APIs are configured."""

    _prefixes: ClassVar[dict[str, str]] = {
        "report_accident": "CASE",
        "claim_application": "CLAIM",
        "maintenance_booking": "SERVICE",
        "work_order_query": "WORK",
        "test_drive_booking": "DRIVE",
        "fleet_service": "FLEET",
    }

    def execute(self, intent: str, slots: dict[str, Any]) -> ActionResult:
        prefix = self._prefixes.get(intent, "TASK")
        reference_id = f"{prefix}-{uuid4().hex[:10].upper()}"
        return ActionResult(
            success=True,
            action=intent,
            reference_id=reference_id,
            message=f"任务已由模拟业务适配器受理，参考编号：{reference_id}",
            payload={"adapter": "mock", "slots": slots},
        )


class ActionRegistry:
    def __init__(self, default_adapter: ActionAdapter) -> None:
        self.default_adapter = default_adapter
        self._adapters: dict[str, ActionAdapter] = {}

    def register(self, intent: str, adapter: ActionAdapter) -> None:
        self._adapters[intent] = adapter

    def execute(self, intent: str, slots: dict[str, Any]) -> ActionResult:
        adapter = self._adapters.get(intent, self.default_adapter)
        return adapter.execute(intent, slots)
