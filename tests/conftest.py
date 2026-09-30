from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from enterprise_rag.core.config import Settings
from enterprise_rag.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    test_data_dir = Path("work/test-databases")
    test_data_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        environment="test",
        model_provider="mock",
        log_level="ERROR",
        database_path=test_data_dir / f"{uuid4().hex}.db",
        chunk_max_chars=220,
        chunk_overlap_chars=40,
        embedding_dimensions=128,
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client
