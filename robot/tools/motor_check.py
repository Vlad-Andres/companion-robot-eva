"""
motor_check.py — Bring-up for the TB6612 and the two wheels.

Run this before anything else after wiring the base. It drives each movement
in turn with a pause between, so you can see which wheel does what and catch
the two mistakes everyone makes: a motor wired backwards, and the left and
right pairs swapped.

Put the robot on a box with its wheels off the ground first.

    cd robot && .venv/bin/python tools/motor_check.py
    cd robot && .venv/bin/python tools/motor_check.py --seconds 3

What you should see, in order:

    forward       both wheels turning the same way, forwards
    backward      both wheels turning the same way, backwards
    turn_left     left wheel back, right wheel forward
    turn_right    left wheel forward, right wheel back

If forward spins the robot instead, one motor is reversed — set invert_left or
invert_right in config.py rather than resoldering. If left and right are
swapped, swap the pin numbers.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from actions.move_base_handler import MoveBaseHandler  # noqa: E402
from config import RobotConfig  # noqa: E402
from motion.base_driver import build_base_driver  # noqa: E402

SEQUENCE = ("forward", "backward", "turn_left", "turn_right")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Drive each movement in turn.")
    parser.add_argument("--seconds", type=float, default=1.5, help="how long to hold each movement")
    parser.add_argument("--speed", type=float, help="override drive and turn speed (0-1)")
    args = parser.parse_args()

    config = RobotConfig()
    if args.speed is not None:
        config.base.drive_speed = args.speed
        config.base.turn_speed = args.speed

    driver = build_base_driver(config.base)
    if not driver.available:
        print("No base driver — check base.enabled in config.py and the wiring.")
        return

    handler = MoveBaseHandler(driver=driver, config=config.base)
    print("Wheels off the ground? Starting in 3s. Ctrl+C stops.\n")
    await asyncio.sleep(3)

    try:
        for movement in SEQUENCE:
            print(f"  {movement}")
            await handler.execute(movement)
            await asyncio.sleep(args.seconds)
            await handler.execute("stop")
            await asyncio.sleep(0.7)
    finally:
        # Whatever happened, including Ctrl+C, the wheels stop.
        await handler.stop()
        driver.close()
        print("\nDone — motors released.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
