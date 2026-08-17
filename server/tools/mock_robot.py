"""
mock_robot.py — A fake Pi, for exercising the server on its own.

The mirror image of mock_command_server.py: that one fakes the server so the
robot can be tested alone, this one fakes the robot so the server can be. It
speaks the real eva/1 protocol, so what gets tested is the server's actual
message handling and not a convenient approximation of it.

It announces a capability manifest, streams audio at real time, and prints
everything that comes back — including which commands the server decided to
send, which is the thing worth watching once the model can act.

    # A rule-matched command. Needs macOS `say` to make the audio.
    python tools/mock_robot.py --say "turn left"

    # A robot with no wheels: the same words come back as conversation,
    # because the server will not promise movement this robot cannot make.
    python tools/mock_robot.py --say "turn left" --actuators speaker,eyes

    # Firmware from before the handshake still works.
    python tools/mock_robot.py --say "hello there" --no-capabilities

    # Your own audio, at whatever the server is configured to expect.
    python tools/mock_robot.py --wav recording.wav

Pair it with EVA_SPEECH_TO_TEXT_STUB_TEXT and EVA_LANGUAGE_MODEL_STUB_REPLY to
run the whole path with no Whisper, no Ollama and no robot at all.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Optional

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from protocol import PROTOCOL_ID, dumps_message  # noqa: E402

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512               # 32 ms, the frame the server endpoints on
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE


# ----------------------------------------------------------------------
# Audio in
# ----------------------------------------------------------------------


def _read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2 or handle.getframerate() != SAMPLE_RATE:
            raise SystemExit(
                f"{path}: need mono 16-bit {SAMPLE_RATE} Hz, got "
                f"{handle.getnchannels()}ch {handle.getsampwidth() * 8}-bit {handle.getframerate()} Hz"
            )
        return handle.readframes(handle.getnframes())


def _synthesize(text: str) -> bytes:
    """Speak `text` with macOS `say`, in exactly the format the robot sends."""
    if shutil.which("say") is None:
        raise SystemExit("--say needs macOS `say`; pass --wav instead, or use EVA_SPEECH_TO_TEXT_STUB_TEXT")

    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "utterance.wav")
        subprocess.run(
            ["say", "-o", path, "--data-format=LEI16@16000", "--channels=1", text],
            check=True,
        )
        return _read_wav(path)


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(SAMPLE_RATE * seconds)


# ----------------------------------------------------------------------
# The session
# ----------------------------------------------------------------------


def _manifest(args: argparse.Namespace) -> dict:
    return {
        "v": PROTOCOL_ID,
        "type": "capabilities",
        "protocol": [args.protocol],
        "robot": {"id": args.robot_id, "name": "mock robot"},
        "sensors": [s for s in args.sensors.split(",") if s],
        "actuators": [a for a in args.actuators.split(",") if a],
        "audio": {"encoding": "pcm_s16le", "sample_rate_hz": SAMPLE_RATE, "channels": 1},
    }


async def _stream_audio(websocket, audio: bytes, *, realtime: bool) -> None:
    """
    Send the audio one frame at a time.

    Paced to real time by default, because the server's endpointer decides
    where the utterance ends from silence between frames. Blasting the whole
    file at once tests a timing the robot will never produce.
    """
    total = len(audio) // 2 // FRAME_SAMPLES
    print(f"-- streaming {total} frames ({len(audio) / 2 / SAMPLE_RATE:.2f}s of audio)")

    next_send = time.monotonic()
    for index in range(total):
        start = index * FRAME_SAMPLES * 2
        try:
            await websocket.send(audio[start : start + FRAME_SAMPLES * 2])
        except websockets.ConnectionClosed:
            print("-- connection closed mid-stream; stopping")
            return
        if realtime:
            next_send += FRAME_SECONDS
            delay = next_send - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)


async def _receive(websocket, out_dir: Optional[Path]) -> None:
    """Print every message; save the speech so it can be listened to."""
    try:
        await _receive_loop(websocket, out_dir)
    except websockets.ConnectionClosed as closed:
        # The server hanging up is a result, not a crash: it is how a rejected
        # protocol version is meant to look from here.
        print(f"-- server closed the connection: {closed.code} {closed.reason or ''}".rstrip())


async def _receive_loop(websocket, out_dir: Optional[Path]) -> None:
    speech_index = 0
    async for message in websocket:
        if isinstance(message, (bytes, bytearray)):
            speech_index += 1
            note = f"<- audio {len(message)} bytes"
            if out_dir is not None:
                path = out_dir / f"reply_{speech_index:02d}.wav"
                path.write_bytes(bytes(message))
                note += f" → {path}"
            print(note)
            continue

        try:
            data = json.loads(message)
        except ValueError:
            print(f"<- unparseable: {message!r}")
            continue

        kind = data.get("type")
        if kind == "command":
            command = data.get("command", {})
            print(f"<- COMMAND  {command.get('name')} {command.get('args')}")
        elif kind == "speech.start":
            print(f"<- SPEAKS   {data.get('speech', {}).get('text')!r}")
        elif kind == "transcript.final":
            print(f"<- HEARD    {data.get('text')!r}")
        elif kind == "capabilities.ack":
            accepted = data.get("accepted", {})
            actions = [a.get("name") for a in data.get("actions", [])]
            print(f"<- ACK      protocol={data.get('protocol')} accepted={accepted} can be sent: {actions}")
            if data.get("unknown"):
                print(f"            server has no actions for: {data['unknown']}")
        elif kind == "status":
            print(f"<- status   {data.get('state')}")
        elif kind == "error":
            print(f"<- ERROR    {data.get('error')}")
        else:
            print(f"<- {kind}   {dumps_message(data)}")


async def run(args: argparse.Namespace) -> None:
    if args.wav:
        audio = _read_wav(args.wav)
    elif args.say:
        audio = _synthesize(args.say)
    else:
        audio = _silence(args.silence)

    # A moment of quiet after the words, so the endpointer sees the turn end
    # the way it would in a room rather than at the end of a file.
    audio += _silence(args.trailing_silence)

    out_dir = Path(args.out) if args.out else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)

    url = args.server.replace("http://", "ws://").replace("https://", "wss://").rstrip("/") + "/v1/websocket/audio"
    print(f"-- connecting to {url}")

    async with websockets.connect(url) as websocket:
        receiver = asyncio.create_task(_receive(websocket, out_dir))

        if not args.no_capabilities:
            manifest = _manifest(args)
            print(f"-> capabilities sensors={manifest['sensors']} actuators={manifest['actuators']}")
            await websocket.send(dumps_message(manifest))
            # Let the acknowledgement land before the audio, so the log reads
            # in the order the handshake actually happened — and so a rejected
            # protocol version is seen before anything is streamed at it.
            await asyncio.sleep(0.3)
            if receiver.done():
                print("-- done")
                return
        else:
            print("-> (no manifest — pretending to be firmware older than the handshake)")

        await _stream_audio(websocket, audio, realtime=not args.fast)

        if args.audio_end:
            await websocket.send(dumps_message({"v": PROTOCOL_ID, "type": "audio.end"}))

        print(f"-- listening for {args.wait:.0f}s")
        try:
            await asyncio.wait_for(receiver, timeout=args.wait)
        except asyncio.TimeoutError:
            receiver.cancel()
        print("-- done")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pretend to be Eva's Raspberry Pi.")
    parser.add_argument("--server", default="ws://127.0.0.1:8002", help="server base URL")

    source = parser.add_mutually_exclusive_group()
    source.add_argument("--say", help="speak this text with macOS `say` and send it")
    source.add_argument("--wav", help="send this WAV file (mono 16-bit 16 kHz)")
    parser.add_argument("--silence", type=float, default=1.0, help="seconds of silence when neither --say nor --wav is given")
    parser.add_argument("--trailing-silence", type=float, default=1.2, help="silence appended so the turn ends naturally")

    parser.add_argument("--sensors", default="microphone", help="comma-separated sensor manifest")
    parser.add_argument("--actuators", default="base,speaker,eyes", help="comma-separated actuator manifest")
    parser.add_argument("--robot-id", default="mock-01")
    parser.add_argument("--protocol", default=PROTOCOL_ID, help="protocol version to offer (try eva/9 to see a rejection)")
    parser.add_argument("--no-capabilities", action="store_true", help="never send a manifest, like older firmware")

    parser.add_argument("--audio-end", action="store_true", help="force an endpoint instead of letting the server decide")
    parser.add_argument("--fast", action="store_true", help="send frames as fast as possible instead of at real time")
    parser.add_argument("--wait", type=float, default=25.0, help="seconds to keep listening for replies")
    parser.add_argument("--out", help="directory to write the replies' WAVs into")

    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\n-- interrupted")


if __name__ == "__main__":
    main()
