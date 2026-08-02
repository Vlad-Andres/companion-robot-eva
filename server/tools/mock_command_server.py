"""
mock_command_server.py — Fake server for exercising the robot on its own.

Speaks the real eva/1 protocol (see server/protocol.py) so the robot's normal
message handling is what gets tested. Cycles through movement commands and
reply text so the eyes and command path visibly react.

Run with: make mock
"""

from __future__ import annotations

import asyncio
import itertools
import sys
from pathlib import Path
from typing import Optional

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions import MOVE_COMMANDS  # noqa: E402
from protocol import (  # noqa: E402
    base_envelope,
    command_message,
    dumps_message,
    new_id,
    speech_start_message,
    status_message,
)

SESSION_ID = "s_mock"


async def _send(websocket, message: dict) -> None:
    text = dumps_message(message)
    print(f"TX -> {websocket.remote_address}: {text}")
    await websocket.send(text)


async def _ticker(websocket) -> None:
    movements = itertools.cycle(MOVE_COMMANDS)
    replies = itertools.cycle(
        [
            "Hello from the mock server.",
            "I am processing your request.",
            "This is a test reply.",
        ]
    )

    while True:
        await asyncio.sleep(5)
        await _send(
            websocket,
            command_message(
                command_id=new_id("command"),
                name="move_base",
                args={"command": next(movements)},
                session_id=SESSION_ID,
            ),
        )

        await asyncio.sleep(5)
        await _send(
            websocket,
            speech_start_message(speech_id=new_id("speech"), text=next(replies), session_id=SESSION_ID),
        )


async def handle_ws(websocket, _path: Optional[str] = None) -> None:
    await _send(websocket, base_envelope("hello", session_id=SESSION_ID))
    await _send(websocket, status_message(state="ready", session_id=SESSION_ID))

    ticker_task = asyncio.create_task(_ticker(websocket))
    try:
        async for _message in websocket:
            pass
    finally:
        ticker_task.cancel()


async def main() -> None:
    server = await websockets.serve(handle_ws, "0.0.0.0", 8002)
    print("Mock server listening on ws://0.0.0.0:8002 (eva/1)")
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
