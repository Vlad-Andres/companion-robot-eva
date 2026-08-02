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
2. Robot streams microphone audio as **binary frames** — PCM S16LE, mono, 16 kHz.
3. Robot sends `{"type":"audio.end","utterance_id":"<id>"}` as a **text frame** to finalise the
   utterance. Failing that, the server finalises after an idle timeout (default 0.9 s), which is a
   safety net rather than the intended path — the robot's voice gate should decide the endpoint.
4. Server replies with text frames:
   - `{"type":"transcript.final", ...}` — the transcript
   - `{"type":"command","command":{"name":"move_base","group":"move","args":{...}}}` — an action to execute
   - `{"type":"memory.suggest","items":[...]}` — facts worth storing on the robot
   - Binary frames carry synthesised speech audio for playback.
5. Robot acknowledges commands that set `requires_ack` with `command.ack`.

## Command envelope

Every command is grouped, which drives execution on the robot: different groups run concurrently
(Eva can speak while driving), the same group serialises, and a `stop` clears the `move` queue.

```json
{
  "v": "eva/1",
  "type": "command",
  "command": {
    "id": "command_a1b2",
    "name": "move_base",
    "group": "move",
    "args": {"command": "turn_left"},
    "requires_ack": true
  }
}
```

Groups are `speak`, `move`, `go_to`, `system` and `memory`. The authoritative list of action names
and their argument schemas lives in `server/actions.py` and is served over `GET /v1/actions` — that
same registry is what constrains the language models' output.

## Configuration

Server settings come from environment variables, optionally via a `server/.env` file
(copy `server/.env.example`). Real environment variables override the file.
See `server/config.py`:

| Variable | Default | Purpose |
|---|---|---|
| `EVA_PORT` | `8002` | Listen port |
| `EVA_AUDIO_IDLE_SECONDS` | `0.9` | Fallback utterance finalisation |
| `EVA_AUDIO_MAX_BYTES` | `2000000` | Hard cap per utterance |
| `EVA_SPEECH_TO_TEXT_STUB_TEXT` | — | Force a fixed transcript, for testing |
| `EVA_LANGUAGE_MODEL_ENABLED` | `false` | Enable the language model path |
| `EVA_OLLAMA_BASE_URL` | — | Ollama endpoint |
| `EVA_OLLAMA_MODEL` | — | Model name |
| `EVA_TEXT_TO_SPEECH_ENABLED` | `true` | Enable Piper speech synthesis |
| `EVA_DATASET_CAPTURE_ENABLED` | `false` | Record labelled training audio |
| `EVA_DATASET_DIR` | `dataset` | Where captured samples are written |

Robot settings are dataclasses in `robot/config.py` — display, camera, microphone, server address,
memory and audio. The server address is currently hardcoded; mDNS discovery is on the roadmap.
