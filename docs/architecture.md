# Architecture

Eva is split across two machines. The **robot** (Raspberry Pi 4) owns hardware, reflexes and
execution. The **server** (Mac mini) owns everything expensive: speech recognition, language
models, speech synthesis. They talk over one WebSocket session on the local network.

The split exists because a Pi 4 running a language model manages a few tokens per second while
pegging the CPU that also has to drive motors — and it drains the battery faster than streaming
audio over WiFi ever would. Keeping the Pi thin is what makes Eva fast.

This page has two halves. **[What runs today](#what-runs-today)** describes the code as it exists;
**[Where this is going](#where-this-is-going)** describes the design being built toward. Nothing in
the second half is implemented yet — check [roadmap.md](roadmap.md) for the order of work.

---

## What runs today

```mermaid
flowchart LR

  subgraph PI["Raspberry Pi 4 — robot"]
    MIC["MicrophoneSensor<br/>16 kHz mono, 512-sample frames"]
    SC["SpeechClient<br/>WebSocket, auto-reconnect<br/>relays every frame"]
    FB["ServerFeedbackService<br/>eyes + queued speech playback"]
    EYE["OLED eyes"]
    BLINK["IdleBlinkService"]
  end

  subgraph MAC["Mac mini — server"]
    EP["Endpointer<br/>ring buffer + pre-roll"]
    VAD["Silero VAD<br/>per 32 ms frame"]
    TURN["Smart Turn v3<br/>is the sentence finished?"]
    STT["faster-whisper"]
    PLAN["planner + action_rules"]
    LLM["Ollama<br/>streamed tokens"]
    SENT["SentenceAccumulator"]
    TTS["Piper (or macOS say)"]
    REC["DatasetRecorder"]
  end

  MIC -->|"sensor.audio"| SC
  SC -->|"binary PCM, continuous"| EP
  EP <--> VAD
  EP <--> TURN
  EP -->|"complete utterance"| STT
  STT --> PLAN
  STT --> REC
  PLAN -->|"rule matched"| TTS
  PLAN -->|"movement"| SC
  PLAN -->|"no match → dialogue"| LLM
  LLM --> SENT
  SENT -->|"sentence at a time"| TTS
  TTS -->|"WAV per sentence"| SC
  SC -->|"perception.backend_*"| FB
  FB --> EYE
  BLINK --> EYE
```

**One turn, end to end.** The microphone publishes 32 ms frames and the SpeechClient relays every
one of them — the robot makes no judgement about what is worth hearing. On the Mac, each frame goes
to the Endpointer, which scores it with Silero VAD and keeps a rolling buffer. When speech starts,
the buffer already holds the 300 ms *before* detection, so the start of the first word is recovered
rather than clipped. When speech stops, Smart Turn decides whether the sentence actually sounds
finished; if it doesn't, the window extends and a thinking pause no longer cuts you off.

The completed utterance goes to Whisper, then to the rule matcher. A match speaks its confirmation
and sends any movement as a command. No match becomes dialogue: Ollama's tokens are streamed into a
sentence accumulator, and each sentence is synthesised and sent as it completes — so Eva starts
talking while the rest of the reply is still being written. The robot mutes its own microphone
during playback so she doesn't transcribe herself.

**Why the deciding happens on the Mac.** The robot used to drop quiet frames with an RMS threshold.
That put the most consequential judgement in the pipeline on the weakest CPU, using a fixed
threshold against a 1.5-second average, and it clipped word onsets — a frame is only sent *after*
it crosses the threshold, and the beginning of a word is quiet. Continuous streaming costs 32 KB/s,
which is nothing on a WiFi link, and it buys an important property: **audio that was never
discarded can still be recovered.** Pre-roll is only possible because nothing was thrown away.

**What is still simple.** There is one matching tier, not four. The language model is prompted for
plain text rather than constrained by the action registry. There is no arbiter, no epochs, and no
capability handshake — the robot executes whatever command arrives.

**What is worth keeping.** Components publish to topics on an async bus and never call each other
directly, so a slow network client can't block audio capture. Services with `start()`/`stop()` are
managed by `ServiceRegistry`: started in registration order, stopped in reverse, and a failure is
logged without taking the robot down — a missing display degrades one service instead of the whole
robot. Every command reaching the wire passes `validate_command()` in `server/actions.py`, so the
registry is the single source of truth for what Eva can do, even though the models don't read from
it yet.

### Inside the robot

`robot/runtime.py` is the composition root and nothing else: it constructs the graph, registers
services, and handles shutdown. Behavior lives in services.

| Directory | Role |
|---|---|
| `core/` | Event bus, service registry, action dispatcher |
| `sensors/` | Hardware input producers (microphone) |
| `perception/` | `SpeechClient` — owns the WebSocket session with the server |
| `behaviors/` | `ServerFeedbackService` (reacts to server replies), `IdleBlinkService` |
| `actions/` | Eye expression and animation handlers |
| `display/` | `EyeController` — OLED animation primitives |
| `utils/` | Logging, and `AudioOutput` — the one owner of speaker output |

### Inside the server

`app.py` exposes the REST routes and the WebSocket endpoint; `websocket_session.py` runs one
session. Listening is split across three files: `voice_activity.py` (is this frame speech?),
`turn_detection.py` (has the speaker finished?) and `endpointing.py` (the buffer and the decision).
`planner.py` decides commands-versus-dialogue, `action_rules.py` holds the phrase rules, and
`actions.py` is the registry every command is validated against. `sentences.py` cuts the streamed
reply into speakable pieces.

The detectors are injected into the endpointer rather than constructed by it, which is what lets
the endpointing logic be tested with fakes in milliseconds and no model files. `make models`
fetches the ~10 MB of ONNX weights; without them the server still runs, treating every frame as
speech and ending turns on silence alone, and says so in the log.

---

## Where this is going

None of this exists yet. It is recorded here because the shape of the code today — the registry,
the event bus, the validated command envelope — is chosen to make these additions cheap.

**Capabilities become grammar.** The robot announces its hardware on connect. The server builds the
models' JSON output schema from that manifest, so a model *cannot* emit an action the robot lacks.
The registry and `validate_command()` are the half of this that already exists; the handshake and
the schema-constrained prompt are the missing half. Ollama's `format` parameter accepts a JSON
schema directly, which is the mechanism.

**Four tiers instead of one.** An utterance would escalate through tiers that get smarter and
slower, each able to end the turn:

- **Tier 0 — safety reflex.** Only `stop` and synonyms, matched anywhere in the utterance. Preempts:
  cancels the in-flight model call and clears queued movement. Loose substring matching is correct
  here, because stopping unnecessarily costs far less than failing to stop.
- **Tier 1 — exact and learned match.** Fires when the *entire* normalised utterance is a command,
  after stripping politeness. This is roughly what `action_rules.py` does today.
- **Tier 2 — small model.** A 0.6B model constrained to emit a command or nothing, never speech.
  Catches phrasings the string tiers miss, limited to cheap reversible commands.
- **Tier 3 — main model.** Full context, constrained to a `say` + `commands` schema.

Tiers 2 and 3 would run **in parallel, not in sequence**. A router in front of everything would add
its latency to every dialogue turn while only helping commands — which Tier 1 already handles for
free. Racing them lets a confident Tier 2 answer move the robot while Tier 3 is still composing a
sentence, with the arbiter dropping the duplicate. Worth measuring the real command-to-dialogue
ratio before building Tier 2 at all.

**Epochs prevent stale actions.** Every transcript and command carries an epoch that increments
when a new utterance begins; commands from older epochs are discarded, so a slow reply to the
previous sentence never gets acted on.

**Barge-in.** Eva currently goes deaf while speaking, which is the only way to avoid transcribing
herself without acoustic echo cancellation. Real interruption needs AEC, and then the endpointer
already has what it needs to detect that you have started talking over her.

**Reflexes stay local.** Idle blinking already is. Obstacle stops and intent saccades would join it,
so an unreachable server degrades Eva to a blinking, idling robot rather than a brick.

**Streaming transcription is deliberately *not* on this list.** LocalAgreement-style streaming ASR
confirms a prefix only once consecutive decodes agree, which costs latency; a batch decode of a
2–3 s utterance is a few hundred milliseconds on an M2. For short conversational turns it would
make Eva slower, not faster. It earns its place in long-form dictation, which is not this.

See [protocol.md](protocol.md) for the wire contract and [roadmap.md](roadmap.md) for the order of
work.
