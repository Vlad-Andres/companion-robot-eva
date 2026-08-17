# Wiring

What the code expects: **Raspberry Pi 4**, **WM8960 Audio HAT** (mic + speaker), **SSD1305 OLED 128×32** on I2C, and for movement a **TB6612FNG** driving two wheels with a **US-100** looking ahead.

Pin defaults live in `config.py`. Every motor pin was chosen to avoid what the audio HAT claims (GPIO 2, 3, 17, 18, 19, 20, 21) and the UART the range sensor needs (14, 15).

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

## 5. Motors — TB6612FNG

Eight wires to the Pi, plus power and the motors themselves.

| TB6612 | Pi pin | GPIO | What |
|---|---|---|---|
| PWMA | 32 | 12 | Left speed (hardware PWM) |
| AIN1 | 29 | 5 | Left direction |
| AIN2 | 31 | 6 | Left direction |
| PWMB | 33 | 13 | Right speed (hardware PWM) |
| BIN1 | 16 | 23 | Right direction |
| BIN2 | 18 | 24 | Right direction |
| STBY | 22 | 25 | Enable — **low and the chip ignores everything** |
| VCC | 17 | — | 3.3 V, logic side |
| GND | 20 | — | Ground |

Motor power and motors:

| TB6612 | Goes to |
|---|---|
| VM | Battery + (via the buck converter, or straight from the 18650 pack) |
| GND | Battery − — **and** the Pi's ground, or the chip sees no common reference |
| AO1 / AO2 | Left motor |
| BO1 / BO2 | Right motor |

**The one that catches people:** the battery ground and the Pi ground must be joined. Without a common ground the direction pins read as noise and the motors twitch or do nothing.

Two 18650s in series give ~7.4 V, which suits typical yellow TT gearmotors directly on VM. Do **not** run the motors off the Pi's 5 V rail — the current spike on start browns out the Pi and it reboots mid-sentence.

Check it with the wheels off the ground:

```bash
cd robot && .venv/bin/python tools/motor_check.py
```

Forward, backward, left, right in turn. If "forward" spins the robot, one motor is wired backwards — set `invert_left` or `invert_right` in `config.py` rather than resoldering.

## 6. Range sensor — US-100 (UART mode)

Four wires. Set the jumper on the back of the board to **UART**, not trigger/echo.

| US-100 | Pi pin | GPIO |
|---|---|---|
| VCC | 2 | 5 V |
| GND | 6 | Ground |
| Trig/TX | 10 | 15 (RXD) |
| Echo/RX | 8 | 14 (TXD) |

TX and RX cross over: the sensor's TX goes to the Pi's RX.

The serial port is the login console by default, so free it once:

```bash
sudo raspi-config nonint do_serial_hw 0 && sudo raspi-config nonint do_serial_cons 1 && sudo reboot
```

Then watch it read, and walk your hand in to find the thresholds:

```bash
cd robot && .venv/bin/python tools/range_check.py
```

The sensor is optional. Without it Eva still moves; she just has no reflex to stop her driving into things, and says so at startup.

## Notes

- Power the Pi from a real **5 V / 3 A USB-C** supply. The HAT plus WiFi browns out weak chargers, which looks like random crashes.
- Volume defaults to 5% in `config.py`. Raise `volume_percent` to ~50 or you won't hear anything.
- The HAT's button (GPIO 17) is the emergency stop. It works when nothing else does — worth knowing before the first drive, because while Eva is speaking her microphone is muted and a spoken "stop" has nowhere to land.
- Camera isn't implemented yet — nothing to connect.
