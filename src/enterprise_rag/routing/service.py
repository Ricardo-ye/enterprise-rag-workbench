import re
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from enterprise_rag.knowledge.embeddings import EmbeddingProvider, cosine_similarity
from enterprise_rag.routing.config import (
    IntentConfig,
    RoutingConfig,
    SafetyRuleConfig,
)
from enterprise_rag.routing.models import (
    ActiveTaskContext,
    ActorType,
    Audience,
    Classification,
    ConversationTurn,
    IntentClassification,
    IntentKind,
    RouteTarget,
    RoutingDecision,
    SafetyAssessment,
    SafetyDecision,
    SafetyMatch,
    TraceStep,
)


def normalize_query(query: str) -> str:
    normalized = unicodedata.normalize("NFKC", query).lower()
    return re.sub(r"\s+", " ", normalized).strip()


@dataclass(frozen=True, slots=True)
class _ScoredMatch:
    confidence: float
    matched_terms: list[str]


class SafetyClassifier:
    def __init__(self, rules: list[SafetyRuleConfig]) -> None:
        self._rules = [
            (
                rule,
                [re.compile(pattern, flags=re.IGNORECASE) for pattern in rule.patterns],
            )
            for rule in rules
        ]

    def classify(self, query: str) -> SafetyAssessment:
        matches: list[SafetyMatch] = []
        for rule, patterns in self._rules:
            if any(pattern.search(query) for pattern in patterns):
                matches.append(
                    SafetyMatch(
                        rule_id=rule.id,
                        category=rule.category,
                        decision=SafetyDecision(rule.decision),
                    )
                )
        decision = SafetyDecision.ALLOW
        if any(match.decision == SafetyDecision.BLOCK for match in matches):
            decision = SafetyDecision.BLOCK
        elif matches:
            decision = SafetyDecision.REVIEW
        return SafetyAssessment(decision=decision, matches=matches)


