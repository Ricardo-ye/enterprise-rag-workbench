from typing import Annotated, cast

from fastapi import Depends, Request

from enterprise_rag.assistant.service import AssistantService
from enterprise_rag.generation.evaluation import AnswerEvaluator
from enterprise_rag.generation.repository import AnswerRecordRepository
from enterprise_rag.generation.service import AnswerGenerationService
from enterprise_rag.kbqa.repository import KbqaRepository
from enterprise_rag.kbqa.service import KbqaService
from enterprise_rag.knowledge.service import KnowledgeService
from enterprise_rag.providers.base import ModelProvider
from enterprise_rag.rag.evaluation import RetrieverEvaluator
from enterprise_rag.rag.service import RagService
from enterprise_rag.routing.service import RoutingService
from enterprise_rag.taskflow.service import TaskFlowService


def get_model_provider(request: Request) -> ModelProvider:
    return cast(ModelProvider, request.app.state.model_provider)


ModelProviderDependency = Annotated[ModelProvider, Depends(get_model_provider)]


def get_knowledge_service(request: Request) -> KnowledgeService:
    return cast(KnowledgeService, request.app.state.knowledge_service)


KnowledgeServiceDependency = Annotated[KnowledgeService, Depends(get_knowledge_service)]


def get_routing_service(request: Request) -> RoutingService:
    return cast(RoutingService, request.app.state.routing_service)


RoutingServiceDependency = Annotated[RoutingService, Depends(get_routing_service)]


def get_taskflow_service(request: Request) -> TaskFlowService:
    return cast(TaskFlowService, request.app.state.taskflow_service)


TaskFlowServiceDependency = Annotated[TaskFlowService, Depends(get_taskflow_service)]


def get_kbqa_service(request: Request) -> KbqaService:
    return cast(KbqaService, request.app.state.kbqa_service)


KbqaServiceDependency = Annotated[KbqaService, Depends(get_kbqa_service)]


def get_kbqa_repository(request: Request) -> KbqaRepository:
    return cast(KbqaRepository, request.app.state.kbqa_repository)


KbqaRepositoryDependency = Annotated[KbqaRepository, Depends(get_kbqa_repository)]


def get_assistant_service(request: Request) -> AssistantService:
    return cast(AssistantService, request.app.state.assistant_service)


AssistantServiceDependency = Annotated[AssistantService, Depends(get_assistant_service)]


def get_rag_service(request: Request) -> RagService:
    return cast(RagService, request.app.state.rag_service)


RagServiceDependency = Annotated[RagService, Depends(get_rag_service)]


def get_retriever_evaluator(request: Request) -> RetrieverEvaluator:
    return cast(RetrieverEvaluator, request.app.state.retriever_evaluator)


RetrieverEvaluatorDependency = Annotated[RetrieverEvaluator, Depends(get_retriever_evaluator)]


def get_generation_service(request: Request) -> AnswerGenerationService:
    return cast(AnswerGenerationService, request.app.state.generation_service)


AnswerGenerationServiceDependency = Annotated[
    AnswerGenerationService, Depends(get_generation_service)
]


def get_answer_record_repository(request: Request) -> AnswerRecordRepository:
    return cast(AnswerRecordRepository, request.app.state.answer_record_repository)


AnswerRecordRepositoryDependency = Annotated[
    AnswerRecordRepository, Depends(get_answer_record_repository)
]


def get_answer_evaluator(request: Request) -> AnswerEvaluator:
    return cast(AnswerEvaluator, request.app.state.answer_evaluator)


AnswerEvaluatorDependency = Annotated[AnswerEvaluator, Depends(get_answer_evaluator)]
