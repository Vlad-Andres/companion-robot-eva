"""
test_audio_pipeline.py — Simplified runtime to test only the audio capture and STT API pipeline.

This script:
1. Initializes the EventBus and ContextManager.
2. Starts the MicrophoneSensor (WM8960).
3. Starts the SpeechClient (connects to your local Flask API).
4. Prints the results of the transcription in real-time.

Usage:
    python test_audio_pipeline.py
"""

import asyncio
import sys
from config import RobotConfig
from core.event_bus import Event, EventBus
from core.context_manager import ContextManager
from sensors.microphone_sensor import MicrophoneSensor
from perception.speech_client import SpeechClient
from utils.logger import configure_logging, get_logger

async def run_pipeline():
    # 1. Setup minimal infrastructure
    configure_logging(level="DEBUG")
    log = get_logger("audio_pipeline_test")
    
    bus = EventBus()
    ctx = ContextManager()
    cfg = RobotConfig()
    
    # Ensure you've updated the IP in config.py or override it here:
    # cfg.speech_api.base_url = "http://YOUR_COMPUTER_IP:8002"
    
    log.info("=" * 60)
    log.info("Simplified Audio -> STT Pipeline Test")
    log.info(f"Target API: {cfg.speech_api.base_url}{cfg.speech_api.endpoint}")
    log.info("=" * 60)

    # 2. Initialize only the necessary components
    mic = MicrophoneSensor(bus, cfg.microphone)
    stt = SpeechClient(bus, ctx, cfg.speech_api)

    # 3. Subscribe to the final result to print it
    async def on_speech(event: Event):
        print("\n" + "!" * 40)
        print(f"TRANSCRIPTION RECEIVED: {event.data}")
        print("!" * 40 + "\n")

    bus.subscribe("perception.speech", on_speech)

    # 4. Start services
    try:
        await stt.start()
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
        await stt.stop()

if __name__ == "__main__":
    try:
        asyncio.run(run_pipeline())
    except KeyboardInterrupt:
        sys.exit(0)
