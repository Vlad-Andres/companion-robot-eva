## Companion Robot EVA — Repository Wiki

This wiki explains how the repository is structured, how the runtime works end-to-end, and where to extend it.

### Start Here

- [Running The Robot](running.md)
- [Architecture Overview](architecture.md)
- [Subsystems](subsystems.md)
- [Local API Contracts](local-apis.md)
- [Extending The Robot](extending.md)
- [Further Development Roadmap](roadmap.md)

### Mental Model

The robot follows a pipeline:

Sensor → EventBus → Perception → ContextManager → DecisionEngine → ActionDispatcher → Handlers

The key idea is decoupling: sensors can run fast, APIs can be slow, and actions can be ordered, without the whole system blocking.

