from pathlib import Path


def _service_block(text: str, service: str, next_service: str | None) -> str:
    marker = f"\n  {service}:\n"
    start = text.index(marker) + 1
    if next_service:
        end_marker = f"\n  {next_service}:\n"
        end = text.index(end_marker, start)
    else:
        end = text.index("\nnetworks:\n", start)
    return text[start:end]


def test_compose_contours_are_physically_separate():
    text = Path("docker-compose.yml").read_text(encoding="utf-8")

    youtube = _service_block(text, "youtube-worker", "telegram-worker")
    telegram = _service_block(text, "telegram-worker", "auto-edit-worker")
    auto_edit = _service_block(text, "auto-edit-worker", None)

    assert "${RG_AUTO_EDIT_HOST_ROOT:-/volume1/RG_AUTO_EDIT}/YOUTUBE_CONTROL:/workspace:rw" in youtube
    assert "/volume1/docker/" not in youtube

    assert "/volume1/docker/RG_DEPLOY/cloudflare-video-moderation" in telegram
    assert "YOUTUBE_CONTROL" not in telegram
    assert "deploy.env" not in telegram
    assert "/.env" not in telegram

    assert "YOUTUBE_CONTROL" not in auto_edit
    assert "/volume1/docker/" not in auto_edit
    assert "${RG_AUTO_EDIT_HOST_ROOT:-/volume1/RG_AUTO_EDIT}/PROJECTS" in auto_edit


def test_workers_use_three_distinct_networks():
    text = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "youtube_net" in text
    assert "telegram_net" in text
    assert "auto_edit_net" in text
