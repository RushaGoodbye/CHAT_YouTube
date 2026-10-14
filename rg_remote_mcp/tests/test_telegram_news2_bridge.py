import pytest
from rg_remote_mcp import server


@pytest.mark.asyncio
async def test_news2_status_uses_fixed_commands(monkeypatch):
    calls = []
    async def fake_worker_post(contour, route, payload):
        calls.append((contour, route, payload))
        return {"exit_code": 0, "stdout": "OK", "stderr": ""}
    monkeypatch.setattr(server, "worker_post", fake_worker_post)
    result = await server.telegram_news2_status()
    assert result["v35"]["exit_code"] == 0
    assert result["v36"]["exit_code"] == 0
    assert [x[2]["argv"][-1] for x in calls] == ["status", "status"]
    assert all(x[0] == "telegram" and x[1] == "/command" for x in calls)


@pytest.mark.asyncio
async def test_photo_review_blocks_unvalidated_input(monkeypatch):
    calls = []
    async def fake_worker_post(contour, route, payload):
        calls.append(payload)
        return {"exit_code": 0, "stdout": "OK", "stderr": ""}
    monkeypatch.setattr(server, "worker_post", fake_worker_post)
    for bad_id in ("../../etc/passwd", "abcd", "z" * 24):
        with pytest.raises(ValueError):
            await server.telegram_news2_photo_review(bad_id, "accept", "VERIFIED_BY_HUMAN")
    with pytest.raises(ValueError):
        await server.telegram_news2_photo_review("a"*24, "accept", "WATERMARK")
    with pytest.raises(ValueError):
        await server.telegram_news2_photo_review("a"*24, "publish", "VERIFIED_BY_HUMAN")
    assert not calls
    await server.telegram_news2_photo_review("a"*24, "accept", "VERIFIED_BY_HUMAN")
    assert calls[0]["argv"] == [
        "python3", "/workspace/telegram_news_2/rg_v35.py",
        "review", "--id", "a"*24, "--decision", "accept",
        "--note", "VERIFIED_BY_HUMAN",
    ]
