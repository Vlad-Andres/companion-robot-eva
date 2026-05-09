"""
display/eye_controller.py — OLED eye animation controller.

Migrated from eyes_animation.py and adapted for use as a reusable module.
The __main__ block has been removed; EyeController is now purely importable.

Used by:
  - actions/eye_expression_handler.py   (via action dispatch)
  - runtime.py                          (startup animation)

Hardware: SSD1305 128×32 OLED display via I2C.
"""

# Original source: https://github.com/intellar/oled_eye_display/blob/main/python/example.py

import enum
import random
import time

from utils.logger import get_logger

log = get_logger(__name__)


class Animation(enum.IntEnum):
    """Named animations available on the eye display."""
    WAKEUP = 0
    RESET = 1
    MOVE_RIGHT_BIG = 2
    MOVE_LEFT_BIG = 3
    BLINK_LONG = 4
    BLINK_SHORT = 5
    HAPPY = 6
    SLEEP = 7
    SACCADE_RANDOM = 8
    CURIOUS = 9
    CONFUSED = 10
    THINKING = 11
    IMPATIENT = 12


class EyeController:
    """
    Controls the OLED eye animation display.

    Manages the luma.oled device and provides named animation methods.
    All methods are synchronous (blocking); use run_in_executor() when
    calling from async code.

    Attributes:
        device: The luma.oled display device.
        w:      Eye width in pixels.
        h:      Eye height in pixels.
        space:  Gap between the two eyes in pixels.
        rad:    Corner radius for rounded rectangles.
        lx:     X centre of the left eye.
        rx:     X centre of the right eye.
    """

    def __init__(self, port: int = 1, addr: int = 0x3C) -> None:
        """
        Initialize the OLED display and eye geometry.

        Args:
            port: I2C bus port number.
            addr: I2C device address.

        Raises:
            RuntimeError: If the display cannot be initialized.
        """
        try:
            from luma.core.interface.serial import i2c
            from luma.oled.device import ssd1305
            serial = i2c(port=port, address=addr)
            self.device = ssd1305(serial, width=128, height=32)
        except Exception as exc:
            raise RuntimeError(f"Failed to initialize OLED display: {exc}") from exc

        # Eye geometry
        self.w: int = 38
        self.h: int = 20
        self.space: int = 16
        self.rad: int = 8
        self.lx: int = 64 - (self.space // 2) - (self.w // 2)
        self.rx: int = 64 + (self.space // 2) + (self.w // 2)

        log.debug("EyeController initialized (lx=%d, rx=%d)", self.lx, self.rx)

    # ------------------------------------------------------------------
    # Core draw primitive
    # ------------------------------------------------------------------

    def draw(self, lx=None, rx=None, h=None, mode=None, brow=None) -> None:
        """
        Render the eyes to the OLED display.

        Args:
            lx:   X centre of left eye (defaults to self.lx).
            rx:   X centre of right eye (defaults to self.rx).
            h:    Eye height in pixels (defaults to self.h).
            mode: Rendering mode — None (normal), "happy", or "sleep".
            brow: Brow mode — None, "raised", or "furrowed".
        """
        from luma.core.render import canvas
        lx = lx if lx is not None else self.lx
        rx = rx if rx is not None else self.rx
        h = h if h is not None else self.h

        with canvas(self.device) as d:
            for x in [lx, rx]:
                box = [x - self.w // 2, 16 - h // 2, x + self.w // 2, 16 + h // 2]
                if mode == "happy":
                    d.arc(box, 180, 0, fill="white", width=4)
                elif mode == "sleep":
                    d.rectangle([box[0], 15, box[2], 17], fill="white")
                else:
                    d.rounded_rectangle(box, radius=min(h // 2, self.rad), fill="white")

            if brow == "raised":
                for x in [lx, rx]:
                    left = x - (self.w // 2) + 3
                    right = x + (self.w // 2) - 3
                    y = 0
                    d.line([(left, y), (x, y), (right, y)], fill="white", width=1)
            elif brow == "furrowed":
                for x in [lx, rx]:
                    left = x - (self.w // 2) + 3
                    right = x + (self.w // 2) - 3
                    y = 4
                    d.line([(left, y), (x, y - 4), (right, y)], fill="white", width=1)


    def clear(self) -> None:
        """Clear the display (blank screen)."""
        from luma.core.render import canvas
        with canvas(self.device) as _:
            pass

    # ------------------------------------------------------------------
    # Named animations
    # ------------------------------------------------------------------

    def wakeup(self) -> None:
        """Animate eyes opening from a thin slit to full height."""
        for h in range(2, self.h + 1, 4):
            self.draw(h=h)
            time.sleep(0.05)

    def reset(self) -> None:
        """Render eyes in the default neutral position."""
        self.draw()

    def move_right_big(self) -> None:
        """Shift both eyes 16 pixels to the right."""
        self.draw(lx=self.lx + 16, rx=self.rx + 16)

    def move_left_big(self) -> None:
        """Shift both eyes 16 pixels to the left."""
        self.draw(lx=self.lx - 16, rx=self.rx - 16)

    def blink_long(self) -> None:
        """Slow blink: squint briefly then reopen."""
        self.draw(h=2)
        time.sleep(0.4)
        self.reset()

    def blink_short(self) -> None:
        """Quick blink."""
        self.draw(h=2)
        time.sleep(0.1)
        self.reset()

    def happy(self) -> None:
        """Render upward arc eyes (smile shape)."""
        self.draw(mode="happy", brow="raised")

    def sleep(self) -> None:
        """Render thin horizontal line eyes (sleeping)."""
        self.draw(mode="sleep")

    def saccade_random(self) -> None:
        """Shift eyes by a random horizontal offset (−16 to +16 px)."""
        offset = random.randint(-16, 16)
        self.draw(lx=self.lx + offset, rx=self.rx + offset)

    def curious(self) -> None:
        """Curious look: raised brows plus a small saccade."""
        self.draw(brow="raised")
        time.sleep(0.15)
        offset = random.randint(-8, 8)
        self.draw(lx=self.lx + offset, rx=self.rx + offset, brow="raised")

    def confused(self) -> None:
        """Confused look: furrowed brows plus a couple small saccades."""
        self.draw(brow="furrowed")
        time.sleep(0.15)
        for _ in range(2):
            offset = random.randint(-10, 10)
            self.draw(lx=self.lx + offset, rx=self.rx + offset, brow="furrowed")
            time.sleep(0.18)
        self.reset()

    def thinking(self) -> None:
        """Thinking loop: look left/right with furrowed brows then saccade."""
        self.draw(brow="furrowed")
        time.sleep(0.2)
        self.draw(lx=self.lx - 12, rx=self.rx - 12, brow="furrowed")
        time.sleep(0.35)
        self.draw(lx=self.lx + 12, rx=self.rx + 12, brow="furrowed")
        time.sleep(0.35)
        self.saccade_random()
        time.sleep(0.25)
        self.reset()

    def impatient(self) -> None:
        """Impatient look: raised brows and repeated quick saccades."""
        self.draw(brow="raised")
        for _ in range(3):
            offset = random.randint(-12, 12)
            self.draw(lx=self.lx + offset, rx=self.rx + offset, brow="raised")
            time.sleep(0.12)
        self.reset()

    # ------------------------------------------------------------------
    # Generic play interface
    # ------------------------------------------------------------------

    def play(self, anim: Animation) -> None:
        """
        Play a named animation by Animation enum member.

        Looks up and calls the corresponding method by lowercased enum name.

        Args:
            anim: An Animation enum member.
        """
        method_name = anim.name.lower()
        method = getattr(self, method_name, None)
        if method is not None:
            log.debug("Playing animation: %s", anim.name)
            method()
        else:
            log.warning("No method found for animation: %s", anim.name)
