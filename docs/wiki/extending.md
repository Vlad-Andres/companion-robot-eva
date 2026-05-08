## Extending The Robot

This repo is intentionally organized so you can extend it without tightly coupling modules.

### Add A New Sensor

1. Create a new module in `sensors/`.
2. Subclass [BaseSensor](file:///workspace/sensors/base_sensor.py#L20-L56) and implement `start()` / `stop()`.
3. Publish events via [EventBus.publish](file:///workspace/core/event_bus.py#L96-L126) to a new `sensor.*` topic.
4. Register the sensor in [RobotRuntime._register_sensors](file:///workspace/runtime.py#L157-L168).

### Add A New Perception Client (New Local Model)

1. Create a module in `perception/`.
2. Subclass [BasePerceptionClient](file:///workspace/perception/base_perception.py#L18-L65).
3. Subscribe to the right `sensor.*` topic in `start()`.
4. Call your local API, parse output, update [ContextManager](file:///workspace/core/context_manager.py#L61-L231).
5. Publish a `perception.*` event for the rest of the system.
6. Register the client in [RobotRuntime._register_perception_clients](file:///workspace/runtime.py#L170-L181).

### Add A New Action Type

1. Add a new value to [ActionType](file:///workspace/actions/action_types.py#L32-L45).
2. Add a payload dataclass for the new action.
3. Register the payload class in `_ACTION_REGISTRY`.
4. Implement a handler by subclassing [BaseActionHandler](file:///workspace/actions/base_action_handler.py#L15-L48).
5. Register the handler in [RobotRuntime._register_action_handlers](file:///workspace/runtime.py#L135-L156).

### Add An Autonomous Behavior

Autonomous behaviors are just services that publish actions on timers or heuristics.

Example: [IdleBlinkService](file:///workspace/behaviors/idle_blink.py#L26-L116)

To add your own:

1. Add a service in `behaviors/` with `start()`/`stop()`.
2. Publish `decision.actions` events with structured action dicts.
3. Register it in [RobotRuntime._register_idle_behaviors](file:///workspace/runtime.py#L195-L209).

