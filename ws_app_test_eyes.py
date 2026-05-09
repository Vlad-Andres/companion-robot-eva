import asyncio
import itertools
from typing import Optional

import websockets


async def _send(websocket, message: str) -> None:
    print(f"TX -> {websocket.remote_address}: {message!r}")
    await websocket.send(message)


async def _ticker(websocket) -> None:
    commands = itertools.cycle(
        [
            "DO turn_left",
            "DO turn_right",
            "DO move_forward",
            "DO move_back",
            "DO stop",
            "DO come_here",
        ]
    )
    speech = itertools.cycle(
        [
            "Hello from backend.",
            "I am processing your request.",
            "This is a test reply.",
        ]
    )

    while True:
        await asyncio.sleep(5)
        await _send(websocket, next(commands))
        await asyncio.sleep(5)
        await _send(websocket, next(speech))


async def handle_ws(websocket, _path: Optional[str] = None) -> None:
    ticker_task = asyncio.create_task(_ticker(websocket))
    try:
        async for _msg in websocket:
            pass
    finally:
        ticker_task.cancel()


async def main() -> None:
    server = await websockets.serve(handle_ws, "0.0.0.0", 8002)
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
