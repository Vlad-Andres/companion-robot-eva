## Subsystems

### Runtime (Composition Root)

[RobotRuntime](file:///workspace/runtime.py#L36-L309) is the “composition root” that wires everything together:

- creates `EventBus`, `ContextManager`, `MemoryStore`, `ServiceRegistry`, `ActionDispatcher`
- registers sensors and perception clients as services
- registers action handlers with the dispatcher
- subscribes the dispatcher to `decision.actions`

### Event Bus

[EventBus](file:///workspace/core/event_bus.py#L48-L126) is an async pub/sub system:

- `subscribe(topic, handler)` registers async handlers
- `publish(Event(...))` calls all handlers concurrently via `asyncio.gather`
- handler failures are logged and isolated

### Sensors

Sensors produce raw data and publish events:

- Camera: [CameraSensor](file:///workspace/sensors/camera_sensor.py)
  - publishes `sensor.vision`
  - should output bytes (recommended: JPEG) or a numpy frame (if you add numpy/OpenCV)
- Microphone: [MicrophoneSensor](file:///workspace/sensors/microphone_sensor.py)
  - publishes `sensor.audio`
  - intended output is raw PCM bytes (default config: 16 kHz, mono)

### Perception Clients

Perception clients consume sensor events, call a local AI API, update context, and publish structured results:

- Vision: [VisionClient](file:///workspace/perception/vision_client.py)
  - subscribes to `sensor.vision`
  - publishes `perception.objects` with a `List[DetectedObject]`
- Speech-to-text: [SpeechClient](file:///workspace/perception/speech_client.py)
  - subscribes to `sensor.audio`
  - publishes `perception.speech` with a text string

### Context

[ContextManager](file:///workspace/core/context_manager.py#L61-L231) is the shared state store:

- most recent objects, last speech
- rolling conversation history (human + robot turns)
- current expression + recent actions
- `snapshot()` produces a stable payload for the decision layer

### Decision

[DecisionEngine](file:///workspace/decision/decision_engine.py#L31-L207) is the “brain”:

- listens for `perception.speech` triggers
- periodically runs a “decision cycle”
- builds an LLM payload via [ContextBuilder](file:///workspace/decision/context_builder.py#L20-L129)
- expects a structured response: `{"actions": [...]}` and publishes `decision.actions`

### Actions

Actions are structured objects returned by the decision API and executed by handlers:

- definitions and parsing: [action_types.py](file:///workspace/actions/action_types.py#L32-L164)
- routing: [ActionDispatcher](file:///workspace/core/action_dispatcher.py#L25-L118)
- handlers:
  - Speak: [SpeakHandler](file:///workspace/actions/speak_handler.py)
  - Eye expression / animation: [eye_expression_handler.py](file:///workspace/actions/eye_expression_handler.py)

### Idle Behaviors

Autonomous services can publish actions without the LLM:

- Idle blink: [IdleBlinkService](file:///workspace/behaviors/idle_blink.py#L26-L116) publishes `decision.actions` with `play_eye_animation`

