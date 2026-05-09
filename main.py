from __future__ import annotations

import uvicorn


def run() -> None:
    uvicorn.run("robot_backend.asgi:app", host="0.0.0.0", port=8002, log_level="info")


if __name__ == "__main__":
    run()
