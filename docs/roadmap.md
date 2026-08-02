# Roadmap

## Built

- Event-driven robot runtime with service lifecycle and degraded-mode tolerance
- Microphone capture with chunking, and a streaming WebSocket link to the server
- OLED eye animations, expressions and idle blinking
- Server: REST + WebSocket session, STT wiring, rule-based command matching, Piper speech synthesis
- Half-duplex audio suppression so Eva doesn't hear herself

## Next, in order

**1. Freeze the protocol and add the capability handshake.** The robot should announce its
available sensors and actuators on connect, and the server should build the models' output schema
from that manifest. This is what makes hardware genuinely pluggable, and everything below assumes
it.

**2. Voice gate on the Pi.** Replace the per-chunk RMS threshold in `perception/speech_client.py`
with frame-level Silero VAD: 500 ms pre-roll so word starts aren't clipped, 500 ms hangover before
declaring the end, then send `audio.end` immediately. This removes 1–2 seconds of dead air per
exchange and stops feeding silence to the recogniser.

**3. Streaming response path.** Stream tokens from the language model, split on sentence
boundaries, and start speaking the first sentence while the rest generates.

**4. Command tiers and the arbiter.** Implement Tier 0/1/3 first and measure the real ratio of
commands to dialogue before adding the Tier 2 small model — if the string tiers already catch most
commands, it earns very little.

**5. Promotion store.** Log commands the language model caught that Tier 1 missed; promote a phrase
to the fast path after three consistent hits, so Eva gets faster at your personal phrasing.

**6. Camera and vision.** Implement capture in `sensors/camera_sensor.py`, send frames to the
server for scene understanding with a small vision model.

**7. Motors.** Add the `move` action handler and wire the base.

## Known gaps

- `robot/decision/decision_engine.py` posts to a `/decide` endpoint the server doesn't implement.
  Under the agreed split the server owns planning, so this module should shrink to a dispatcher for
  incoming commands.
- The server address is hardcoded in `robot/config.py`; mDNS discovery would make Eva portable
  between networks.
- `RobotConfig.from_yaml()` and `from_env()` raise `NotImplementedError`.
- The Piper voice model (~63 MB) is committed to the repo. If more voices get added, move them to
  Git LFS or fetch them in a setup step.
- Barge-in (interrupting Eva mid-sentence) needs acoustic echo cancellation; today the microphone
  is simply muted during playback.
