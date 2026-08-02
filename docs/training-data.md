# Capturing training data

The long-term plan is to move command recognition onto the Pi as an acoustic intent
model, so "stop" never makes a network round trip. That model needs audio recorded
through *your* microphone, in *your* rooms, in *your* voice — which the server can
collect for free while you use Eva normally.

Every finalised utterance already arrives at the server with its audio and, moments
later, the command it turned out to be. Capture just writes that pair to disk.

## Enabling it

Copy the template and flip the flag:

```bash
cp server/.env.example server/.env
```

Then set `EVA_DATASET_CAPTURE_ENABLED=true` in `server/.env` and restart the server.
Real environment variables still override the file, so `EVA_DATASET_CAPTURE_ENABLED=true make server`
works as a one-off without editing anything.

| Variable | Default | Purpose |
|---|---|---|
| `EVA_DATASET_CAPTURE_ENABLED` | `false` | Master switch |
| `EVA_DATASET_DIR` | `dataset` | Where samples are written |
| `EVA_DATASET_MAX_BYTES` | `2000000000` | Capture pauses at this size (2 GB) |

`server/.env` and `dataset/` are both gitignored. Capture records everyone who speaks
near the robot, so leave it off unless you are deliberately collecting, and tell people
in the room when it is on.

## What gets written

```
dataset/
├── manifest.jsonl
└── audio/
    ├── utt_a1b2.wav
    └── ...
```

Audio is 16 kHz mono PCM — exactly what the recogniser received — and each manifest row
describes one sample:

```json
{
  "audio": "audio/utt_a1b2.wav",
  "transcript": "turn left",
  "label": "turn_left",
  "label_source": "rule",
  "duration_ms": 500,
  "sample_rate_hz": 16000,
  "channels": 1,
  "session_id": "s_2af9…",
  "utterance_id": "utt_a1b2"
}
```

`label` is the training target: a command key when a rule matched, or `none` when the
utterance was ordinary conversation. That `none` class is what teaches the model to
*reject* non-commands, which is the part that decides whether Eva acts on things you
never meant as instructions — so ordinary chatter is valuable data, not noise.

`label_source` records how the label was derived (`rule` or `dialogue`) so you can filter
to only the labels you trust when training.

## Checking progress

```bash
make dataset
```

It prints samples, minutes of audio and the number of distinct phrasings per label, and
warns when a class is thin. Distinct phrasings matter more than raw counts: fifty
recordings of you saying "turn left" identically teach far less than fifty different ways
of asking Eva to turn.

Rough targets before training: a few hundred samples per command, and at least as many
`none` samples as your largest command class.

## Known limitation

Labels come from the rule matcher, so the dataset inherits its blind spots. If you say
"quit moving" today, no rule matches, and it gets recorded as `none` — a wrong label for
what is really a stop command. Two ways to handle it: fix labels by hand in the manifest
before training (the transcript is right there, so it is quick to grep), or wait until the
language model tier can supply labels for utterances the rules miss, which is the
promotion-store mechanism on the roadmap.

Until then, prefer phrasings the rules already know while collecting, and treat the
`none` class as needing a manual pass.
