from luma.core.interface.serial import i2c
from luma.oled.device import ssd1305
from luma.core.render import canvas
from PIL import ImageFont
import time

serial = i2c(port=1, address=0x3C)
device = ssd1305(serial, width=128, height=32)

with canvas(device) as draw:
    draw.text((0, 0), "Hello Robot!", fill="white")
    draw.text((0, 16), "I2C works!", fill="white")
    draw.text((86, 0), "Hello !", fill="white")

time.sleep(10)