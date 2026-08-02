## Further Development Roadmap

This repository is a working architecture scaffold. The high-impact work now is to implement real hardware I/O and stabilize the “local API contracts”.

### Priority 1 — Make The Robot See And Hear

- Implement camera capture in [CameraSensor](file:///workspace/sensors/camera_sensor.py#L56-L136)
  - Choose backend: `picamera2` (recommended on Pi) or `opencv-python`.
  - Decide output: JPEG bytes (recommended) for easiest HTTP transport.
- Implement microphone capture in [MicrophoneSensor](file:///workspace/sensors/microphone_sensor.py#L59-L146)
  - Choose backend: `sounddevice` or `pyaudio`.
  - Output PCM16LE, 16 kHz, mono (matches current defaults).

### Priority 2 — Speech Gating (Don’t Spam STT)

Recommended architecture: “always listening locally” but only send audio when speech is detected.

Implementation steps:

- Add a simple gate before publishing `sensor.audio` chunks (energy threshold / VAD).
- Add pre-roll (buffer the last ~300–800 ms) so you don’t clip the start of words.
- Optional: add a wake word model later; keep it on-device.

### Priority 3 — Define And Freeze Local API Contracts

Decide the exact request/response formats so the robot runtime and API servers can evolve independently.

- STT: choose PCM16LE vs WAV; define sample rate, channels, endianness.
- Vision: define image encoding (JPEG/PNG), max payload size, and object schema.
- Decision: define the allowed action set and add strict validation in the API server.

Docs: [Local API Contracts](local-apis.md)

### Priority 4 — Implement Output (TTS + Eyes)

- Implement TTS in [SpeakHandler](file:///workspace/actions/speak_handler.py#L18-L62)
  - Choose: local engine (piper/espeak) or a local TTS API.
- Extend expression/animation usage in [eye_expression_handler.py](file:///workspace/actions/eye_expression_handler.py)
  - Add more expressive states tied to conversation or confidence.

### Priority 5 — Memory Integration

The memory layer exists but is not yet used by the decision payload:

- Store events (speech, objects, actions) into [MemoryStore](file:///workspace/memory/memory_store.py#L47-L180)
- Pull recent/relevant memories into [ContextBuilder](file:///workspace/decision/context_builder.py#L95-L129)
- Later: replace keyword search with vector retrieval

### Priority 6 — Reliability And Testing

- Add a small contract-test suite for each local API (HTTP status codes, JSON schema, timeout behavior).
- Add “degraded mode” behavior: if STT/LLM is down, blink/speak fallback prompts.
- Add load shedding: drop frames/audio when APIs are saturated (similar to VisionClient’s semaphore behavior).

