import asyncio
import json
import os
import time
from typing import Optional

import websockets

from action_rules import match_action_from_text

DEBUG = True

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8002

STT_MODEL_NAME = "small.en"

LLM_ENABLED = True
OLLAMA_BASE_URL = "http://127.0.0.1:11434"
OLLAMA_MODEL = "llama3.2:3b"
OLLAMA_SYSTEM_PROMPT = "You are a nice, cute robot assistant inspired by Eve from Wall-E. I am your creator, you just got into this world and you have a small body. Reply with plain text only and be cute. Do not try to behave like a robot but like a kid. Do not use captions like *giggles*"
OLLAMA_TIMEOUT_SECONDS = 30
DIALOG_MAX_MESSAGES = 13
LLM_BUSY_SECONDS = 60.0
LLM_BUSY_MESSAGE = "BUSY"
LLM_READY_MESSAGE = "READY"

PIPER_MODEL_PATH = "voices/en_GB-alba-medium.onnx"
PIPER_CONFIG_PATH = "voices/en_GB-alba-medium.onnx.json"
TTS_SAVE_DIR = "generated_audio"

try:
    import numpy as np
    from faster_whisper import WhisperModel
except Exception:
    np = None
    WhisperModel = None


class Session:
    def __init__(self) -> None:
        self.audio = bytearray()
        self.last_rx: float = time.monotonic()
        self.last_final_full: str = ""
        self.ignore_until: float = 0.0
        self.last_action_key: str = ""
        self.last_tx_speech: str = ""
        self.dialog: list[dict[str, str]] = [{"role": "system", "content": OLLAMA_SYSTEM_PROMPT}]


class SttEngine:
    def __init__(self) -> None:
        self._model = None
        if WhisperModel is not None:
            self._model = WhisperModel(STT_MODEL_NAME, device="cpu", compute_type="int8")

    def available(self) -> bool:
        return self._model is not None and np is not None

    def transcribe_pcm16le_mono_16k(self, audio_bytes: bytes) -> str:
        if not self.available():
            return "hello robot"

        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(audio_np, beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments if s.text).strip()


ENGINE = SttEngine()

async def _send(websocket, message: str) -> None:
    print(f"TX -> {websocket.remote_address}: {message!r}")
    await websocket.send(message)

async def _send_bytes(websocket, data: bytes) -> None:
    print(f"TX(bin) -> {websocket.remote_address}: {len(data)} bytes")
    await websocket.send(data)

def _dbg(message: str) -> None:
    if DEBUG:
        print(message)

os.makedirs(TTS_SAVE_DIR, exist_ok=True)
_TTS_SEQ = 0


def _save_tts_wav(wav: bytes) -> str:
    global _TTS_SEQ
    _TTS_SEQ += 1
    ts_ms = int(time.time() * 1000)
    filename = f"tts_{ts_ms}_{_TTS_SEQ:06d}.wav"
    path = os.path.join(TTS_SAVE_DIR, filename)
    with open(path, "wb") as f:
        f.write(wav)
    return path


def _tts_wav_bytes(text: str) -> Optional[bytes]:
    import shutil
    import subprocess
    import tempfile

    piper = shutil.which("piper")
    if not piper:
        _dbg("Piper binary not found (pip install piper-tts)")
        return None
    if not os.path.exists(PIPER_MODEL_PATH):
        _dbg(f"Piper model not found: {PIPER_MODEL_PATH}")
        return None
    if not os.path.exists(PIPER_CONFIG_PATH):
        _dbg(f"Piper config not found: {PIPER_CONFIG_PATH}")
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        wav_path = f.name
    try:
        args = [piper, "--model", PIPER_MODEL_PATH, "--config", PIPER_CONFIG_PATH, "--output_file", wav_path]
        proc = subprocess.run(
            args,
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="ignore").strip()
            if err:
                _dbg(f"Piper error: {err}")
            return None
        with open(wav_path, "rb") as rf:
            return rf.read()
    finally:
        try:
            os.remove(wav_path)
        except Exception:
            pass

    return None


