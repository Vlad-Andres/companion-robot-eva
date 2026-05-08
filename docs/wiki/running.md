## Running The Robot

### Minimal Run

From the repo root:

```bash
python main.py
```

The entrypoint intentionally stays thin and delegates wiring and lifecycle to [runtime.py](file:///workspace/runtime.py).

### Logging

You can set verbosity via CLI:

```bash
python main.py --log-level DEBUG
```

Logging is configured by [configure_logging](file:///workspace/utils/logger.py#L18-L39).

### What Works Today vs What Is Still Stubbed

The architecture runs, but hardware integrations are still stubs:

- Camera capture: [CameraSensor](file:///workspace/sensors/camera_sensor.py#L30-L136) (stubbed `_capture_frame`)
- Microphone capture: [MicrophoneSensor](file:///workspace/sensors/microphone_sensor.py#L29-L146) (stubbed `_record_chunk`)
- TTS output: [SpeakHandler](file:///workspace/actions/speak_handler.py#L18-L62) (stubbed)

The local-API calling stubs are wired for:

- Vision API: [VisionClient](file:///workspace/perception/vision_client.py)
- Speech-to-text API: [SpeechClient](file:///workspace/perception/speech_client.py)
- Decision/LLM API: [DecisionEngine](file:///workspace/decision/decision_engine.py)

