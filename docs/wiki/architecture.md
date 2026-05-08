## Architecture Overview

### The Core Loop

At a high level, the runtime is an event-driven graph with a single orchestration entrypoint:

- Entry point: [main.py](file:///workspace/main.py)
- Composition root (wiring): [RobotRuntime](file:///workspace/runtime.py#L36-L309)

### Dataflow (Topics)

The system uses a pub/sub bus where every component communicates via topic names.

Key topics (see [EventBus](file:///workspace/core/event_bus.py#L1-L126)):

- `sensor.vision`: raw camera frame data
- `sensor.audio`: raw microphone audio chunks
- `perception.objects`: structured objects detected from vision
- `perception.speech`: transcribed human speech text
- `decision.actions`: list of structured actions to execute

### Why Event-Driven

- Sensors publish data at hardware cadence without knowing who consumes it.
- Perception clients can call slow local APIs with backpressure (semaphores) and retries.
- Decision and actions can run at “human” pace without blocking sensors.

### Services And Lifecycle

Most components are “services” (start/stop) managed by [ServiceRegistry](file:///workspace/core/service_registry.py#L21-L141):

- Start order = registration order
- Stop order = reverse order
- Failures are logged; the robot can still run partially (degraded mode)

