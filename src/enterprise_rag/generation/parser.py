import json
import re
from typing import Any

from pydantic import ValidationError

from enterprise_rag.generation.models import GeneratedCandidate


class GenerationParseError(ValueError):
    pass


def parse_candidate(text: str) -> GeneratedCandidate:
    candidate_text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", candidate_text, re.DOTALL)
    if fenced:
        candidate_text = fenced.group(1)
    try:
        payload: Any = json.loads(candidate_text)
        return GeneratedCandidate.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise GenerationParseError("model response is not valid grounded-answer JSON") from exc


def citation_indices(answer: str) -> list[int]:
    return list(dict.fromkeys(int(value) for value in re.findall(r"\[(\d+)]", answer)))
