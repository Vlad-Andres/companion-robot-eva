# Copyrights https://github.com/intellar/oled_eye_display/blob/main/python/example.py
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1305
from luma.core.render import canvas
import time, enum, random, sys

class Animation(enum.IntEnum):
    WAKEUP = 0
    RESET = 1
    MOVE_RIGHT_BIG = 2
    MOVE_LEFT_BIG = 3
    BLINK_LONG = 4
    BLINK_SHORT = 5
    HAPPY = 6
    SLEEP = 7
    SACCADE_RANDOM = 8

class EyeController:
    def __init__(self, port=1, addr=0x3C):
        try:
            self.device = ssd1305(i2c(port=port, address=addr), width=128, height=32)
        except Exception as e:
            print(f"Error: {e}"); sys.exit(1)
        # Eye configuration
        self.w, self.h, self.space, self.rad = 38, 24, 16, 8
        self.lx = 64 - (self.space // 2) - (self.w // 2)
        self.rx = 64 + (self.space // 2) + (self.w // 2)

    def draw(self, lx=None, rx=None, h=None, mode=None):
        lx, rx, h = lx or self.lx, rx or self.rx, h or self.h
        with canvas(self.device) as d:
            for x in [lx, rx]:
                box = [x - self.w//2, 16 - h//2, x + self.w//2, 16 + h//2]
                if mode == "happy": d.arc(box, 180, 0, fill="white", width=4)
                elif mode == "sleep": d.rectangle([box[0], 15, box[2], 17], fill="white")
                else: d.rounded_rectangle(box, radius=min(h//2, self.rad), fill="white")

    def wakeup(self):
        for h in range(2, self.h + 1, 4): self.draw(h=h); time.sleep(0.05)
    
    def reset(self): self.draw()
    def move_right_big(self): self.draw(lx=self.lx + 16, rx=self.rx + 16)
    def move_left_big(self): self.draw(lx=self.lx - 16, rx=self.rx - 16)
    def blink_long(self): self.draw(h=2); time.sleep(0.4); self.reset()
    def blink_short(self): self.draw(h=2); time.sleep(0.1); self.reset()
    def happy(self): self.draw(mode="happy")
    def sleep(self): self.draw(mode="sleep")
    def saccade_random(self): 
        ox = random.randint(-16, 16)
        self.draw(lx=self.lx + ox, rx=self.rx + ox)

    def play(self, anim):
        func = getattr(self, anim.name.lower(), None)
        if func:
            print(f"Playing: {anim.name}")
            func()

if __name__ == "__main__":
    eyes = EyeController()
    try:
        eyes.play(Animation.WAKEUP)
        for anim in Animation:
            if anim in [Animation.RESET, Animation.WAKEUP]: continue
            eyes.play(anim); time.sleep(1.5)
            eyes.reset(); time.sleep(0.5)
        eyes.play(Animation.SLEEP)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        with canvas(eyes.device) as d: pass # Clear screen
