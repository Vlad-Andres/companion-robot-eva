import asyncio
import numpy as np
import pyaudio
from config import RobotConfig
from core.event_bus import Event, EventBus
from sensors.microphone_sensor import MicrophoneSensor
import math
import struct

def get_rms(data):
    if not data: return 0
    count = len(data) / 2
    format = "%dh" % (count)
    shorts = struct.unpack(format, data)
    sum_squares = 0.0
    for sample in shorts:
        n = sample / 32768.0
        sum_squares += n * n
    return math.sqrt(sum_squares / count) * 32768

async def monitor_audio():
    bus = EventBus()
    cfg = RobotConfig()
    # Set shorter chunks for faster feedback during testing
    cfg.microphone.chunk_duration_seconds = 1.0
    
    mic = MicrophoneSensor(bus, cfg.microphone)
    
    print("--- Audio Detection Test ---")
    print(f"Sampling Rate: {cfg.microphone.sample_rate}")
    print(f"Channels: {cfg.microphone.channels} (WM8960)")
    print("Listening for 30 seconds... Speak into the mic!")
    print("-" * 30)

    async def on_audio(event: Event):
        chunk = event.data
        rms = get_rms(chunk)
        status = "VOICE" if rms > 200 else "SILENCE"
        bar = "#" * int(rms / 50)
        print(f"RMS: {rms:5.1f} | {status:7} | {bar}")

    bus.subscribe("sensor.audio", on_audio)
    
    try:
        await mic.start()
        await asyncio.sleep(30)
    finally:
        await mic.stop()
        print("-" * 30)
        print("Test finished.")

if __name__ == "__main__":
    try:
        asyncio.run(monitor_audio())
    except Exception as e:
        print(f"Error: {e}")
        print("\nPossible fixes:")
        print("1. Ensure WM8960 drivers are installed.")
        print("2. Run: sudo apt-get install libportaudio2")
        print("3. Check alsamixer settings (Capture/Mic gain).")
