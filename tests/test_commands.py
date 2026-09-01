"""Unit tests for owner command authorization and global control operations."""

from unittest.mock import AsyncMock

import pytest

from app.ai.soul_loader import SoulLoader
from app.config import Settings
from app.control.commands import ControlManager


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.log_control_event = AsyncMock()
    return repo


@pytest.fixture
def test_setup(tmp_path):
    soul_file = tmp_path / "soul.md"
    soul_file.write_text("Test Soul Content", encoding="utf-8")
    settings = Settings(
        OWNER_USER_ID=12345678,
        OWNER_USERNAME="@mlsv06",
        SOUL_PATH=soul_file,
        AUTOPILOT_ENABLED=False,
    )
    soul_loader = SoulLoader(soul_file)
    control = ControlManager(settings=settings, soul_loader=soul_loader)
    return control, settings, soul_loader


@pytest.mark.asyncio
async def test_owner_authorization(test_setup, mock_repo):
    control, _settings, _ = test_setup

    # Authorized by ID
    assert control.is_owner(12345678, "any_user") is True
    # Authorized by Username
    assert control.is_owner(999999, "mlsv06") is True
    assert control.is_owner(999999, "@mlsv06") is True

    # Unauthorized
    assert control.is_owner(999999, "stranger") is False


@pytest.mark.asyncio
async def test_unauthorized_command_rejected(test_setup, mock_repo):
    control, settings, _ = test_setup

    handled, reply = await control.handle_control_command(
        command_text="/autopilot_on",
        user_id=999999,
        username="hacker",
        repo=mock_repo,
    )
    assert handled is True
    assert "Access denied" in reply
    assert settings.AUTOPILOT_ENABLED is False


@pytest.mark.asyncio
async def test_autopilot_toggle(test_setup, mock_repo):
    control, settings, _ = test_setup

    # Turn on
    handled, reply = await control.handle_control_command(
        command_text="/autopilot_on",
        user_id=12345678,
        username="mlsv06",
        repo=mock_repo,
    )
    assert handled is True
    assert "ENABLED" in reply
    assert settings.AUTOPILOT_ENABLED is True

    # Turn off
    handled, reply = await control.handle_control_command(
        command_text="/autopilot_off",
        user_id=12345678,
        username="mlsv06",
        repo=mock_repo,
    )
    assert handled is True
    assert "DISABLED" in reply
    assert settings.AUTOPILOT_ENABLED is False


@pytest.mark.asyncio
async def test_pause_resume(test_setup, mock_repo):
    control, _settings, _ = test_setup

    # Pause
    handled, _reply = await control.handle_control_command(
        command_text="/pause",
        user_id=12345678,
        username="mlsv06",
        repo=mock_repo,
    )
    assert handled is True
    assert control.is_paused is True

    # Resume
    handled, _reply = await control.handle_control_command(
        command_text="/resume",
        user_id=12345678,
        username="mlsv06",
        repo=mock_repo,
    )
    assert handled is True
    assert control.is_paused is False


@pytest.mark.asyncio
async def test_status_command(test_setup, mock_repo):
    control, _settings, _ = test_setup

    handled, reply = await control.handle_control_command(
        command_text="/status",
        user_id=12345678,
        username="mlsv06",
        repo=mock_repo,
    )
    assert handled is True
    assert "Telegram AI Status" in reply
    assert "Autopilot" in reply
