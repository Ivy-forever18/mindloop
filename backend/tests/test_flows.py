async def test_task_can_be_atomized_and_shrunk(client):
    response = await client.post("/v1/tasks", json={"title": "我要写周报"})
    assert response.status_code == 201
    task = response.json()
    assert 3 <= len(task["steps"]) <= 5
    assert task["current_step"]["estimated_minutes"] <= 10
    shrunk = await client.post(f'/v1/tasks/{task["id"]}/actions', json={"action": "stuck"})
    assert shrunk.status_code == 200
    assert shrunk.json()["current_step"]["estimated_minutes"] == 2
    completed = await client.post(f'/v1/tasks/{task["id"]}/actions', json={"action": "complete"})
    assert completed.json()["current_step_index"] == 1


async def test_capture_reminder_and_clarification(client):
    created = await client.post("/v1/captures", json={"text": "明天早上10点提醒我找产品经理确认需求", "now": "2026-09-22T09:00:00+08:00"})
    assert created.status_code == 200
    assert created.json()["intent"] == "reminder"
    assert created.json()["data"]["remind_at"].startswith("2026-09-23T10:00:00")
    unclear = await client.post("/v1/captures", json={"text": "提醒我交作业"})
    assert unclear.json()["status"] == "needs_clarification"


async def test_focus_nudge_cooldown_and_return(client):
    task = (await client.post("/v1/tasks", json={"title": "准备明天的汇报"})).json()
    session = (await client.post("/v1/focus/sessions", json={"task_id": task["id"], "mode": "light"})).json()
    first = await client.post(f'/v1/focus/sessions/{session["id"]}/signals', json={"signal_type": "walking", "duration_seconds": 21})
    assert first.json()["prompted"] is True
    second = await client.post(f'/v1/focus/sessions/{session["id"]}/signals', json={"signal_type": "walking", "duration_seconds": 30})
    assert second.json()["prompted"] is False
    assert "冷却" in second.json()["reason"]
    help_response = await client.post(f'/v1/focus/sessions/{session["id"]}/respond', json={"response": "need_help"})
    assert help_response.json()["next_step"] == task["current_step"]["content"]
    commands = await client.get("/v1/devices/demo-pendant/commands")
    assert [item["kind"] for item in commands.json()] == ["gentle_nudge", "show_next_step"]


async def test_deep_mode_requires_camera_consent(client):
    response = await client.post("/v1/focus/sessions", json={"mode": "deep", "camera_consent": False})
    assert response.status_code == 422
