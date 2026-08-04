# How Eva works, step by step

Every diagram here names real files and real functions. If a box says
`endpointing.py · push()`, that function exists and is on the path.

For the shape of the system and the reasoning behind it, read
[architecture.md](architecture.md). This page is the wiring.

- [The components](#the-components)
- [Startup — the server](#startup--the-server)
- [Startup — the robot](#startup--the-robot)
- [A command: "turn left"](#a-command-turn-left)
- [A conversation: "what do you want to talk about"](#a-conversation-what-do-you-want-to-talk-about)
- [A thinking pause](#a-thinking-pause)
- [Not hearing herself](#not-hearing-herself)
- [Losing the server](#losing-the-server)

---

## The components

Two processes on two machines, one WebSocket between them. Dotted arrows are
the event bus; solid arrows are direct calls or network traffic.

```mermaid
flowchart TB

subgraph PI["Raspberry Pi 4 — robot/"]
  direction TB

  subgraph PIBOOT["composition root"]
    MAIN["main.py"]
    RT["runtime.py<br/><i>builds and wires everything</i>"]
    CFG1["config.py<br/><i>dataclasses</i>"]
  end

  subgraph PICORE["core/"]
    BUS["event_bus.py<br/><i>async pub/sub</i>"]
    REG["service_registry.py<br/><i>start and stop order</i>"]
    DISP["action_dispatcher.py<br/><i>routes to handlers</i>"]
  end

  MIC["sensors/microphone_sensor.py<br/><i>pyaudio → 512-sample frames</i>"]
  SC["perception/speech_client.py<br/><i>owns the WebSocket</i>"]
  FB["behaviors/server_feedback.py<br/><i>reacts to the server</i>"]
  BLINK["behaviors/idle_blink.py"]
  EYEH["actions/eye_expression_handler.py"]
  EYEC["display/eye_controller.py<br/><i>OLED over I2C</i>"]
  AUD["utils/audio.py<br/><i>AudioOutput — all sound</i>"]

  MAIN --> RT
  CFG1 --> RT
  RT --> REG
  REG -.-> MIC
  REG -.-> SC
  REG -.-> FB
  REG -.-> BLINK
  MIC -. "sensor.audio" .-> BUS
  BUS -.-> SC
  SC -. "perception.backend_*" .-> BUS
  BUS -.-> FB
  BLINK -. "decision.actions" .-> BUS
  BUS -.-> DISP
  FB --> DISP
  DISP --> EYEH
  EYEH --> EYEC
  FB --> AUD
  EYEH --> AUD
end

subgraph MAC["Mac mini — server/"]
  direction TB

  subgraph MACBOOT["startup, once"]
    ASGI["asgi.py"]
    APP["app.py<br/><i>lifespan builds every engine</i>"]
    CFG2["config.py<br/><i>env vars</i>"]
  end

  WS["websocket_session.py<br/><i>one session per robot</i>"]

  subgraph LISTEN["listening"]
    EP["endpointing.py<br/><i>ring buffer, pre-roll, hangover</i>"]
    VAD["voice_activity.py<br/><i>Silero — is this speech?</i>"]
    TURN["turn_detection.py<br/><i>Smart Turn — finished?</i>"]
    STT["speech_to_text.py<br/><i>faster-whisper</i>"]
  end

  subgraph THINK["deciding"]
    PLAN["planner.py"]
    RULES["action_rules.py<br/><i>phrase regexes</i>"]
    ACT["actions.py<br/><i>registry + validation</i>"]
    LLM["language_model.py<br/><i>Ollama, streamed</i>"]
  end

  subgraph SPEAK["speaking"]
    SENT["sentences.py<br/><i>tokens → sentences</i>"]
    TTS["text_to_speech.py<br/><i>Piper, or macOS say</i>"]
  end

  PROTO["protocol.py<br/><i>message envelopes</i>"]
  REC["dataset_recorder.py"]

  ASGI --> APP
  CFG2 --> APP
  APP --> WS
  WS --> EP
  EP <--> VAD
  EP <--> TURN
  WS --> STT
  WS --> PLAN
  PLAN --> RULES
  PLAN --> ACT
  WS --> LLM
  LLM --> SENT
  SENT --> TTS
  WS --> TTS
  WS --> PROTO
  WS --> REC
end

subgraph EXT["external"]
  OLLAMA["ollama<br/><i>separate process, :11434</i>"]
  ONNX[("models/<br/>silero_vad.onnx<br/>smart_turn.onnx")]
end

SC <-->|"WebSocket :8002 — binary audio up, JSON and WAV down"| WS
LLM -->|"HTTP :11434"| OLLAMA
VAD --- ONNX
TURN --- ONNX
```

Note where the models live: `silero_vad.onnx` and `smart_turn.onnx` are files
loaded **inside the server process** by onnxruntime. Only the chat model is a
separate service.

---

## Startup — the server

Runs once, before any robot connects. Building Whisper and the ONNX sessions is
slow, so it happens here and the results are shared by every connection.

```mermaid
sequenceDiagram
    autonumber
    participant U as uvicorn
    participant A as app.py
    participant C as config.py
    participant B as build factories

    U->>A: import asgi:app → create_app()
    A->>A: lifespan starts
    A->>C: load_settings()
    C->>C: load_dotenv() then read EVA_* vars
    C-->>A: Settings

    A->>B: build_speech_to_text_engine()
    B-->>A: FasterWhisper, or Stub if unavailable
    A->>B: build_text_to_speech_engine()
    B-->>A: Piper if it really synthesises, else macOS say
    A->>B: build_language_model_client()
    B-->>A: Ollama, or Disabled if the flag is off
    A->>B: build_voice_activity_detector()
    B-->>A: Silero, or AlwaysSpeech if the file is missing
    A->>B: build_turn_detector()
    B-->>A: SmartTurn, or SilenceOnly

    Note over A,B: Every factory returns something usable.<br/>A missing model degrades loudly, never crashes.

    A->>A: store all six on app.state
    A-->>U: ready, listening on :8002
```

---

## Startup — the robot

```mermaid
sequenceDiagram
    autonumber
    participant M as main.py
    participant R as runtime.py
    participant Reg as service_registry.py
    participant Svc as services

    M->>R: RobotRuntime(config)
    R->>R: build EyeController, AudioOutput
    R->>R: register eye handlers on ActionDispatcher
    R->>Reg: register microphone, speech_client,<br/>server_feedback, idle_blink
    R->>R: subscribe to "decision.actions"

    M->>R: run()
    R->>R: audio_output.apply_volume()
    R->>Reg: start_all()

    loop in registration order
        Reg->>Svc: start()
        Note over Reg,Svc: A failure is logged, not fatal.<br/>No display means no eyes, not no robot.
    end

    R->>R: play the startup animation and sound
    Note over R: Now idle, waiting on the event bus.
```

---

## A command: "turn left"

The fast path. A rule matches, so no language model is involved at all.

```mermaid
sequenceDiagram
    autonumber
    participant Mic as microphone_sensor.py
    participant Bus as event_bus.py
    participant SC as speech_client.py
    participant WS as websocket_session.py
    participant EP as endpointing.py
    participant VAD as voice_activity.py
    participant TD as turn_detection.py
    participant STT as speech_to_text.py
    participant PL as planner.py
    participant TTS as text_to_speech.py
    participant FB as server_feedback.py
    participant AO as utils/audio.py

    Note over Mic: You say "turn left"

    loop every 32 ms
        Mic->>Mic: _reassembly_worker() cuts 512 samples
        Mic->>Bus: publish "sensor.audio"
        Bus->>SC: process(frame)
        SC->>SC: _outbox.put_nowait(frame)
        SC->>WS: _producer_loop() sends binary frame
        WS->>WS: receive loop → audio_queue
        WS->>EP: _audio_loop() → frames_from_pcm16() → push(frame)
        EP->>VAD: speech_probability(frame)
        VAD-->>EP: 0.0 … 1.0
    end

    Note over EP: First frame over 0.5 →<br/>_begin_utterance() seeds the buffer<br/>with the 300 ms already captured
    WS->>SC: status "listening"
    SC->>Bus: "perception.backend_listening"
    Bus->>FB: eyes glance

    Note over EP: You stop. 0.6 s of silence.
    EP->>EP: _on_hangover_elapsed()
    EP->>TD: is_complete(audio)
    TD-->>EP: true
    EP->>EP: _finish()
    EP-->>WS: the whole utterance as PCM

    WS->>STT: transcribe(audio)
    STT-->>WS: "turn left"
    WS->>SC: transcript.final
    WS->>PL: plan_from_transcript("turn left")
    PL->>PL: match_action_from_text() hits the turn_left rule
    PL->>PL: validate_command() against actions.py
    PL-->>WS: speak "Turning left." + move_base turn_left

    Note over WS: speak is fulfilled here, not shipped.<br/>The robot has no voice of its own.
    WS->>TTS: synthesize_wav("Turning left.")
    TTS-->>WS: WAV bytes
    WS->>SC: speech.start, then the WAV, then speech.end
    WS->>SC: command move_base
    WS->>WS: ignore_until = now + 1.5 s

    SC->>Bus: backend_speech, backend_audio, backend_command
    Bus->>FB: _on_backend_speech() → happy eyes
    Bus->>FB: _on_backend_audio()
    FB->>AO: play_speech(wav)
    Note over AO: Blocks while aplay runs, so the<br/>microphone stays muted exactly that long
    Bus->>FB: _on_backend_command() → move_base logged
```

---

## A conversation: "what do you want to talk about"

No rule matches, so it becomes dialogue — and the reply is spoken while it is
still being written.

```mermaid
sequenceDiagram
    autonumber
    participant WS as websocket_session.py
    participant PL as planner.py
    participant LLM as language_model.py
    participant OL as ollama
    participant SA as sentences.py
    participant TTS as text_to_speech.py
    participant SC as speech_client.py
    participant AO as utils/audio.py

    Note over WS: Utterance already endpointed<br/>and transcribed, as above

    WS->>PL: plan_from_transcript(text)
    PL-->>WS: no rule matched → dialogue
    WS->>WS: _stream_reply()
    WS->>SC: status "thinking"
    Note over SC: eyes start the thinking loop

    WS->>LLM: stream(system_prompt, user_text)
    LLM->>OL: POST /api/chat, stream true,<br/>num_predict 80, keep_alive 30m

    loop token by token
        OL-->>LLM: token
        LLM-->>WS: token
        WS->>SA: add(token)
        alt a sentence just closed
            SA-->>WS: "I'd love to hear about your day."
            WS->>TTS: synthesize_wav(sentence)
            TTS-->>WS: WAV
            WS->>SC: speech.start + WAV + speech.end
            SC->>AO: play_speech(wav)
            Note over AO: Eva is already talking while<br/>the model writes the next sentence
        else mid-sentence
            SA-->>WS: nothing yet
        end
    end

    WS->>SA: finish()
    SA-->>WS: any trailing text
    WS->>SC: language_model.result, status "ready"
```

---

## A thinking pause

Why a 600 ms pause mid-sentence no longer cuts you off.

```mermaid
sequenceDiagram
    autonumber
    participant EP as endpointing.py
    participant VAD as voice_activity.py
    participant TD as turn_detection.py

    Note over EP: "What do you want…"
    loop while you speak
        EP->>VAD: speech_probability(frame)
        VAD-->>EP: ~1.0
    end

    Note over EP: …you pause to think
    loop 19 silent frames = 0.6 s
        EP->>VAD: speech_probability(frame)
        VAD-->>EP: ~0.0
        EP->>EP: _silent_frames += 1
    end

    EP->>EP: _on_hangover_elapsed()
    EP->>TD: is_complete(audio so far)
    TD->>TD: last 8 s → 80×800 mel → sigmoid
    TD-->>EP: false — sounds unfinished
    Note over EP: extension budget spent += 0.6 s<br/>silence counter reset, keep listening

    Note over EP: "…to talk about"
    loop you continue
        EP->>VAD: speech_probability(frame)
        VAD-->>EP: ~1.0
    end

    Note over EP: you really stop
    EP->>TD: is_complete(audio)
    TD-->>EP: true
    EP->>EP: _finish() — one utterance, not two
```

If the detector never says "finished", `max_extension_seconds` (4 s by default)
ends the turn anyway, so a noisy room cannot hold the microphone open forever.

---

## Not hearing herself

Eva's speaker is centimetres from her microphone, so her own voice comes
straight back in. Two mechanisms, one per side.

```mermaid
sequenceDiagram
    autonumber
    participant WS as websocket_session.py
    participant SC as speech_client.py
    participant Bus as event_bus.py
    participant FB as server_feedback.py
    participant AO as utils/audio.py
    participant EP as endpointing.py

    WS->>WS: _speak() sets ignore_until = now + 1.5 s
    WS->>SC: speech.start + WAV

    par robot side
        SC->>Bus: backend_audio
        Bus->>FB: _on_backend_audio()
        FB->>Bus: backend_audio_playing
        Bus->>SC: _on_backend_audio_playing() clears _send_allowed
        Note over SC: process() returns early —<br/>no frames leave the Pi
        FB->>AO: play_speech(wav) — blocks
        AO-->>FB: finished
        FB->>Bus: backend_audio_done
        Bus->>SC: _send_allowed.set()
    and server side
        Note over WS,EP: Any frame still in flight arrives<br/>before ignore_until, so _audio_loop<br/>drops it and calls endpointer.reset()
    end
```

The server-side guard exists because frames already in the socket buffer cannot
be recalled — muting the Pi stops new audio, not audio already sent.

---

## Losing the server

```mermaid
sequenceDiagram
    autonumber
    participant SC as speech_client.py
    participant WS as the server
    participant Bus as event_bus.py
    participant BL as idle_blink.py

    SC->>WS: connect
    WS--xSC: unreachable
    SC->>SC: _connection_manager() logs the error type,<br/>waits 5 s, retries

    Note over SC: while disconnected, process()<br/>returns early and drops frames
    Note over SC: Deliberate — a backlog would be flushed<br/>on reconnect as a burst of stale speech

    Note over BL,Bus: Idle blinking is a local service and<br/>keeps running, so Eva stays alive-looking<br/>rather than freezing

    SC->>WS: reconnect succeeds
    WS-->>SC: hello, status ready
    Note over SC: frames flow again from now,<br/>with nothing stale in front of them
```

---

## Where to look when something breaks

| Symptom | Start here |
|---|---|
| Sentences cut short | `endpointing.py` — hangover and turn detection |
| First word missing | `endpointing.py` — `preroll_seconds` |
| Nothing transcribed | `voice_activity.py` — is the model loaded? check the startup log |
| Eva never replies | `EVA_LANGUAGE_MODEL_ENABLED`, and whether the Ollama model name exists |
| Wrong voice | `text_to_speech.py` — the startup log says `piper` or falls back to `say` |
| Too quiet or too loud | `robot/config.py` — `AudioConfig.volume_percent` |
| Eva talks over herself | `ignore_until` in `websocket_session.py`, `_send_allowed` in `speech_client.py` |
