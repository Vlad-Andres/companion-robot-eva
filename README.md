# Robot Backend (REST + WebSocket)

This backend receives audio over WebSocket, performs STT, and emits structured robot commands grouped by action type (speak/move/go_to/etc.). It also exposes a small REST API for discovery (supported actions, protocol version).

## Run

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn robot_backend.asgi:app --host 0.0.0.0 --port 8002
```

## REST API

- `GET /health`
- `GET /v1/protocol`
- `GET /v1/actions`

## WebSocket API

- Endpoint: `ws://<host>:8002/v1/ws/audio`
- Transport:
  - Binary frames: raw audio chunks (default: PCM S16LE mono 16kHz)
  - Text frames: JSON control messages (protocol `robot-backend/1`)

### Minimal client flow

1. Connect to `/v1/ws/audio`
2. Send audio chunks as binary frames
3. Send `{"type":"audio.end","utterance_id":"<id>"}` as a text frame to finalize immediately (otherwise idle timeout finalizes)
4. Receive:
   - `{"type":"asr.final", ...}`
   - `{"type":"cmd","cmd":{"name":"move_base","group":"move","args":{...}}}`
   - `{"type":"cmd","cmd":{"name":"speak","group":"speak","args":{...}}}`
   - `{"type":"memory.suggest","items":[...]}` for robot-side memory storage

## Configuration

Environment variables:

- `ROBOT_BACKEND_PORT` (default `8002`)
- `ROBOT_BACKEND_AUDIO_IDLE_SECONDS` (default `0.9`)
- `ROBOT_BACKEND_AUDIO_MAX_BYTES` (default `2000000`)
- `ROBOT_BACKEND_STT_STUB_TEXT` (set to force a deterministic transcript for testing)
- `ROBOT_BACKEND_LLM_ENABLED` (default `false`)
- `ROBOT_BACKEND_OLLAMA_BASE_URL` / `ROBOT_BACKEND_OLLAMA_MODEL`
- `ROBOT_BACKEND_TTS_ENABLED` (default `true`)

## Tests

```bash
pytest -q
```
