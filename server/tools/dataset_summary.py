"""
Summarise captured training data: how many samples per label, and how much audio.

Run from the server directory:
    python tools/dataset_summary.py [dataset_dir]

Use it to judge when you have enough data to train the on-device intent model.
A rough target is a few hundred samples per command label, plus at least as many
"none" samples as your largest command class so the reject class is not starved.
"""

from __future__ import annotations

import collections
import json
import os
import sys


def main() -> int:
    directory = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("EVA_DATASET_DIR", "dataset")
    manifest_path = os.path.join(directory, "manifest.jsonl")

    if not os.path.isfile(manifest_path):
        print(f"No manifest at {manifest_path}.")
        print("Enable capture with EVA_DATASET_CAPTURE_ENABLED=true in server/.env, then talk to Eva.")
        return 1

    counts: collections.Counter[str] = collections.Counter()
    duration_ms: collections.Counter[str] = collections.Counter()
    sources: collections.Counter[str] = collections.Counter()
    transcripts: dict[str, set[str]] = collections.defaultdict(set)
    malformed = 0

    with open(manifest_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            label = str(row.get("label", "?"))
            counts[label] += 1
            duration_ms[label] += int(row.get("duration_ms") or 0)
            sources[str(row.get("label_source", "?"))] += 1
            text = str(row.get("transcript", "")).strip().lower()
            if text:
                transcripts[label].add(text)

    total = sum(counts.values())
    if total == 0:
        print("Manifest is empty.")
        return 1

    print(f"{total} samples, {sum(duration_ms.values()) / 60000:.1f} minutes of audio\n")
    print(f"{'label':<16}{'samples':>9}{'minutes':>9}{'phrasings':>11}")
    print("-" * 45)
    for label, count in counts.most_common():
        print(f"{label:<16}{count:>9}{duration_ms[label] / 60000:>9.1f}{len(transcripts[label]):>11}")

    print(f"\nlabel sources: {dict(sources)}")
    if malformed:
        print(f"warning: {malformed} malformed manifest line(s) skipped")

    command_counts = [c for label, c in counts.items() if label != "none"]
    if command_counts:
        smallest = min(command_counts)
        if smallest < 100:
            print(f"\nSmallest command class has {smallest} samples — aim for a few hundred before training.")
        if counts["none"] < max(command_counts):
            print("The 'none' class is smaller than your largest command class; collect more ordinary conversation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
