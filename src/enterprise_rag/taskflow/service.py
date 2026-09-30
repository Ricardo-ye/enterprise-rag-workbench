from typing import Any, ClassVar

from enterprise_rag.routing.config import IntentConfig
from enterprise_rag.routing.models import ActiveTaskContext
from enterprise_rag.taskflow.actions import ActionRegistry
from enterprise_rag.taskflow.models import TaskFlowResult, TaskSession, TaskStage
from enterprise_rag.taskflow.nlu import SlotExtractor
from enterprise_rag.taskflow.repository import TaskRepository


class TaskFlowService:
    _cancel_phrases: ClassVar[set[str]] = {"取消", "不用了", "退出", "停止办理", "不办了"}
    _slot_prompts: ClassVar[dict[str, str]] = {
        "vehicle_id": "请提供车辆 VIN（17 位）或通过业务前端选择车辆。",
        "incident_time": "事故发生在什么时间？",
        "location": "事故发生在哪里？",
        "policy_number": "请提供保单号。",
        "claim_type": "请选择理赔类型，例如车辆损失、人伤或玻璃。",
        "service_type": "需要预约保养还是维修？",
        "preferred_time": "希望安排在什么时间？",
        "service_center": "请选择服务中心或门店。",
        "work_order_id": "请提供工单号。",
        "model": "希望试驾哪款车型？",
        "city": "希望在哪个城市办理？",
        "contact": "请提供用于确认的手机号码。",
        "company_name": "请提供企业名称。",
        "fleet_size": "预计采购或管理多少辆车？",
    }

    def __init__(
        self,
        *,
        repository: TaskRepository,
        extractor: SlotExtractor,
        actions: ActionRegistry,
        intents: list[IntentConfig],
    ) -> None:
        self.repository = repository
        self.extractor = extractor
        self.actions = actions
        self._intents = {intent.name: intent for intent in intents}

    def get_active_context(self, conversation_id: str) -> ActiveTaskContext | None:
        session = self.repository.get_active(conversation_id)
        if session is None:
            return None
        return ActiveTaskContext(intent=session.intent, collected_slots=session.slots)

    def get_latest(self, conversation_id: str) -> TaskSession | None:
        return self.repository.get_latest(conversation_id)

    def process(
        self,
        *,
        conversation_id: str,
        intent_name: str,
        query: str,
        provided_slots: dict[str, Any] | None = None,
    ) -> TaskFlowResult:
        intent = self._intents[intent_name]
        active = self.repository.get_active(conversation_id)
        if active and any(phrase in query for phrase in self._cancel_phrases):
            cancelled = self.repository.cancel(active.id, reason="user_cancelled")
            return TaskFlowResult(
                stage=TaskStage.CANCELLED,
                session=cancelled,
                message="当前任务已取消。",
            )
        if active and active.intent != intent_name:
            self.repository.cancel(active.id, reason="superseded_by_new_intent")
            active = None
        session = active or self.repository.create(
            conversation_id=conversation_id,
            intent=intent_name,
            missing_slots=intent.required_slots,
        )

        extracted = self.extractor.extract(query, intent.required_slots, provided_slots)
        slots = {**session.slots, **extracted}
        missing = [slot for slot in intent.required_slots if slot not in slots]
        session = self.repository.update_slots(session.id, slots=slots, missing_slots=missing)
        if missing:
            requested_slot = missing[0]
            return TaskFlowResult(
                stage=TaskStage.NEEDS_INPUT,
                session=session,
                message=self._slot_prompts.get(requested_slot, f"请提供 {requested_slot}。"),
                requested_slot=requested_slot,
            )

        action = self.actions.execute(intent_name, slots)
        completed = self.repository.complete(session.id, action.model_dump(mode="json"))
        return TaskFlowResult(
            stage=TaskStage.ACTION_COMPLETED,
            session=completed,
            message=action.message,
            action=action,
        )
