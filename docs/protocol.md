# Wire protocol

One WebSocket session carries everything between robot and server. Protocol id: `eva/1`
(see `server/protocol.py`).

## Endpoints

The server listens on port **8002**.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `GET /v1/protocol` | Returns the protocol id the server speaks |
| `GET /v1/actions` | Lists supported actions with their JSON arg schemas |
| `WS /v1/websocket/audio` | The session: audio up, commands and speech down |
| `GET /debug` | Live listening dashboard *(only when `EVA_DEBUG_ENABLED`)* |
| `WS /v1/websocket/debug` | Telemetry feed for that dashboard |

## Watching it work

With `EVA_DEBUG_ENABLED=true`, open `http://<server>:8002/debug` while you talk to
Eva. It shows the incoming level and Silero's speech probability frame by frame,
highlights the exact audio each utterance captured — pre-roll included — and
breaks down where the time went per stage, so "why did that feel slow?" has an
answer instead of a guess. Stages over 800 ms are flagged.

It is off by default, and when off the telemetry object is a no-op, so nothing
is measured or allocated on the audio path. A dashboard that stops reading gets
dropped events rather than being allowed to slow the pipeline.

## Session flow

1. Robot connects to `ws://<server>:8002/v1/websocket/audio`.
2. Server sends `hello` — carrying `protocol` and every version it still serves — then
   `status` with state `ready`.
