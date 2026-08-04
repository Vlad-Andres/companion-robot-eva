# Roadmap

## Built

- Event-driven robot runtime with service lifecycle and degraded-mode tolerance
- Microphone capture with chunking, and a streaming WebSocket link to the server
- OLED eye animations, expressions and idle blinking
- Server: REST + WebSocket session, STT wiring, rule-based command matching, Piper speech synthesis
- Half-duplex audio suppression so Eva doesn't hear herself
- Optional capture of labelled training audio (see [training-data.md](training-data.md))
- One action registry (`server/actions.py`) that validates every command before it reaches the wire
- Server-side endpointing: Silero VAD with pre-roll, and Smart Turn v3 deciding whether a pause is
  the end of a sentence or you thinking
- Streamed replies — Ollama tokens cut into sentences and synthesized one at a time, so Eva starts
  speaking before the reply is finished

## Next, in order

**1. Freeze the protocol and add the capability handshake.** The robot should announce its
available sensors and actuators on connect, and the server should build the models' output schema
from that manifest. This is what makes hardware genuinely pluggable, and everything below assumes
it.

**2. Tune the endpointer against real speech.** The defaults — 0.6 s hangover, 0.3 s pre-roll, a
0.5 Smart Turn threshold — are starting points, not measurements. Capture a handful of real
exchanges and check the two failure directions separately: cutting you off mid-thought means the
hangover or the turn threshold is too aggressive, while a laggy feel means they are too generous.

**3. Command tiers and the arbiter.** Implement Tier 0/1/3 first and measure the real ratio of
commands to dialogue before adding the Tier 2 small model — if the string tiers already catch most
commands, it earns very little.

**4. On-device intent model.** Train a closed-set intent classifier with a reject class on
the captured dataset and run it on the Pi, wired to execute locally rather than to annotate
messages. Keeps working when WiFi drops, and answers in tens of milliseconds instead of a
round trip. Needs a few hundred samples per command first.

**5. Promotion store.** Log commands the language model caught that Tier 1 missed; promote a phrase
to the fast path after three consistent hits, so Eva gets faster at your personal phrasing.

**6. Camera and vision.** Add a camera sensor publishing frames, and a server route that runs a
small vision model over them. (The earlier stub and its HTTP client were removed as dead code —
this starts fresh, over the existing WebSocket rather than a third service.)

**7. Motors.** Handle `move_base` on the robot and wire the base. The command already reaches it
and is logged.

## Known gaps

- The language model is prompted for plain text and is not constrained by the action registry, so
  it can only talk, never act. Item 1 above closes this; Ollama's `format` parameter takes a JSON
  schema, and the registry can already produce one.
- The server address is hardcoded in `robot/config.py`; mDNS discovery would make Eva portable
  between networks.
- `robot/config.py` has no file or environment layer — defaults are edited in place.
- The Piper voice model (~63 MB) is committed to the repo. If more voices get added, move them to
  Git LFS or fetch them in a setup step alongside `make models`.
- Barge-in (interrupting Eva mid-sentence) needs acoustic echo cancellation; today the microphone
  is muted during playback. The endpointer would otherwise already detect the interruption.
- The microphone is always streaming, so everything in the room reaches the Mac. The old RMS gate
  was an accidental privacy filter; if that matters, the honest replacement is a wake word or
  push-to-talk, not an energy threshold that does both jobs badly.
- No automated tests cover the robot half; `robot/tools/` are manual hardware checks.
