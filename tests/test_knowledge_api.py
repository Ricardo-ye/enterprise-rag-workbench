import json
from typing import Any, cast

from fastapi.testclient import TestClient


def _upload(
    client: TestClient,
    content: str,
    *,
    source_uri: str = "kb://vehicle/manual",
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={"file": ("vehicle.md", content.encode(), "text/markdown")},
        data={
            "source_uri": source_uri,
            "metadata_json": json.dumps({"department": "after-sales"}),
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_document_lifecycle_and_versioning(client: TestClient) -> None:
    first = _upload(
        client,
        "# 充电指南\n\n## 快充\n\n车辆支持 800V 快充平台。\n\n## 安全\n\n雨天可以正常充电。",
    )
    assert first["action"] == "created"
    document = first["document"]
    assert isinstance(document, dict)
    assert document["current_version"] == 1
    assert document["chunk_count"] == 2
    document_id = str(document["id"])

    unchanged = _upload(
        client,
        "# 充电指南\n\n## 快充\n\n车辆支持 800V 快充平台。\n\n## 安全\n\n雨天可以正常充电。",
    )
    assert unchanged["action"] == "unchanged"

    updated = _upload(
        client,
        "# 充电指南\n\n## 快充\n\n车辆支持 800V 快充平台, 峰值功率 350kW。",
    )
    assert updated["action"] == "updated"
    assert updated["document"]["current_version"] == 2

    documents = client.get("/api/v1/knowledge/documents")
    assert documents.status_code == 200
    assert len(documents.json()) == 1

    rebuilt = client.post("/api/v1/knowledge/indexes/rebuild")
    assert rebuilt.status_code == 200
    assert rebuilt.json() == {
        "status": "ok",
        "documents": 1,
        "chunks": 1,
        "faqs": 0,
    }

    deleted = client.delete(f"/api/v1/knowledge/documents/{document_id}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/knowledge/documents").json()[0]["status"] == "deleted"


def test_duplicate_content_is_not_reindexed(client: TestClient) -> None:
    content = "# 保修政策\n\n整车保修期以购车合同为准。"
    first = _upload(client, content, source_uri="kb://warranty/a")
    duplicate = _upload(client, content, source_uri="kb://warranty/b")

    assert duplicate["action"] == "duplicate"
    assert duplicate["document"]["id"] == first["document"]["id"]
    assert len(client.get("/api/v1/knowledge/documents").json()) == 1


def test_lexical_and_vector_search(client: TestClient) -> None:
    _upload(
        client,
        "# 续航说明\n\n低温环境会影响动力电池活性, 冬季续航里程可能下降。",
    )
    response = client.post(
        "/api/v1/knowledge/search",
        json={"query": "冬季续航", "limit": 3},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["lexical"][0]["source_type"] == "document"
    assert "冬季续航" in body["lexical"][0]["content"]
    assert body["vector"][0]["source_type"] == "document"
    assert body["vector"][0]["score"] > 0


def test_faq_import_is_idempotent_and_searchable(client: TestClient) -> None:
    payload = {
        "items": [
            {
                "question": "预约保养需要提前多久?",
                "answer": "建议至少提前一天预约。",
                "metadata": {"business": "maintenance"},
            }
        ]
    }
    first = client.post("/api/v1/knowledge/faqs/import", json=payload)
    second = client.post("/api/v1/knowledge/faqs/import", json=payload)

    assert first.status_code == 200
    assert first.json() == {"created": 1, "updated": 0, "unchanged": 0}
    assert second.json() == {"created": 0, "updated": 0, "unchanged": 1}

    search = client.post(
        "/api/v1/knowledge/search",
        json={"query": "预约保养", "limit": 3},
    )
    assert search.status_code == 200
    assert any(hit["source_type"] == "faq" for hit in search.json()["lexical"])


def test_rejects_unsupported_files_and_invalid_metadata(client: TestClient) -> None:
    unsupported = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={"file": ("image.png", b"not an image", "image/png")},
    )
    assert unsupported.status_code == 415

    invalid_metadata = client.post(
        "/api/v1/knowledge/documents/ingest",
        files={"file": ("note.txt", b"hello", "text/plain")},
        data={"metadata_json": "[]"},
    )
    assert invalid_metadata.status_code == 422
