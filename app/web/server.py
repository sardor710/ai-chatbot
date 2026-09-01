"""Async HTTP server providing a real-time web dashboard for Telegram chats."""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.anonymous.commands import (
    is_bot_connection_notice,
    is_bot_disconnection_notice,
    is_bot_service_notice,
)
from app.config import Settings
from app.control.commands import ControlManager
from app.database.database import get_db_session
from app.database.models import Conversation, ConversationTypeEnum, Message
from app.telegram.sender import TelegramSender

logger = logging.getLogger(__name__)


class WebDashboardServer:
    """Lightweight, zero-dependency async HTTP + SSE server for the live chat screen."""

    def __init__(
        self,
        settings: Settings,
        control_manager: ControlManager,
        sender: TelegramSender | None = None,
    ) -> None:
        self.settings = settings
        self.control_manager = control_manager
        self.sender = sender
        self.server: asyncio.Server | None = None
        self._sse_clients: set[asyncio.Queue] = set()
        self._template_path = Path(__file__).parent / "templates" / "dashboard.html"

    async def start(self) -> None:
        """Start listening for incoming HTTP requests."""
        host = self.settings.DASHBOARD_HOST
        port = self.settings.DASHBOARD_PORT
        try:
            self.server = await asyncio.start_server(
                self._handle_client, host=host, port=port
            )
            logger.info(f"🌐 Web Dashboard live at: http://{host}:{port}")
        except Exception as e:
            logger.error(f"Failed to start Web Dashboard on {host}:{port}: {e}")

    async def stop(self) -> None:
        """Shut down the web dashboard server gracefully."""
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info("Web Dashboard server stopped.")
        # Disconnect any remaining SSE queues
        for q in list(self._sse_clients):
            await q.put(None)
        self._sse_clients.clear()

    def broadcast_update(self, event_type: str = "update", **kwargs: Any) -> None:
        """Push an SSE notification to all active browser windows."""
        payload = {"type": event_type, **kwargs}
        dead_clients = []
        for q in self._sse_clients:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass
            except Exception:
                dead_clients.append(q)
        for q in dead_clients:
            self._sse_clients.discard(q)

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle an incoming HTTP connection."""
        try:
            line = await reader.readline()
            if not line:
                writer.close()
                await writer.wait_closed()
                return

            req_line = line.decode("utf-8", errors="ignore").strip()
            parts = req_line.split(" ")
            if len(parts) < 2:
                writer.close()
                await writer.wait_closed()
                return

            method, path = parts[0].upper(), parts[1]

            # Read headers
            headers = {}
            content_length = 0
            while True:
                header_line = await reader.readline()
                if not header_line or header_line == b"\r\n":
                    break
                header_str = header_line.decode("utf-8", errors="ignore").strip()
                if ":" in header_str:
                    k, v = header_str.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
                    if k.strip().lower() == "content-length":
                        try:
                            content_length = int(v.strip())
                        except ValueError:
                            content_length = 0

            # Route requests
            if method == "GET" and path == "/":
                await self._serve_dashboard_html(writer)
            elif method == "GET" and path == "/api/chats":
                await self._serve_api_chats(writer)
            elif method == "GET" and path == "/api/stream":
                await self._serve_sse_stream(writer)
            elif method == "POST" and path == "/api/action":
                body = b""
                if content_length > 0:
                    body = await reader.readexactly(content_length)
                await self._handle_api_action(writer, body)
            elif method == "OPTIONS":
                await self._send_cors_options(writer)
            else:
                await self._send_response(
                    writer, 404, "Not Found", b"404 Not Found", "text/plain"
                )
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        except Exception as e:
            logger.exception(f"Error handling HTTP request: {e}")
            try:
                err_resp = json.dumps({"error": str(e)}).encode("utf-8")
                await self._send_response(
                    writer, 500, "Internal Server Error", err_resp, "application/json"
                )
            except Exception:
                pass
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _send_response(
        self,
        writer: asyncio.StreamWriter,
        status_code: int,
        status_text: str,
        body: bytes,
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        """Send a standard HTTP response."""
        resp = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n"
            f"Access-Control-Allow-Origin: *\r\n\r\n"
        ).encode("utf-8") + body
        writer.write(resp)
        await writer.drain()

    async def _send_cors_options(self, writer: asyncio.StreamWriter) -> None:
        """Handle pre-flight OPTIONS request."""
        resp = (
            "HTTP/1.1 204 No Content\r\n"
            "Access-Control-Allow-Origin: *\r\n"
            "Access-Control-Allow-Methods: GET, POST, OPTIONS\r\n"
            "Access-Control-Allow-Headers: Content-Type\r\n"
            "Content-Length: 0\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        writer.write(resp)
        await writer.drain()

    async def _serve_dashboard_html(self, writer: asyncio.StreamWriter) -> None:
        """Serve the dashboard single-page HTML application."""
        if self._template_path.exists():
            html_bytes = self._template_path.read_bytes()
        else:
            html_bytes = b"<h1>Dashboard template not found</h1>"
        await self._send_response(
            writer, 200, "OK", html_bytes, "text/html; charset=utf-8"
        )

    async def _serve_sse_stream(self, writer: asyncio.StreamWriter) -> None:
        """Stream real-time server-sent events to browser."""
        headers = (
            "HTTP/1.1 200 OK\r\n"
            "Content-Type: text/event-stream\r\n"
            "Cache-Control: no-cache\r\n"
            "Connection: keep-alive\r\n"
            "Access-Control-Allow-Origin: *\r\n\r\n"
        ).encode("utf-8")
        writer.write(headers)
        await writer.drain()

        client_queue: asyncio.Queue = asyncio.Queue(maxsize=20)
        self._sse_clients.add(client_queue)

        try:
            # Send initial connected greeting
            init_msg = f"data: {json.dumps({'type': 'connected'})}\n\n".encode("utf-8")
            writer.write(init_msg)
            await writer.drain()

            while True:
                try:
                    payload = await asyncio.wait_for(client_queue.get(), timeout=15.0)
                    if payload is None:
                        break
                    line = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode(
                        "utf-8"
                    )
                    writer.write(line)
                    await writer.drain()
                except asyncio.TimeoutError:
                    # Keep-alive heartbeat comment
                    writer.write(b": ping\n\n")
                    await writer.drain()
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._sse_clients.discard(client_queue)

    async def _serve_api_chats(self, writer: asyncio.StreamWriter) -> None:
        """Return structured state and recent messages for both bots."""
        data = {
            "status": {
                "autopilot": self.settings.AUTOPILOT_ENABLED,
                "is_paused": self.control_manager.is_paused,
                "model": self.settings.LLM_MODEL,
            },
            "bots": {
                "anonrubot": {"state": "STOPPED", "messages": []},
                "anonim": {"state": "STOPPED", "messages": []},
            },
        }

        # Target IDs: anonrubot: 660309226, anonim: 8103812978
        bot_targets = {
            "anonrubot": 660309226,
            "anonim": 8103812978,
        }

        async with get_db_session(self.settings.DATABASE_URL) as session:
            for bot_key, chat_id in bot_targets.items():
                # 1. Fetch latest conversation for current state and partner metadata
                stmt_conv = (
                    select(Conversation)
                    .where(
                        Conversation.telegram_chat_id == chat_id,
                        Conversation.type == ConversationTypeEnum.ANONYMOUS_CHAT,
                    )
                    .order_by(Conversation.id.desc())
                    .options(
                        selectinload(Conversation.details),
                    )
                )
                res_conv = await session.execute(stmt_conv)
                conv = res_conv.scalars().first()

                # 2. Fetch the latest 50 messages across this bot chat
                stmt_msgs = (
                    select(Message)
                    .join(Conversation, Message.conversation_id == Conversation.id)
                    .where(
                        Conversation.telegram_chat_id == chat_id,
                        Conversation.type == ConversationTypeEnum.ANONYMOUS_CHAT,
                    )
                    .order_by(Message.id.desc())
                    .limit(50)
                )
                res_msgs = await session.execute(stmt_msgs)
                recent_msgs = list(reversed(res_msgs.scalars().all()))

                msg_list = []
                for m in recent_msgs:
                    time_str = m.timestamp.strftime("%H:%M") if m.timestamp else ""
                    is_system = (
                        m.direction == MessageDirectionEnum.INCOMING
                        and (
                            is_bot_service_notice(m.text)
                            or is_bot_connection_notice(m.text)
                            or is_bot_disconnection_notice(m.text)
                        )
                    )
                    msg_list.append(
                        {
                            "id": m.id,
                            "text": m.text,
                            "direction": m.direction.value,
                            "sender_type": m.sender_type.value,
                            "is_system": is_system,
                            "time": time_str,
                        }
                    )

                details = conv.details if conv else None
                metadata = details.get_metadata() if details else {}
                gender = details.gender if details else None
                age = metadata.get("age") or (details.participant_age if details else None)
                name = metadata.get("name")
                username = metadata.get("telegram_username") or (
                    details.telegram_username if details else None
                )
                state = conv.state.value if conv else "STOPPED"
                conv_id = conv.id if conv else None

                data["bots"][bot_key] = {
                    "state": state,
                    "conversation_id": conv_id,
                    "gender": gender,
                    "age": age,
                    "name": name,
                    "username": username,
                    "messages": msg_list,
                }

        body_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        await self._send_response(
            writer, 200, "OK", body_bytes, "application/json; charset=utf-8"
        )

    async def _handle_api_action(
        self, writer: asyncio.StreamWriter, body: bytes
    ) -> None:
        """Handle actions initiated from the web dashboard UI."""
        try:
            req = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            req = {}

        bot = req.get("bot")
        command = req.get("command")
        action = req.get("action")

        if action == "search_all":
            if self.sender:
                for b in self.settings.get_anonymous_bot_usernames():
                    try:
                        await self.sender.send_text(b, "/search")
                    except Exception as e:
                        logger.warning(f"Dashboard search error for {b}: {e}")

        elif command in ("/pause", "/resume"):
            self.control_manager.is_paused = (command == "/pause")
            logger.info(f"Dashboard toggled pause state: {self.control_manager.is_paused}")

        elif bot and command and self.sender:
            try:
                await self.sender.send_text(bot, command)
                logger.info(f"Dashboard sent command '{command}' to @{bot}")
            except Exception as e:
                logger.warning(f"Dashboard send command error to @{bot}: {e}")

        # Broadcast update to refresh UI
        self.broadcast_update(event_type="update")

        resp_bytes = json.dumps({"ok": True}).encode("utf-8")
        await self._send_response(
            writer, 200, "OK", resp_bytes, "application/json; charset=utf-8"
        )