async def _send_speech(session: Session, websocket, text: str) -> None:
    if text == session.last_tx_speech:
        return
    session.last_tx_speech = text

    wav = await asyncio.to_thread(_tts_wav_bytes, text)
    if not wav:
        _dbg("TTS failed; no audio to send")
        return
    path = _save_tts_wav(wav)
    _dbg(f"TTS saved: {path}")
    await _send_bytes(websocket, wav)

def _ollama_generate(prompt: str) -> Optional[str]:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/generate"
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    try:
        import urllib.request
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            out = data.get("response")
            return out.strip() if isinstance(out, str) else None
    except Exception as e:
        try:
            body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        except Exception:
            body = ""
        _dbg(f"Ollama generate error: {e} {body}".strip())
        return None


def _ollama_chat(messages: list[dict[str, str]]) -> Optional[str]:
    url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
    payload = {"model": OLLAMA_MODEL, "messages": messages, "stream": False}
    try:
        import urllib.request

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=OLLAMA_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            message = data.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                return content.strip() if isinstance(content, str) else None
            return None
    except Exception as e:
        try:
            body = e.read().decode("utf-8") if hasattr(e, "read") else ""
        except Exception:
            body = ""
        _dbg(f"Ollama chat error: {e} {body}".strip())
        return None


async def _finalize_after_idle(websocket, session: Session, idle_seconds: float) -> None:
    while True:
        await asyncio.sleep(0.05)
        if not session.audio:
            continue
        if time.monotonic() < session.ignore_until:
            session.audio.clear()
            continue
        if time.monotonic() - session.last_rx < idle_seconds:
            continue

        full = ENGINE.transcribe_pcm16le_mono_16k(bytes(session.audio))
        session.audio.clear()

        if not full:
            continue

        _dbg(f"FINAL transcript: {full!r}")

        action = match_action_from_text(full)
        key = action.get("key") if isinstance(action, dict) else None
        if key and key != session.last_action_key:
            session.last_action_key = key
            session.ignore_until = time.monotonic() + 2.0
            await _send(websocket, f"DO {key}")
            continue

        if full == session.last_final_full:
            continue

        session.last_final_full = full
        if not LLM_ENABLED:
            await _send_speech(session, websocket, full)
            continue

        session.ignore_until = time.monotonic() + LLM_BUSY_SECONDS
        await _send(websocket, LLM_BUSY_MESSAGE)
        _dbg(f"LLM request: model={OLLAMA_MODEL!r} base={OLLAMA_BASE_URL!r}")

        session.dialog.append({"role": "user", "content": full})
        if len(session.dialog) > DIALOG_MAX_MESSAGES:
            session.dialog = [session.dialog[0], *session.dialog[-(DIALOG_MAX_MESSAGES - 1):]]

        reply = await asyncio.to_thread(_ollama_chat, session.dialog)
        if not reply:
            reply = await asyncio.to_thread(_ollama_generate, full)
        if reply:
            _dbg(f"LLM reply: {reply!r}")
            session.dialog.append({"role": "assistant", "content": reply})
            if len(session.dialog) > DIALOG_MAX_MESSAGES:
                session.dialog = [session.dialog[0], *session.dialog[-(DIALOG_MAX_MESSAGES - 1):]]
            await _send_speech(session, websocket, reply)
        else:
            _dbg("LLM reply empty; sending transcript")
            await _send_speech(session, websocket, full)

        session.ignore_until = 0.0
        await _send(websocket, LLM_READY_MESSAGE)


async def handle_stt(websocket, _path: Optional[str] = None) -> None:
    session = Session()
    finalize_task = asyncio.create_task(_finalize_after_idle(websocket, session, idle_seconds=0.9))
    try:
        async for message in websocket:
            if not isinstance(message, (bytes, bytearray)):
                continue

            session.last_rx = time.monotonic()
            if session.ignore_until and session.last_rx < session.ignore_until:
                continue
            session.audio.extend(message)
    finally:
        finalize_task.cancel()


async def main() -> None:
    _dbg(f"STT available={ENGINE.available()} llm={LLM_ENABLED} ollama_model={OLLAMA_MODEL!r} tts_model={PIPER_MODEL_PATH!r}")
    server = await websockets.serve(handle_stt, SERVER_HOST, SERVER_PORT)
    await server.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