class RoutingService:
    def __init__(
        self,
        *,
        config: RoutingConfig,
        min_intent_confidence: float,
        min_domain_confidence: float,
        embedding_provider: EmbeddingProvider,
        fallback_similarity_threshold: float,
    ) -> None:
        self.config = config
        self.min_intent_confidence = min_intent_confidence
        self.min_domain_confidence = min_domain_confidence
        self.embedding_provider = embedding_provider
        self.fallback_similarity_threshold = fallback_similarity_threshold
        self.safety_classifier = SafetyClassifier(config.safety_rules)
        self._domains = {domain.name: domain for domain in config.domains}
        self._intents = {intent.name: intent for intent in config.intents}
        examples = [(intent, keyword) for intent in config.intents for keyword in intent.keywords]
        example_vectors = embedding_provider.embed(
            [normalize_query(keyword) for _, keyword in examples]
        )
        self._intent_examples = [
            (intent, keyword, vector)
            for (intent, keyword), vector in zip(examples, example_vectors, strict=True)
        ]

    def route(
        self,
        query: str,
        *,
        actor_type: ActorType = ActorType.UNKNOWN,
        history: list[ConversationTurn] | None = None,
        active_task: ActiveTaskContext | None = None,
    ) -> RoutingDecision:
        trace_id = uuid4().hex
        normalized = normalize_query(query)
        history = history or []
        trace: list[TraceStep] = []

        safety = self.safety_classifier.classify(normalized)
        trace.append(
            TraceStep(
                stage="safety",
                decision=safety.decision.value,
                confidence=1.0,
                details={"matched_rules": [match.rule_id for match in safety.matches]},
            )
        )
        audience, audience_confidence, audience_terms = self._classify_audience(
            normalized, actor_type
        )
        trace.append(
            TraceStep(
                stage="audience",
                decision=audience.value,
                confidence=audience_confidence,
                details={"matched_terms": audience_terms, "actor_type": actor_type.value},
            )
        )

        if safety.decision == SafetyDecision.BLOCK:
            unknown_domain = self._unknown_domain()
            unknown_intent = self._unknown_intent()
            trace.append(
                TraceStep(
                    stage="route",
                    decision=RouteTarget.REJECT.value,
                    confidence=1.0,
                    details={"reason": "blocked_by_safety_policy"},
                )
            )
            return RoutingDecision(
                trace_id=trace_id,
                normalized_query=normalized,
                safety=safety,
                audience=audience,
                domain=unknown_domain,
                intent=unknown_intent,
                is_follow_up=False,
                target=RouteTarget.REJECT,
                reason="请求命中安全规则; 已在入口拒绝。",
                trace=trace,
            )

        if self._is_chitchat(normalized):
            trace.append(
                TraceStep(
                    stage="route",
                    decision=RouteTarget.CHITCHAT.value,
                    confidence=0.99,
                    details={"reason": "matched_chitchat_whitelist"},
                )
            )
            return RoutingDecision(
                trace_id=trace_id,
                normalized_query=normalized,
                safety=safety,
                audience=audience,
                domain=self._unknown_domain(),
                intent=self._unknown_intent(),
                is_follow_up=False,
                target=RouteTarget.CHITCHAT,
                reason="命中闲聊白名单。",
                trace=trace,
            )

        is_follow_up = self._is_follow_up(normalized, active_task)
        classification_query = self._classification_query(normalized, history, is_follow_up)
        domain = self._classify_domain(classification_query)
        intent = self._classify_intent(classification_query)

        if active_task is not None:
            active_intent = self._intents.get(active_task.intent)
            has_strong_new_intent = (
                intent.name != "unknown"
                and intent.name != active_task.intent
                and intent.confidence >= self.min_intent_confidence
            )
            if active_intent and not has_strong_new_intent:
                intent = self._intent_result(
                    active_intent,
                    confidence=max(intent.confidence, 0.9),
                    matched_terms=intent.matched_terms,
                    inherited=True,
                    source="context",
                )
                domain = self._domain_for_intent(active_intent, domain)
                is_follow_up = True

        if intent.name != "unknown":
            configured_intent = self._intents[intent.name]
            domain = self._domain_for_intent(configured_intent, domain)

        trace.extend(
            [
                TraceStep(
                    stage="domain",
                    decision=domain.name,
                    confidence=domain.confidence,
                    details={"matched_terms": domain.matched_terms},
                ),
                TraceStep(
                    stage="intent",
                    decision=intent.name,
                    confidence=intent.confidence,
                    details={
                        "kind": intent.kind.value,
                        "matched_terms": intent.matched_terms,
                        "inherited_from_context": intent.inherited_from_context,
                        "source": intent.source,
                        "required_slots": intent.required_slots,
                    },
                ),
            ]
        )

        target, reason, route_confidence = self._select_target(domain, intent)
        trace.append(
            TraceStep(
                stage="route",
                decision=target.value,
                confidence=route_confidence,
                details={
                    "reason": reason,
                    "safety_review_required": safety.decision == SafetyDecision.REVIEW,
                },
            )
        )
        return RoutingDecision(
            trace_id=trace_id,
            normalized_query=normalized,
            safety=safety,
            audience=audience,
            domain=domain,
            intent=intent,
            is_follow_up=is_follow_up,
            target=target,
            reason=reason,
            trace=trace,
        )

    def catalog(self) -> dict[str, Any]:
        return {
            "version": self.config.version,
            "domains": [domain.model_dump() for domain in self.config.domains],
            "intents": [intent.model_dump(mode="json") for intent in self.config.intents],
            "thresholds": {
                "intent": self.min_intent_confidence,
                "domain": self.min_domain_confidence,
                "fallback_similarity": self.fallback_similarity_threshold,
            },
        }

    def _classify_audience(
        self,
        query: str,
        actor_type: ActorType,
    ) -> tuple[Audience, float, list[str]]:
        if actor_type in {ActorType.EMPLOYEE, ActorType.PARTNER, ActorType.BUSINESS}:
            return Audience.TO_B, 1.0, [f"actor:{actor_type.value}"]
        if actor_type == ActorType.CONSUMER:
            return Audience.TO_C, 1.0, ["actor:consumer"]
        business_matches = self._contained_terms(query, self.config.audience.business_keywords)
        consumer_matches = self._contained_terms(query, self.config.audience.consumer_keywords)
        if len(business_matches) > len(consumer_matches):
            return Audience.TO_B, min(0.7 + 0.08 * len(business_matches), 0.96), business_matches
        confidence = 0.7 if consumer_matches else 0.55
        return Audience.TO_C, confidence, consumer_matches

    def _classify_domain(self, query: str) -> Classification:
        candidates = [
            (domain, self._score_terms(query, domain.keywords)) for domain in self.config.domains
        ]
        domain, match = max(candidates, key=lambda item: item[1].confidence)
        if match.confidence < self.min_domain_confidence:
            return self._unknown_domain()
        return Classification(
            name=domain.name,
            display_name=domain.display_name,
            confidence=match.confidence,
            matched_terms=match.matched_terms,
        )

    def _classify_intent(self, query: str) -> IntentClassification:
        candidates = [
            (intent, self._score_terms(query, intent.keywords)) for intent in self.config.intents
        ]
        intent, match = max(
            candidates,
            key=lambda item: (item[1].confidence, item[0].priority),
        )
        if match.confidence < self.min_intent_confidence:
            fallback = self._nearest_intent(query)
            if fallback is not None:
                fallback_intent, fallback_term, similarity = fallback
                calibrated_confidence = min(0.55 + 0.4 * similarity, 0.95)
                if calibrated_confidence >= self.min_intent_confidence:
                    return self._intent_result(
                        fallback_intent,
                        confidence=calibrated_confidence,
                        matched_terms=[fallback_term],
                        source="nearest_intent",
                    )
            return self._unknown_intent(confidence=match.confidence)
        return self._intent_result(
            intent,
            confidence=match.confidence,
            matched_terms=match.matched_terms,
            source="keyword",
        )

    def _nearest_intent(
        self,
        query: str,
    ) -> tuple[IntentConfig, str, float] | None:
        query_vector = self.embedding_provider.embed([query])[0]
        candidates = [
            (intent, keyword, cosine_similarity(query_vector, vector))
            for intent, keyword, vector in self._intent_examples
        ]
        best = max(candidates, key=lambda item: (item[2], item[0].priority))
        if best[2] < self.fallback_similarity_threshold:
            return None
        return best

    def _select_target(
        self,
        domain: Classification,
        intent: IntentClassification,
    ) -> tuple[RouteTarget, str, float]:
        if intent.name != "unknown" and intent.confidence >= self.min_intent_confidence:
            if intent.kind == IntentKind.TASK:
                return (
                    RouteTarget.TASK_FLOW,
                    "任务型意图需要收集槽位并执行后端动作。",
                    intent.confidence,
                )
            return (
                RouteTarget.KBQA,
                "已识别为高置信问答型意图; 优先进入 KBQA。",
                intent.confidence,
            )
        if domain.name != "unknown" and domain.confidence >= self.min_domain_confidence:
            return (
                RouteTarget.RAG,
                "领域已识别但子意图置信度不足; 降级至 RAG。",
                domain.confidence,
            )
        return RouteTarget.RAG, "未识别到可靠领域或意图; 交由 RAG 兜底。", 0.5

    def _domain_for_intent(
        self,
        intent: IntentConfig,
        current: Classification,
    ) -> Classification:
        domain = self._domains[intent.domain]
        return Classification(
            name=domain.name,
            display_name=domain.display_name,
            confidence=max(current.confidence, 0.85),
            matched_terms=current.matched_terms,
        )

    def _intent_result(
        self,
        intent: IntentConfig,
        *,
        confidence: float,
        matched_terms: list[str],
        inherited: bool = False,
        source: str = "keyword",
    ) -> IntentClassification:
        return IntentClassification(
            name=intent.name,
            display_name=intent.display_name,
            confidence=min(confidence, 1.0),
            matched_terms=matched_terms,
            kind=IntentKind(intent.kind),
            domain=intent.domain,
            required_slots=intent.required_slots,
            inherited_from_context=inherited,
            source=source,
        )

    def _score_terms(self, query: str, terms: list[str]) -> _ScoredMatch:
        matches = self._contained_terms(query, terms)
        if not matches:
            return _ScoredMatch(confidence=0.0, matched_terms=[])
        canonical_query = self._canonical_phrase(query)
        if any(canonical_query == self._canonical_phrase(term) for term in matches):
            confidence = 0.99
        else:
            longest = max(len(term) for term in matches)
            signal = 0.7 + 0.08 * (len(matches) - 1) + min(longest, 8) * 0.012
            confidence = min(signal, 0.96)
        return _ScoredMatch(confidence=confidence, matched_terms=matches)

    def _contained_terms(self, query: str, terms: list[str]) -> list[str]:
        return [term for term in terms if normalize_query(term) in query]

    def _is_chitchat(self, query: str) -> bool:
        canonical = self._canonical_phrase(query)
        return any(
            canonical == self._canonical_phrase(phrase) for phrase in self.config.chitchat_phrases
        )

    def _is_follow_up(
        self,
        query: str,
        active_task: ActiveTaskContext | None,
    ) -> bool:
        if active_task is not None:
            return True
        return any(
            query.startswith(normalize_query(marker)) for marker in self.config.follow_up_markers
        )

    def _classification_query(
        self,
        query: str,
        history: list[ConversationTurn],
        is_follow_up: bool,
    ) -> str:
        if not is_follow_up:
            return query
        previous_user_message = next(
            (normalize_query(turn.content) for turn in reversed(history) if turn.role == "user"),
            "",
        )
        return f"{previous_user_message} {query}".strip()

    def _canonical_phrase(self, value: str) -> str:
        return re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", "", normalize_query(value))

    def _unknown_domain(self) -> Classification:
        return Classification(
            name="unknown",
            display_name="未知领域",
            confidence=0.0,
            matched_terms=[],
        )

    def _unknown_intent(self, *, confidence: float = 0.0) -> IntentClassification:
        return IntentClassification(
            name="unknown",
            display_name="未知意图",
            confidence=confidence,
            matched_terms=[],
            kind=IntentKind.UNKNOWN,
            domain="unknown",
            required_slots=[],
            source="none",
        )