3. Robot sends `capabilities`, announcing its hardware. The server answers with
   `capabilities.ack`, naming the exact commands this session may send it. See
   [the handshake](#the-handshake) below; a robot that skips this step still works.
4. Robot streams **every** microphone frame as binary — PCM S16LE, mono, 16 kHz, 512 samples
   (32 ms) per frame. It applies no gate and makes no decisions; 32 KB/s is cheap and discarding
   audio early is what used to clip word onsets.
5. The server decides where the utterance ends, from the audio: Silero VAD per frame, 300 ms of
   pre-roll kept from before speech was detected, and Smart Turn to check the sentence actually
   sounds finished before committing. `audio.end` still forces an endpoint but nothing requires the
   robot to send it.
6. Server replies with the messages below. Binary frames carry synthesised speech as WAV — **one
   per sentence**, streamed as the reply is written, so expect several per turn.

While Eva is speaking the server ignores inbound audio, so she does not transcribe her own voice.

Frame size is a transport detail. The server reassembles frames across reads, and Whisper only ever
sees whole utterances, so it has no effect on transcription accuracy.

## The handshake

The robot announces its hardware; the server answers with the subset of the action registry
that hardware supports. Both halves matter: the robot learns exactly which commands can
arrive, and the server learns which ones it is allowed to produce — including in the
language model's output grammar, so a model **cannot** name an action the robot lacks.

**Robot → server**, once, right after connecting:

```json
{
  "v": "eva/1",
  "type": "capabilities",
  "protocol": ["eva/1"],
  "robot": {"id": "eva-pi-01", "name": "Eva"},
  "sensors": ["microphone"],
  "actuators": ["base", "speaker", "eyes"],
  "audio": {"encoding": "pcm_s16le", "sample_rate_hz": 16000, "channels": 1}
}
```

**Server → robot**, in reply:

```json
{
  "v": "eva/1",
  "type": "capabilities.ack",
  "protocol": "eva/1",
  "accepted": {"sensors": ["microphone"], "actuators": ["base", "eyes", "speaker"]},
  "actions": [{"name": "speak", "args_schema": {…}, "description": "…"},
              {"name": "move_base", "args_schema": {…}, "description": "…"}],
  "unknown": []
}
```

Known actuators are `base`, `speaker` and `eyes`; known sensors are `microphone` and
`camera`. Anything else is listed back under `unknown` rather than refused — a robot may
carry hardware the server has no action for yet.

The `audio` block folds in what `audio.format` used to say separately. Sending
`audio.format` still works.

**Rules.**

- **The manifest is optional.** A robot that never sends one is assumed to have every
  actuator, which is exactly how firmware older than this handshake behaved. Nothing about
  the existing robot changes.
- **An empty manifest is refused.** Declaring neither a sensor nor an actuator earns an
  `empty_capabilities` error and is ignored, because it is far likelier to be a bug on the
  robot than a robot with no hardware.
- **A version mismatch ends the session.** If `protocol` names nothing in the server's
  `supported_protocols`, the server sends `protocol_unsupported` and closes with 1002.
  Streaming audio nobody is going to answer is harder to diagnose than being told why.
- **Capability affects rules too.** A robot with no base does not hear "Turning left." for
  "turn left" — the whole rule is dropped and the utterance becomes conversation instead,
  because a confirmation is a promise and Eva should not make one she cannot keep.

## Messages the server sends

| Type | Payload | Robot behaviour |
|---|---|---|
| `hello` | `protocol`, `supported_protocols` | Logged |
| `capabilities.ack` | `protocol`, `accepted`, `actions`, `unknown` | Logged — the commands to expect |
| `status` | `state`: `ready` \| `listening` \| `thinking` | `listening` drives the glance animation |
| `transcript.final` | `utterance_id`, `text` | Published as `perception.transcript` |
| `command` | `command`: `{id, name, args}` | Executed — see below |
| `speech.start` | `speech`: `{id, text, audio_format}` | Happy eyes; the WAV follows |
| `speech.end` | `speech`: `{id}` | Logged |
| `memory.suggest` | `items` | Logged — no robot-side store yet |
| `language_model.requested` | `request_id`, `model` | Logged |
| `language_model.result` | `request_id` | Logged |
| `error` | `error`: `{code, message}` | Logged as a warning |

Anything unrecognised is logged rather than spoken, so Eva never reads raw JSON aloud.

## Messages the robot sends

| Type | Purpose |
|---|---|
| binary frames | PCM S16LE mono 16 kHz, 512 samples per frame, sent continuously |
| `capabilities` | Announce hardware and protocol version *(optional — see above)* |
| `ping` | Keepalive; server replies `pong` |
| `audio.end` | Force an endpoint now *(supported; the robot does not need to send it)* |
| `audio.format` | Override the assumed audio format *(or send it inside `capabilities`)* |

## Command envelope

```json
{
  "v": "eva/1",
  "type": "command",
  "id": "command_a1b2",
  "command": {
    "id": "command_a1b2",
    "name": "move_base",
    "args": {"command": "turn_left"}
  }
}
```

The authoritative list of action names and their argument schemas lives in `server/actions.py` and
is served over `GET /v1/actions`. Every command passes `validate_command()` against that registry
*and* against the connected robot's manifest before it reaches the wire, so an unknown name, a bad
argument, or an action this robot cannot perform never leaves the server.

Commands come from two places now: a matched phrase rule, or the language model, whose reply is
constrained to a `{"say": …, "commands": […]}` schema built from the same registry. The grammar
guarantees the shape of what the model emits, not that it makes sense — validation is the gate
either way, and it is the same gate for both paths.

Commands execute in arrival order. Concurrent execution groups and acknowledgements are on the
roadmap; today the envelope carries neither.

Currently defined: `speak` (`text`) and `move_base` (`command`, one of `stop`, `forward`,
`backward`, `turn_left`, `turn_right`, `come_here`). The robot has no motor handler yet, so
`move_base` is logged and shown on the eyes.

`speak` never travels over the wire: the server owns the synthesiser, so it fulfils speak actions
itself as `speech.start` plus a WAV. Only commands the robot can actually execute are sent.

## Configuration

Server settings come from environment variables, optionally via a `server/.env` file
(copy `server/.env.example`). Real environment variables override the file.
See `server/config.py`:

| Variable | Default | Purpose |
|---|---|---|
| `EVA_HOST` | `0.0.0.0` | Listen address |
| `EVA_PORT` | `8002` | Listen port |
| `EVA_AUDIO_MAX_BYTES` | `2000000` | Hard cap per utterance |
| `EVA_VAD_THRESHOLD` | `0.5` | Speech probability above which a frame counts |
| `EVA_PREROLL_SECONDS` | `0.3` | Audio kept from before speech was detected |
| `EVA_HANGOVER_SECONDS` | `0.6` | Silence that provisionally ends a turn |
| `EVA_MAX_EXTENSION_SECONDS` | `4.0` | How long an unfinished turn may run on |
| `EVA_MAX_UTTERANCE_SECONDS` | `30.0` | Hard cap on one utterance |
| `EVA_VAD_MODEL_PATH` | `models/silero_vad.onnx` | Silero weights |
| `EVA_TURN_DETECTION_ENABLED` | `true` | Semantic turn detection on/off |
| `EVA_TURN_MODEL_PATH` | `models/smart_turn.onnx` | Smart Turn weights |
| `EVA_TURN_THRESHOLD` | `0.5` | P(complete) above which a turn ends |
| `EVA_SPEECH_TO_TEXT_MODEL` | `small.en` | faster-whisper model |
| `EVA_SPEECH_TO_TEXT_STUB_TEXT` | — | Force a fixed transcript, for testing |
| `EVA_TEXT_TO_SPEECH_ENABLED` | `true` | Enable speech synthesis |
| `EVA_TEXT_TO_SPEECH_ENGINE` | `auto` | `auto`, `piper`, `macos_say` or `off` |
| `EVA_PIPER_MODEL_PATH` | `voices/en_GB-alba-medium.onnx` | Piper voice model |
| `EVA_PIPER_CONFIG_PATH` | `voices/en_GB-alba-medium.onnx.json` | Piper voice config |
| `EVA_LANGUAGE_MODEL_ENABLED` | `false` | Enable the dialogue path |
| `EVA_LANGUAGE_MODEL_STUB_REPLY` | — | Force a fixed reply instead of calling Ollama, for testing |
| `EVA_MODEL_ACTIONS_ENABLED` | `true` | Let the model emit commands; off falls back to plain text |
| `EVA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `EVA_OLLAMA_MODEL` | `llama3.2:3b` | Model name |
| `EVA_OLLAMA_TIMEOUT_SECONDS` | `30` | Request timeout |
| `EVA_OLLAMA_MAX_REPLY_TOKENS` | `80` | Reply length cap (a schema adds its own allowance) |
| `EVA_OLLAMA_TEMPERATURE` | `0.2` | Low: a creative sample is how a small model invents an action |
| `EVA_OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model resident |
| `EVA_DEBUG_ENABLED` | `false` | Serve the live dashboard at `/debug` |
| `EVA_DATASET_CAPTURE_ENABLED` | `false` | Record labelled training audio |
| `EVA_DATASET_DIR` | `dataset` | Where captured samples are written |
| `EVA_DATASET_MAX_BYTES` | `2000000000` | Capture pauses at this size |

Robot settings are dataclasses in `robot/config.py` — display, microphone, server address, idle
blink and audio output. The server address is hardcoded there; mDNS discovery is on the roadmap.
