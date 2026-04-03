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

    if not cache.is_configured:
        try:
            await websocket.send_json({
                "type": "logs",
                "data": ["[info] Redis not configured — live log tail disabled. "
                         "Set UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN in .env to enable."],
            })
        except Exception:
            return

    try:
        while True:
            try:
                logs = await cache.get_logs(30)
                if logs:
                    await websocket.send_json({"type": "logs", "data": logs})
            except WebSocketDisconnect:
                break
            except asyncio.CancelledError:
                # Server is shutting down — exit cleanly without logging noise
                break
            except Exception as exc:
                logger.debug("ws_logs send error: {}", exc)
                break

            try:
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break

    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.debug("ws_logs closed: {}", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/jarvis")
async def ws_jarvis(websocket: WebSocket) -> None:
    """Jarvis command channel."""

    try:
        await handle_ws_jarvis(websocket)
    except asyncio.CancelledError:
        pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("ws_jarvis closed: {}", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
