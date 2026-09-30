import re
import unicodedata
from collections.abc import Iterable
from itertools import pairwise

_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]+|[\u3400-\u4dbf\u4e00-\u9fff]")


def normalized_tokens(text: str) -> list[str]:
    """Tokenize Latin words and enrich CJK text with adjacent bigrams."""
    base = [match.group(0).lower() for match in _TOKEN_PATTERN.finditer(text)]
    cjk = [token for token in base if len(token) == 1 and "\u3400" <= token <= "\u9fff"]
    bigrams = [first + second for first, second in pairwise(cjk)]
    return [*base, *bigrams]


def fts_text(text: str) -> str:
    return " ".join(normalized_tokens(text))


def fts_query(text: str) -> str:
    tokens = list(dict.fromkeys(normalized_tokens(text)))
    return " OR ".join(f'"{token}"' for token in tokens)


def approximate_token_count(parts: Iterable[str]) -> int:
    return sum(len(normalized_tokens(part)) for part in parts)


def normalize_faq_question(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    return re.sub(r"[^\w\u3400-\u4dbf\u4e00-\u9fff]+", "", normalized)
