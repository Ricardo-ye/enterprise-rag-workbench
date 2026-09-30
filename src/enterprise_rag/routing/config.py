import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from enterprise_rag.core.errors import ConfigurationError
from enterprise_rag.routing.models import IntentKind, SafetyDecision


class AudienceConfig(BaseModel):
    business_keywords: list[str] = Field(min_length=1)
    consumer_keywords: list[str] = Field(min_length=1)


class DomainConfig(BaseModel):
    name: str
    display_name: str
    keywords: list[str] = Field(min_length=1)


class IntentConfig(BaseModel):
    name: str
    display_name: str
    domain: str
    kind: Literal[IntentKind.TASK, IntentKind.QA]
    keywords: list[str] = Field(min_length=1)
    required_slots: list[str] = Field(default_factory=list)
    priority: int = Field(default=0, ge=0, le=1000)


class SafetyRuleConfig(BaseModel):
    id: str
    category: str
    decision: Literal[SafetyDecision.REVIEW, SafetyDecision.BLOCK]
    patterns: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_patterns(self) -> "SafetyRuleConfig":
        for pattern in self.patterns:
            try:
                re.compile(pattern, flags=re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid regex in safety rule {self.id}: {pattern}") from exc
        return self


class RoutingConfig(BaseModel):
    version: int = Field(ge=1)
    audience: AudienceConfig
    domains: list[DomainConfig] = Field(min_length=1)
    intents: list[IntentConfig] = Field(min_length=1)
    chitchat_phrases: list[str] = Field(min_length=1)
    follow_up_markers: list[str] = Field(min_length=1)
    safety_rules: list[SafetyRuleConfig] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "RoutingConfig":
        domain_names = [domain.name for domain in self.domains]
        if len(set(domain_names)) != len(domain_names):
            raise ValueError("Domain names must be unique")
        intent_names = [intent.name for intent in self.intents]
        if len(set(intent_names)) != len(intent_names):
            raise ValueError("Intent names must be unique")
        unknown_domains = {
            intent.domain for intent in self.intents if intent.domain not in domain_names
        }
        if unknown_domains:
            raise ValueError(f"Unknown intent domains: {sorted(unknown_domains)}")
        return self


def load_routing_config(path: Path) -> RoutingConfig:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RoutingConfig.model_validate(payload)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Routing config does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Routing config is not valid JSON: {path}") from exc
    except ValidationError as exc:
        raise ConfigurationError(f"Routing config validation failed: {exc}") from exc
