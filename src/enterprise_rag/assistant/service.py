import asyncio
from typing import Any
from uuid import uuid4

from enterprise_rag.assistant.models import AssistantResult
from enterprise_rag.generation.service import AnswerGenerationService
from enterprise_rag.kbqa.service import KbqaService
from enterprise_rag.rag.service import RagService
from enterprise_rag.routing.models import ActorType, ConversationTurn, RouteTarget
from enterprise_rag.routing.service import RoutingService
from enterprise_rag.taskflow.models import TaskStage
from enterprise_rag.taskflow.service import TaskFlowService


class AssistantService:
    def __init__(
        self,
        *,
        routing: RoutingService,
        taskflow: TaskFlowService,
        kbqa: KbqaService,
        rag: RagService,
        generation: AnswerGenerationService,
    ) -> None:
        self.routing = routing
        self.taskflow = taskflow
        self.kbqa = kbqa
        self.rag = rag
        self.generation = generation

    async def respond(
        self,
        query: str,
        *,
        conversation_id: str | None = None,
        actor_type: ActorType = ActorType.UNKNOWN,
        history: list[ConversationTurn] | None = None,
        provided_slots: dict[str, Any] | None = None,
    ) -> AssistantResult:
        effective_conversation_id = conversation_id or uuid4().hex
        active_task = await asyncio.to_thread(
            self.taskflow.get_active_context, effective_conversation_id
        )
        route = await asyncio.to_thread(
            self.routing.route,
            query,
            actor_type=actor_type,
            history=history,
            active_task=active_task,
        )

        if route.target == RouteTarget.REJECT:
            return AssistantResult(
                conversation_id=effective_conversation_id,
                status="rejected",
                answer="该请求无法处理。如需车辆服务帮助，请换一种安全、合规的方式描述。",
                route=route,
            )
        if route.target == RouteTarget.CHITCHAT:
            return AssistantResult(
                conversation_id=effective_conversation_id,
                status="answered",
                answer="您好，我可以协助处理车辆、维保、保险理赔和购车相关问题。",
                route=route,
            )
        if route.target == RouteTarget.TASK_FLOW:
            task = await asyncio.to_thread(
                self.taskflow.process,
                conversation_id=effective_conversation_id,
                intent_name=route.intent.name,
                query=query,
                provided_slots=provided_slots,
            )
            status_by_stage = {
                TaskStage.NEEDS_INPUT: "needs_input",
                TaskStage.ACTION_COMPLETED: "action_completed",
                TaskStage.CANCELLED: "cancelled",
            }
            return AssistantResult(
                conversation_id=effective_conversation_id,
                status=status_by_stage[task.stage],
                answer=task.message,
                route=route,
                task=task,
            )
        if route.target == RouteTarget.KBQA:
            kbqa = await asyncio.to_thread(self.kbqa.answer, query)
            if kbqa.status == "answered" and kbqa.answer:
                return AssistantResult(
                    conversation_id=effective_conversation_id,
                    status="answered",
                    answer=kbqa.answer,
                    route=route,
                    kbqa=kbqa,
                )
            generated = await self.generation.answer(query)
            return AssistantResult(
                conversation_id=effective_conversation_id,
                status=generated.status,
                answer=generated.answer,
                route=route,
                kbqa=kbqa,
                retrieval=generated.retrieval,
                generation=generated,
                metadata={"quality_record_id": generated.record_id},
            )
        generated = await self.generation.answer(query)
        return AssistantResult(
            conversation_id=effective_conversation_id,
            status=generated.status,
            answer=generated.answer,
            route=route,
            retrieval=generated.retrieval,
            generation=generated,
            metadata={"quality_record_id": generated.record_id},
        )
