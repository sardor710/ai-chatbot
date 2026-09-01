"""Unit tests for the local web dashboard server."""

from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.control.commands import ControlManager
from app.database.database import close_db, init_db
from app.web.server import WebDashboardServer


@pytest.fixture
async def dashboard_setup(tmp_path):
    db_file = tmp_path / "test_dash.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    await init_db(db_url)

    soul_file = tmp_path / "soul.md"
    soul_file.write_text("Test Soul", encoding="utf-8")

    # Use port 8089 to avoid any local port collisions
    settings = Settings(
        DATABASE_URL=db_url,
        SOUL_PATH=soul_file,
        DASHBOARD_ENABLED=True,
        DASHBOARD_HOST="127.0.0.1",
        DASHBOARD_PORT=8089,
    )

    control_mgr = ControlManager(settings, None)
    sender_mock = AsyncMock()

    server = WebDashboardServer(
        settings=settings,
        control_manager=control_mgr,
        sender=sender_mock,
    )
    await server.start()

    yield server, settings, control_mgr, sender_mock

    await server.stop()
    await close_db()


@pytest.mark.asyncio
async def test_dashboard_html_served(dashboard_setup):
    server, settings, _, _ = dashboard_setup
    url = f"http://{settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}/"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        assert resp.status_code == 200
        assert "Telegram AI Assistant" in resp.text
        assert "@anonrubot" in resp.text
        assert "@anonim" in resp.text


@pytest.mark.asyncio
async def test_api_chats_endpoint(dashboard_setup):
    server, settings, _, _ = dashboard_setup
    url = f"http://{settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}/api/chats"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "bots" in data
        assert "anonrubot" in data["bots"]
        assert "anonim" in data["bots"]


@pytest.mark.asyncio
async def test_api_action_pause_resume(dashboard_setup):
    server, settings, control_mgr, _ = dashboard_setup
    url = f"http://{settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}/api/action"

    assert not control_mgr.is_paused

    async with httpx.AsyncClient() as client:
        # Pause
        resp = await client.post(url, json={"command": "/pause"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert control_mgr.is_paused is True

        # Resume
        resp = await client.post(url, json={"command": "/resume"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert control_mgr.is_paused is False


@pytest.mark.asyncio
async def test_api_action_send_bot_command(dashboard_setup):
    server, settings, _, sender_mock = dashboard_setup
    url = f"http://{settings.DASHBOARD_HOST}:{settings.DASHBOARD_PORT}/api/action"

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={"bot": "anonrubot", "command": "/search"})
        assert resp.status_code == 200
        sender_mock.send_text.assert_called_with("anonrubot", "/search")
