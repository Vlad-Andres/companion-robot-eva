# Wiring

What the code expects: **Raspberry Pi 4**, **WM8960 Audio HAT** (mic + speaker), **SSD1305 OLED 128×32** on I2C.

## 1. WM8960 Audio HAT

Plugs straight onto all 40 pins — no wiring. It uses these, so don't reuse them:

| Signal | GPIO | Pin |
|---|---|---|
| I2C SDA | 2 | 3 |
| I2C SCL | 3 | 5 |
| I2S BCLK | 18 | 12 |
| I2S LRCLK | 19 | 35 |
| I2S ADC (mic) | 20 | 38 |
| I2S DAC (speaker) | 21 | 40 |
| Button | 17 | 11 |

Speaker goes to the screw terminals (4–8 Ω). Microphones are onboard — nothing to connect.

Its driver is not in the kernel, so install it once:

```bash
git clone https://github.com/waveshareteam/WM8960-Audio-HAT && cd WM8960-Audio-HAT && sudo ./install.sh && sudo reboot
```

## 2. OLED eyes

Four wires. The HAT passes the header through on top — use those same pins.

| OLED | Pi pin | What |
|---|---|---|
| VCC | 1 | 3.3 V (**not** 5 V) |
| GND | 9 | Ground |
| SDA | 3 | GPIO 2 |
| SCL | 5 | GPIO 3 |

It shares the I2C bus with the HAT. No conflict: HAT is at address `0x1a`, OLED at `0x3c`.

## 3. Enable I2C and check

```bash
sudo raspi-config nonint do_i2c 0 && sudo i2cdetect -y 1
```

Both `1a` and `3c` should appear. If `3c` is missing, check the OLED's 4 wires. If `1a` is missing, the HAT isn't seated properly.

## 4. Test each part

```bash
cd robot && .venv/bin/python tools/oled_check.py
```

Text on the screen means the display works.

```bash
arecord -d 3 -f S16_LE -r 16000 -c 1 /tmp/t.wav && aplay /tmp/t.wav
```

Records 3 seconds and plays it back — proves mic and speaker.

## Notes

- Power the Pi from a real **5 V / 3 A USB-C** supply. The HAT plus WiFi browns out weak chargers, which looks like random crashes.
- Volume defaults to 5% in `config.py`. Raise `volume_percent` to ~50 or you won't hear anything.
- Camera and motors aren't implemented yet — nothing to connect.
