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
- Capability handshake — the robot announces its hardware, the server answers with the actions that
  hardware supports, and the language model's output schema is built from the same manifest, so a
  model cannot name an action the robot lacks
- The language model can act: replies are constrained to `say` plus `commands`, and the spoken half
  is still read out of the reply as it streams
- Movement: a TB6612FNG differential base executing `move_base` on the Pi, a US-100 obstacle reflex
  that holds forward motion at a wall without trapping the robot against it, and stops on a lost
  server, on shutdown and on the HAT's button
- The robot announces its own hardware, so what it actually brought up is what the model is offered

## Next, in order

**1. Drive it.** Everything below the wheels is written and tested against stubs; none of it has
met a motor. Wire the TB6612 per [HARDWARE.md](../robot/HARDWARE.md), run `tools/motor_check.py`
with the wheels off the ground, and expect to set `invert_left` or `invert_right`. Then tune
`drive_speed` and `turn_speed` — the defaults are cautious guesses about a floor nobody has driven
on.

**2. Tune the endpointer against real speech.** The defaults — 0.6 s hangover, 0.3 s pre-roll, a
0.5 Smart Turn threshold — are starting points, not measurements. Capture a handful of real
exchanges and check the two failure directions separately: cutting you off mid-thought means the
hangover or the turn threshold is too aggressive, while a laggy feel means they are too generous.

**3. Measure how well a 3B model actually picks actions.** The schema guarantees the shape of the
reply, not the judgement behind it. Run a couple of dozen real utterances through
`tools/mock_robot.py` and count two errors separately: movement invented for a sentence that only
wanted conversation, and movement missed for one that asked for it. That number decides whether
tiers are worth building at all.

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
small vision model over them. The manifest already carries `camera` as a known sensor, so the
handshake half is done. (The earlier stub and its HTTP client were removed as dead code — this
starts fresh, over the existing WebSocket rather than a third service.)

**8. Remember the apartment.** An occupancy map, a pose within it, and `navigate_to`. Blocked on
wheel encoders — commanded motion drifts from actual motion without bound, and there are none in
the parts list. The full technical plan is in
[proposals/occupancy-mapping.md](proposals/occupancy-mapping.md).

## Known gaps

- **Eva cannot hear "stop" while she is speaking.** Her microphone is muted during playback so she
  does not transcribe herself, so for the couple of seconds a reply takes, a spoken stop has
  nowhere to land. The obstacle reflex and the HAT button cover it; the real fix is acoustic echo
  cancellation plus the Tier 0 preemption in the tier design, which would let a stop cut through a
  reply that is still being spoken.
- `come_here` drives forward. There is no direction to home in on — no microphone array, no vision
  tracking — so it means "towards where I am facing", which is right often enough to be useful and
  wrong often enough to be worth fixing.
- Movement is open-loop. No encoders, so the robot knows what it asked the wheels to do and nothing
  about what they did. This is what blocks mapping — see the proposal.
- Eva speaks before she moves. `say` comes before `commands` in the schema, which is what lets the
  reply start streaming, so the command lands a couple of hundred milliseconds after the sentence
  that announces it. Fine for "I'm coming over"; wrong for an urgent stop, which is what Tier 0 in
  the tier design exists to handle.
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
- Robot-side test coverage is thin: `robot/tests/` pins microphone capture rate with the
  hardware drivers stubbed, but nothing else. `robot/tools/` are manual hardware checks.
- The action registry is still two entries wide. Eye expressions are driven robot-side from
  `server_feedback.py` rather than being actions the model can choose, so Eva cannot decide to look
  sad about something. Adding `set_expression` to the registry is now a small change on both sides,
  and the `eyes` actuator it would require is already in the manifest.
