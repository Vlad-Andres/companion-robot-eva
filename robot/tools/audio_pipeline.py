"""
audio_pipeline.py — Simplified runtime to test only the audio capture and speech-to-text API pipeline.

This script:
1. Initializes the EventBus.
2. Starts the MicrophoneSensor (WM8960).
3. Starts the SpeechClient (connects to the server WebSocket).
4. Prints the transcripts in real-time.

Usage:
    python audio_pipeline.py
"""

import asyncio
import sys
from config import RobotConfig
from core.event_bus import Event, EventBus
from sensors.microphone_sensor import MicrophoneSensor
from perception.speech_client import SpeechClient
from utils.logger import configure_logging, get_logger

async def run_pipeline():
    # 1. Setup minimal infrastructure
    configure_logging(level="DEBUG")
    log = get_logger("audio_pipeline_test")
    
    bus = EventBus()
    cfg = RobotConfig()
    
    # Ensure you've updated the IP in config.py or override it here:
    # cfg.speech_api.base_url = "http://YOUR_COMPUTER_IP:8002"
    
    log.info("=" * 60)
    log.info("Simplified Audio -> speech-to-text pipeline Test")
    log.info(f"Target API: {cfg.speech_api.base_url}{cfg.speech_api.endpoint}")
    log.info("=" * 60)

    # 2. Initialize only the necessary components
    mic = MicrophoneSensor(bus, cfg.microphone)
    speech_client = SpeechClient(bus, cfg.speech_api)

    # 3. Subscribe to the final result to print it
    async def on_transcript(event: Event):
        print("\n" + "!" * 40)
        print(f"TRANSCRIPTION RECEIVED: {event.data}")
        print("!" * 40 + "\n")

    bus.subscribe("perception.transcript", on_transcript)

    # 4. Start services
    try:
        await speech_client.start()
        await mic.start()
        
        log.info("Pipeline active. Speak into the mic and watch the logs...")
        
        # Keep running until Ctrl+C
        while True:
            await asyncio.sleep(1)
            
    except asyncio.CancelledError:
        pass
    except Exception as e:
        log.error(f"Pipeline error: {e}")
    finally:
        log.info("Shutting down...")
        await mic.stop()
        await speech_client.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        sys.exit(0)
