"""WebSocket endpoints for logs and Jarvis."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.cache import get_cache_client
from core.logger import logger
from jarvis.assistant import handle_ws_jarvis

router = APIRouter()


@router.websocket("/ws/logs")
async def ws_logs(websocket: WebSocket) -> None:
    """Push the latest log tail every two seconds."""

    await websocket.accept()
    cache = get_cache_client()
    try:
        while True:
            logs = await cache.get_logs(30)
            await websocket.send_json({"type": "logs", "data": logs})
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("ws_logs closed: {}", exc)


@router.websocket("/ws/jarvis")
async def ws_jarvis(websocket: WebSocket) -> None:
    """Jarvis command channel."""

    await handle_ws_jarvis(websocket)
