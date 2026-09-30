from fastapi.testclient import TestClient


def test_workspace_and_assets_are_served(client: TestClient) -> None:
    root = client.get("/")
    workspace = client.get("/ui")
    styles = client.get("/assets/styles.css")
    script = client.get("/assets/app.js")
    favicon = client.get("/assets/favicon.svg")

    assert root.status_code == 200
    assert workspace.status_code == 200
    assert root.headers["content-type"].startswith("text/html")
    assert '<html lang="zh-CN">' in root.text
    assert "企业 RAG 工作台" in root.text
    assert 'id="assistant-form"' in root.text
    assert 'id="document-form"' in root.text
    assert 'id="operations-heading"' in root.text
    assert styles.status_code == 200
    assert "--accent: #007c6e" in styles.text
    assert script.status_code == 200
    assert 'apiFetch("/api/v1/assistant/respond"' in script.text
    assert favicon.status_code == 200
    assert favicon.headers["content-type"].startswith("image/svg+xml")


def test_workspace_uses_external_assets_for_content_security_policy(
    client: TestClient,
) -> None:
    response = client.get("/")

    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert '<script src="/assets/app.js?v=11" defer></script>' in response.text
    assert "<script>" not in response.text
    assert "<style>" not in response.text
