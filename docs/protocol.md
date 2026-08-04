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

## Session flow

1. Robot connects to `ws://<server>:8002/v1/websocket/audio`.
2. Server sends `hello`, then `status` with state `ready`.
3. Robot streams **every** microphone frame as binary — PCM S16LE, mono, 16 kHz, 512 samples
   (32 ms) per frame. It applies no gate and makes no decisions; 32 KB/s is cheap and discarding
   audio early is what used to clip word onsets.
4. The server decides where the utterance ends, from the audio: Silero VAD per frame, 300 ms of
   pre-roll kept from before speech was detected, and Smart Turn to check the sentence actually
   sounds finished before committing. `audio.end` still forces an endpoint but nothing requires the
   robot to send it.
5. Server replies with the messages below. Binary frames carry synthesised speech as WAV — **one
   per sentence**, streamed as the reply is written, so expect several per turn.

While Eva is speaking the server ignores inbound audio, so she does not transcribe her own voice.

Frame size is a transport detail. The server reassembles frames across reads, and Whisper only ever
sees whole utterances, so it has no effect on transcription accuracy.

## Messages the server sends

| Type | Payload | Robot behaviour |
|---|---|---|
| `hello` | — | Logged |
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
| `ping` | Keepalive; server replies `pong` |
| `audio.end` | Force an endpoint now *(supported; the robot does not need to send it)* |
| `audio.format` | Override the assumed audio format *(defined, not yet sent)* |

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
before it reaches the wire, so an unknown name or a bad argument never leaves the server.

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
| `EVA_OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Ollama endpoint |
| `EVA_OLLAMA_MODEL` | `llama3.2:3b` | Model name |
| `EVA_OLLAMA_TIMEOUT_SECONDS` | `30` | Request timeout |
| `EVA_OLLAMA_MAX_REPLY_TOKENS` | `80` | Reply length cap |
| `EVA_OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model resident |
| `EVA_DATASET_CAPTURE_ENABLED` | `false` | Record labelled training audio |
| `EVA_DATASET_DIR` | `dataset` | Where captured samples are written |
| `EVA_DATASET_MAX_BYTES` | `2000000000` | Capture pauses at this size |

Robot settings are dataclasses in `robot/config.py` — display, microphone, server address, idle
blink and audio output. The server address is hardcoded there; mDNS discovery is on the roadmap.
