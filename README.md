# Eva — companion robot

A companion robot that drives around, sees, listens and talks. It runs on two machines:

```
robot/     → Raspberry Pi 4     sensors, motors, OLED eyes, speaker, reflexes
server/    → Mac mini           speech recognition, language models, speech synthesis
```

They talk over a single WebSocket session on your local WiFi. The Pi stays deliberately thin — it
captures audio, executes commands and handles reflexes, while everything expensive happens on the
Mac. That's what keeps Eva responsive on battery power.

Read [docs/architecture.md](docs/architecture.md) for the full picture and the system diagram.

## Quick start

Everything runs through `make`. Run `make` on its own to see all targets.

**On the Mac mini:**

```bash
make setup-server && make server
```

The server listens on `:8002`. Check it with `curl localhost:8002/health`.

**On the Raspberry Pi:**

```bash
make setup-robot && make robot
```

Point the Pi at your Mac by setting `speech_api.base_url` in [robot/config.py](robot/config.py).

**No Mac handy?** `make mock` starts a fake server that cycles movement commands, so you can
exercise the robot's eyes and command handling on its own.

### Getting the code onto the Pi

Use the sparse clone so the Pi never downloads the server or its ~63 MB voice model:

```bash
curl -fsSL https://raw.githubusercontent.com/Vlad-Andres/companion-robot-eva/main/scripts/pi-clone.sh | bash
```

## Layout

```
robot/                 Raspberry Pi runtime
├── main.py            entry point
├── runtime.py         composition root — wires every service together
├── config.py          typed configuration dataclasses
├── core/              event bus, context manager, service registry, dispatcher
├── sensors/           camera and microphone adapters
├── perception/        clients that talk to the server
├── actions/           command handlers (speak, eye expression)
├── behaviors/         autonomous reflexes (idle blink)
├── display/           OLED eye animation controller
├── memory/            short and long term memory
├── tools/             manual hardware diagnostics — run these by hand
└── HARDWARE.md        wiring guide: pins, I2C addresses, bring-up checks

server/                     Mac mini brain
├── asgi.py                 ASGI entry point (uvicorn asgi:app)
├── app.py                  REST routes and WebSocket endpoint
├── websocket_session.py    session handling: audio in, commands out
├── speech_to_text.py       transcription engine
├── text_to_speech.py       speech synthesis (Piper)
├── language_model.py       language model client (Ollama)
├── planner.py              transcript → commands
├── action_rules.py         fast-path phrase matching
├── actions.py              action registry and argument schemas
├── protocol.py             message envelopes
├── dataset_recorder.py     optional capture of labelled training audio
├── voices/                 Piper voice model
└── tools/                  mock server for robot-side testing
```

## Docs

- [Architecture](docs/architecture.md) — the diagram, the command tiers, the design principles
- [Protocol](docs/protocol.md) — WebSocket and REST contract, message shapes, configuration
- [Roadmap](docs/roadmap.md) — what's built, what's next, known gaps
- [Training data](docs/training-data.md) — capturing labelled audio for the on-device intent model
- [Wiring](robot/HARDWARE.md) — which component goes on which pin

## Extending

| To add… | Do this |
|---|---|
| A sensor | Subclass `BaseSensor`, register it in `runtime.py`, publish to a `sensor.*` topic |
| An action | Add it to `server/actions.py` with an arg schema, then write a handler in `robot/actions/` |
| A behavior | Add a service in `robot/behaviors/` that publishes actions on its own timer |
| A fast-path phrase | Add a rule in `server/action_rules.py` |

Because the server builds the language models' output schema from the action registry, adding an
action in one place makes it available to the models automatically.

## Tests

```bash
make test
```

Covers the server: REST routes, WebSocket audio handling and phrase matching. The scripts in
`robot/tools/` are manual hardware checks, not automated tests — run them on the Pi by hand.
