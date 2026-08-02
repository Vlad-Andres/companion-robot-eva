# Roadmap

## Built

- Event-driven robot runtime with service lifecycle and degraded-mode tolerance
- Microphone capture with chunking, and a streaming WebSocket link to the server
- OLED eye animations, expressions and idle blinking
- Server: REST + WebSocket session, STT wiring, rule-based command matching, Piper speech synthesis
- Half-duplex audio suppression so Eva doesn't hear herself
- Optional capture of labelled training audio (see [training-data.md](training-data.md))
- One action registry (`server/actions.py`) that validates every command before it reaches the wire

## Next, in order

**1. Freeze the protocol and add the capability handshake.** The robot should announce its
available sensors and actuators on connect, and the server should build the models' output schema
from that manifest. This is what makes hardware genuinely pluggable, and everything below assumes
it.

**2. Voice gate on the Pi.** Replace the per-chunk RMS threshold in `robot/perception/speech_client.py`
with frame-level Silero VAD: 500 ms pre-roll so word starts aren't clipped, 500 ms hangover before
declaring the end, then send `audio.end` immediately. This removes 1–2 seconds of dead air per
exchange and stops feeding silence to the recogniser.

**3. Streaming response path.** Stream tokens from the language model, split on sentence
boundaries, and start speaking the first sentence while the rest generates.

**4. Command tiers and the arbiter.** Implement Tier 0/1/3 first and measure the real ratio of
commands to dialogue before adding the Tier 2 small model — if the string tiers already catch most
commands, it earns very little.

**5. On-device intent model.** Train a closed-set intent classifier with a reject class on
the captured dataset and run it on the Pi, wired to execute locally rather than to annotate
messages. Keeps working when WiFi drops, and answers in tens of milliseconds instead of a
round trip. Needs a few hundred samples per command first.

**6. Promotion store.** Log commands the language model caught that Tier 1 missed; promote a phrase
to the fast path after three consistent hits, so Eva gets faster at your personal phrasing.

**7. Camera and vision.** Add a camera sensor publishing frames, and a server route that runs a
small vision model over them. (The earlier stub and its HTTP client were removed as dead code —
this starts fresh, over the existing WebSocket rather than a third service.)

**8. Motors.** Handle `move_base` on the robot and wire the base. The command already reaches it
and is logged.

## Known gaps

- The language model is prompted for plain text and is not constrained by the action registry, so
  it can only talk, never act. Item 1 above closes this.
- Rule-matched confirmations ("Turning left.") arrive as a `speak` command, but the robot has no
  local synthesis, so they are logged rather than spoken. Either route them through server-side TTS
  or give the robot a local voice.
- The server address is hardcoded in `robot/config.py`; mDNS discovery would make Eva portable
  between networks.
- `robot/config.py` has no file or environment layer — defaults are edited in place.
- Playback volume is applied twice: `apply_wav_volume` scales the samples *and* `set_alsa_volume`
  sets the mixer, which is why `volume_percent` is tuned so low. Worth picking one.
- The Piper voice model (~63 MB) is committed to the repo. If more voices get added, move them to
  Git LFS or fetch them in a setup step.
- Barge-in (interrupting Eva mid-sentence) needs acoustic echo cancellation; today the microphone
  is simply muted during playback.
- No automated tests cover the robot half; `robot/tools/` are manual hardware checks.
