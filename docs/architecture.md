# Architecture

Eva is split across two machines. The **robot** (Raspberry Pi 4) owns hardware, reflexes and
execution. The **server** (Mac mini) owns everything expensive: speech recognition, language
models, speech synthesis. They talk over one WebSocket session on the local network.

The split exists because a Pi 4 running a language model manages a few tokens per second while
pegging the CPU that also has to drive motors — and it drains the battery faster than streaming
audio over WiFi ever would. Keeping the Pi thin is what makes Eva fast.

## The whole system

```mermaid
flowchart TD

  subgraph PI["Raspberry Pi 4 - robot client"]
    MIC["Microphone<br/>16 kHz mono, 32 ms frames"]
    VAD["VoiceGate - Silero VAD<br/>pre-roll 500ms, start 3 frames, hangover 500ms"]
    CAP["Capability manifest<br/>built from ServiceRegistry"]
    WSC["WebSocket client<br/>persistent, auto-reconnect"]
    DISP["Command dispatcher<br/>grouped queues, epoch filter, stop preempts"]
    MOT["Motors"]
    EYE["OLED eyes"]
    SPK["Speaker"]
    REF["Local reflexes<br/>idle blink, intent saccade"]
    DEG["Degraded mode<br/>if server unreachable"]
  end

  subgraph NET["Local WiFi - mDNS discovery"]
    WS["WebSocket session<br/>binary audio + JSON control"]
  end

  subgraph MAC["Mac mini - server brain"]
    STT["Streaming STT<br/>whisper.cpp Metal"]
    T0{"Tier 0 - safety reflex<br/>string match, ~0 ms"}
    T1{"Tier 1 - exact + learned<br/>whole-utterance match, ~0 ms"}
    T2["Tier 2 - small LLM 0.6B<br/>command or none, ~120 ms"]
    T3["Tier 3 - main LLM 7B<br/>say + commands, ~600 ms"]
    ARB["Arbiter<br/>dedupe, validate vs capabilities, stamp epoch"]
    PROMO[("Promotion store<br/>phrase to command, promote after 3 hits")]
    CTX[("Context<br/>perception, memory, capabilities")]
    TTS["TTS - Piper or Kokoro<br/>sentence-split streaming"]
  end

  MIC --> VAD
  VAD -->|"speech.started"| WSC
  VAD -->|"audio frames, 64 ms"| WSC
  VAD -->|"audio.end on hangover"| WSC
  CAP -->|"announce on connect"| WSC
  WSC --> WS
  WS --> STT

  STT -->|"transcript + epoch"| T0
  T0 -->|"STOP matched - preempt"| ARB
  T0 -->|"cancel in-flight call"| T3
  T0 -->|"no match"| T1
  T1 -->|"utterance IS a command"| ARB
  T1 -->|"no match - fan out"| T2
  T1 -->|"no match - fan out"| T3

  T2 -->|"confident cheap command"| ARB
  T2 -->|"none"| T3
  CTX --> T3
  T3 -->|"say + commands JSON"| ARB
  T3 -->|"command Tier 1 missed"| PROMO
  PROMO -->|"learned phrase"| T1

  ARB -->|"speak text"| TTS
  ARB -->|"cmd envelopes"| WS
  TTS -->|"audio out"| WS

  WS --> DISP
  DISP --> MOT
  DISP --> EYE
  DISP --> SPK
  DISP -->|"cmd.ack"| WSC
  REF --> EYE
  DEG --> REF
```

## Understanding the four tiers

An utterance escalates through tiers that get smarter and slower. Each one can end the turn, so
common cases never pay for the expensive path.

**Tier 0 — safety reflex.** Only `stop` and its synonyms, matched anywhere in the utterance.
Fires instantly and preempts: cancels the in-flight model call and clears queued movement. This is
the one place where loose substring matching is correct, because stopping unnecessarily costs far
less than failing to stop.

**Tier 1 — exact and learned match.** Fires only when the *entire* normalised utterance is a
command, after stripping politeness ("eva", "please", "can you"). "Turn left." dispatches with no
model involved at all.

**Tier 2 — small model.** A 0.6B model constrained to emit *a command or nothing* — never speech.
It catches phrasings the string tiers miss ("scoot over a bit"). It may only emit cheap, reversible
commands; anything higher-stakes waits for Tier 3.

**Tier 3 — main model.** Full context, constrained to a `say` + `commands` JSON schema.

Tiers 2 and 3 run **in parallel, not in sequence**. A router placed in front of everything would
add its latency to every dialogue turn while only helping commands — which Tier 1 already handles
for free. Racing them means a confident Tier 2 answer lets the robot react physically in ~120 ms
while Tier 3 is still composing the sentence, and the arbiter drops the duplicate if Tier 3 emits
the same command.

## Three ideas that hold the design together

**Capabilities become grammar.** The robot announces what hardware it has on connect. The server
builds its JSON schema from that manifest, so the models *cannot* emit an action the robot doesn't
have — no prompt engineering, no filtering after the fact. Add or remove hardware and the server
adapts with no code change.

**Epochs prevent stale actions.** Every transcript and command carries an epoch. When a new
utterance begins the epoch increments, and commands from older epochs are discarded — so a slow
model reply from the previous sentence never gets acted on.

**Reflexes stay local.** Idle blinking, intent saccades and obstacle stops live on the Pi. If the
server is unreachable Eva degrades to a blinking, idling robot rather than a brick.

## Inside the robot runtime

The Pi runs an event-driven graph wired together in `robot/runtime.py`. Components publish to
topics on an async bus and never call each other directly, so a slow network client can't block
audio capture.

Most components are services with `start()`/`stop()` managed by `ServiceRegistry`: start in
registration order, stop in reverse, and failures are logged without taking the robot down. That
partial-failure tolerance is what makes the modular hardware story work — a missing camera
degrades one service instead of the whole robot.

See [protocol.md](protocol.md) for the wire contract and [roadmap.md](roadmap.md) for what is built
versus planned.
