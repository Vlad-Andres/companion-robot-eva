# Eva — companion robot

A companion robot that listens, talks and reacts with a pair of OLED eyes. It runs on two machines:

```
robot/     → Raspberry Pi 4     microphone, OLED eyes, speaker, reflexes
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
├── core/              event bus, service registry, action dispatcher
├── sensors/           microphone capture
├── perception/        speech client — owns the WebSocket session
├── actions/           eye expression and animation handlers
├── behaviors/         server feedback, idle blink
├── display/           OLED eye animation controller
├── utils/             logging, audio playback, WAV volume
├── sounds/            startup and blink sound effects
├── tools/             manual hardware diagnostics — run these by hand
└── HARDWARE.md        wiring guide: pins, I2C addresses, bring-up checks

server/                     Mac mini brain
├── asgi.py                 ASGI entry point (uvicorn asgi:app)
├── app.py                  REST routes and WebSocket endpoint
├── websocket_session.py    session handling: audio in, commands out
├── speech_to_text.py       transcription engine (faster-whisper)
├── text_to_speech.py       speech synthesis (Piper, or macOS say)
├── language_model.py       language model client (Ollama)
├── planner.py              transcript → commands or dialogue
├── action_rules.py         fast-path phrase matching
├── actions.py              action registry, schemas and validation
├── protocol.py             message envelopes
├── config.py               environment-variable settings
├── dataset_recorder.py     optional capture of labelled training audio
├── log.py                  logging setup
├── tests/                  server test suite
├── voices/                 Piper voice model
└── tools/                  mock server, dataset summary
```

## Docs

- [Architecture](docs/architecture.md) — how a turn flows today, and the design being built toward
- [Protocol](docs/protocol.md) — WebSocket and REST contract, message shapes, configuration
- [Roadmap](docs/roadmap.md) — what's built, what's next, known gaps
- [Training data](docs/training-data.md) — capturing labelled audio for the on-device intent model
- [Wiring](robot/HARDWARE.md) — which component goes on which pin

## Extending

| To add… | Do this |
|---|---|
| A sensor | Subclass `BaseSensor`, register it in `runtime.py`, publish to a `sensor.*` topic |
| A fast-path phrase | Add a rule in `server/action_rules.py` — commands are wire-shape `{name, args}` |
| An action | Add it to `server/actions.py` (definition + a `validate_command` branch), then handle the name in `robot/behaviors/server_feedback.py` |
| A behavior | Add a service in `robot/behaviors/`, register it in `runtime.py` |
| An eye animation | Add an `Animation` member and a method to `robot/display/eye_controller.py` |

`server/actions.py` is the single source of truth for what Eva can do: the same registry is served
over `GET /v1/actions` and gates every command before it reaches the wire. Constraining the
language model's output with it is the next step — see the roadmap.

## Tests

```bash
make test
```

Covers the server: REST routes, WebSocket audio handling and phrase matching. The scripts in
`robot/tools/` are manual hardware checks, not automated tests — run them on the Pi by hand.
