"""
range_check.py — Is the US-100 talking, and does it agree with a tape measure?

Prints a live distance reading and marks the two thresholds the obstacle
reflex uses, so you can walk a hand towards it and see exactly where Eva will
refuse to drive forward.

    cd robot && .venv/bin/python tools/range_check.py

Nothing printed at all means the sensor is not answering. In order of how
often it is the cause:

  1. The serial port is still the login console. Free it with
     `sudo raspi-config nonint do_serial_hw 0` and
     `sudo raspi-config nonint do_serial_cons 1`, then reboot.
  2. TX and RX are not crossed — the sensor's TX goes to the Pi's RX.
  3. The sensor is a GPIO-trigger US-100, not the UART one. The mode is set by
     a jumper on the back of the board.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import RobotConfig  # noqa: E402
from core.event_bus import Event, EventBus  # noqa: E402
from sensors.range_sensor import RangeSensor  # noqa: E402


async def main() -> None:
    config = RobotConfig()
    bus = EventBus()

    stop_mm = config.range_sensor.stop_distance_mm
    clear_mm = config.range_sensor.clear_distance_mm

    async def on_range(event: Event) -> None:
        distance = int(event.data)
        if distance < stop_mm:
            state = "BLOCKED — forward is held here"
        elif distance < clear_mm:
            state = "hysteresis band"
        else:
            state = "clear"
        print(f"{distance:5d} mm   {state}")

    bus.subscribe("sensor.range", on_range)

    sensor = RangeSensor(bus, config.range_sensor)
    await sensor.start()
    if not sensor.available:
        print(f"No sensor on {config.range_sensor.port}. See the notes at the top of this file.")
        return

    print(f"Reading {config.range_sensor.port}. Ctrl+C to stop.\n")
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        await sensor.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
