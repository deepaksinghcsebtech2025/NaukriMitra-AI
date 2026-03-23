"""WebSocket handler for Jarvis chat."""

from __future__ import annotations

from fastapi import WebSocket, WebSocketDisconnect

from core.logger import logger
from jarvis.commands import dispatch, parse_command


async def handle_ws_jarvis(websocket: WebSocket) -> None:
    """Accept client, echo intents, and stream structured replies."""

    await websocket.accept()
    await websocket.send_json(
        {
            "type": "connected",
            "msg": "Jarvis online. Try: stats, ATS score for [company], interview prep, LinkedIn optimize, resume A/B.",
        }
    )
    while True:
        try:
            data = await websocket.receive_json()
            user_msg = (data.get("message") or "").strip()
            if not user_msg:
                continue
            await websocket.send_json({"type": "thinking", "msg": "Analyzing..."})
            intent = await parse_command(user_msg)
            result = await dispatch(intent)
            await websocket.send_json(
                {
                    "type": "reply",
                    "intent": intent.get("intent"),
                    "msg": intent.get("reply", result),
                    "data": result,
                }
            )
        except WebSocketDisconnect:
            break
        except Exception as exc:
            try:
                await websocket.send_json({"type": "error", "msg": str(exc)})
            except Exception as send_exc:
                logger.debug("jarvis ws send failed: {}", send_exc)
                break
