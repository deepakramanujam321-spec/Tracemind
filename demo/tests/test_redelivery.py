"""Reproduces the demo incident. test_redelivery_is_idempotent FAILS at the baseline commit."""
from conftest import pump_worker

PAYLOAD = {"user_id": "u-1", "title": "Welcome", "body": "Hello there"}


async def _rows(db, user="u-1"):
    cur = await db.execute("SELECT notification_id FROM notifications WHERE user_id = %s", (user,))
    return await cur.fetchall()


async def test_no_fault_single_row(api_client, db, channel):
    r = await api_client.post("/api/notifications", json=PAYLOAD)
    assert r.status_code == 202 and r.json()["status"] == "queued"
    assert await pump_worker(channel) == 1
    assert len(await _rows(db)) == 1


async def test_redelivery_is_idempotent(api_client, db, channel):
    """One logical notification => exactly one row, even when the ack fails after commit."""
    r = await api_client.post("/api/notifications", json={**PAYLOAD, "fault": "ack_failure"})
    nid = r.json()["notification_id"]
    assert await pump_worker(channel) == 2  # original delivery + redelivery
    rows = await _rows(db)
    assert [str(x[0]) for x in rows] == [nid], f"expected 1 row for {nid}, got {len(rows)}"


async def test_inbox_endpoint(api_client, db, channel):
    await api_client.post("/api/notifications", json=PAYLOAD)
    await pump_worker(channel)
    inbox = (await api_client.get("/api/notifications", params={"user_id": "u-1"})).json()
    assert len(inbox) == 1
    assert set(inbox[0]) == {"id", "notification_id", "user_id", "title", "body", "status", "created_at"}
