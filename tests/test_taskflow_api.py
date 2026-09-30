from typing import Any, cast

from fastapi.testclient import TestClient


def _respond(
    client: TestClient,
    query: str,
    *,
    conversation_id: str,
    provided_slots: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/assistant/respond",
        json={
            "query": query,
            "conversation_id": conversation_id,
            "provided_slots": provided_slots or {},
        },
    )
    assert response.status_code == 200, response.text
    return cast(dict[str, Any], response.json())


def test_maintenance_booking_collects_slots_and_executes_action(client: TestClient) -> None:
    conversation_id = "conversation-maintenance-1"

    first = _respond(client, "我要预约保养", conversation_id=conversation_id)
    assert first["status"] == "needs_input"
    assert first["task"]["requested_slot"] == "vehicle_id"
    assert first["task"]["session"]["slots"]["service_type"] == "保养"

    second = _respond(
        client,
        "车辆 VIN 是 LDC613P23A1305189",
        conversation_id=conversation_id,
    )
    assert second["status"] == "needs_input"
    assert second["task"]["requested_slot"] == "preferred_time"
    assert second["route"]["intent"]["inherited_from_context"] is True

    third = _respond(client, "明天下午", conversation_id=conversation_id)
    assert third["status"] == "needs_input"
    assert third["task"]["requested_slot"] == "service_center"

    completed = _respond(client, "上海浦东服务中心", conversation_id=conversation_id)
    assert completed["status"] == "action_completed"
    assert completed["task"]["stage"] == "action_completed"
    assert completed["task"]["action"]["payload"]["adapter"] == "mock"
    assert completed["task"]["action"]["reference_id"].startswith("SERVICE-")

    state = client.get(f"/api/v1/tasks/{conversation_id}")
    assert state.status_code == 200
    assert state.json()["status"] == "completed"
    assert state.json()["slots"]["preferred_time"] == "明天下午"


def test_task_can_be_completed_with_structured_slots(client: TestClient) -> None:
    result = _respond(
        client,
        "我要预约试驾",
        conversation_id="conversation-drive-1",
        provided_slots={
            "model": "星海 S7",
            "city": "上海",
            "preferred_time": "后天上午",
            "contact": "13800138000",
        },
    )

    assert result["status"] == "action_completed"
    assert result["task"]["session"]["intent"] == "test_drive_booking"
    assert result["task"]["action"]["reference_id"].startswith("DRIVE-")


def test_active_task_can_be_cancelled(client: TestClient) -> None:
    conversation_id = "conversation-cancel-1"
    started = _respond(client, "预约维修", conversation_id=conversation_id)
    assert started["status"] == "needs_input"

    cancelled = _respond(client, "不用了, 取消", conversation_id=conversation_id)
    assert cancelled["status"] == "cancelled"
    assert cancelled["task"]["session"]["status"] == "cancelled"
