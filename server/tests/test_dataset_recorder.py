from __future__ import annotations

import json
import os
import wave

from dataset_recorder import DatasetSettings, build_dataset_recorder


def _silence(frames: int = 1600) -> bytes:
    return b"\x00\x00" * frames


def _record_one(recorder, utterance_id="utt_1", label="turn_left", source="rule"):
    recorder.record(
        audio=_silence(),
        transcript="turn left",
        label=label,
        label_source=source,
        sample_rate_hz=16000,
        channels=1,
        session_id="s_test",
        utterance_id=utterance_id,
    )


def test_disabled_recorder_writes_nothing(tmp_path):
    directory = tmp_path / "dataset"
    recorder = build_dataset_recorder(
        DatasetSettings(enabled=False, directory=str(directory), max_bytes=10_000_000)
    )
    _record_one(recorder)
    assert not directory.exists()


def test_records_wav_and_manifest_row(tmp_path):
    directory = tmp_path / "dataset"
    recorder = build_dataset_recorder(
        DatasetSettings(enabled=True, directory=str(directory), max_bytes=10_000_000)
    )
    _record_one(recorder)

    audio_path = directory / "audio" / "utt_1.wav"
    assert audio_path.is_file()

    with wave.open(str(audio_path), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getframerate() == 16000
        assert wav_file.getsampwidth() == 2
        assert wav_file.getnframes() == 1600

    rows = [json.loads(line) for line in (directory / "manifest.jsonl").read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["label"] == "turn_left"
    assert rows[0]["label_source"] == "rule"
    assert rows[0]["transcript"] == "turn left"
    assert rows[0]["duration_ms"] == 100
    assert rows[0]["audio"] == os.path.join("audio", "utt_1.wav")


def test_dialogue_is_recorded_as_reject_class(tmp_path):
    directory = tmp_path / "dataset"
    recorder = build_dataset_recorder(
        DatasetSettings(enabled=True, directory=str(directory), max_bytes=10_000_000)
    )
    _record_one(recorder, utterance_id="utt_2", label="none", source="dialogue")

    rows = [json.loads(line) for line in (directory / "manifest.jsonl").read_text().splitlines()]
    assert rows[0]["label"] == "none"


def test_capture_stops_once_over_size_limit(tmp_path):
    # The limit is checked against what is already stored, so the first sample
    # always lands; everything after it is skipped.
    directory = tmp_path / "dataset"
    recorder = build_dataset_recorder(
        DatasetSettings(enabled=True, directory=str(directory), max_bytes=1)
    )
    _record_one(recorder, utterance_id="utt_1")
    _record_one(recorder, utterance_id="utt_2")
    _record_one(recorder, utterance_id="utt_3")

    rows = (directory / "manifest.jsonl").read_text().splitlines()
    assert len(rows) == 1
    assert (directory / "audio" / "utt_1.wav").is_file()
    assert not (directory / "audio" / "utt_2.wav").exists()


def test_empty_audio_is_skipped(tmp_path):
    directory = tmp_path / "dataset"
    recorder = build_dataset_recorder(
        DatasetSettings(enabled=True, directory=str(directory), max_bytes=10_000_000)
    )
    recorder.record(
        audio=b"",
        transcript="",
        label="none",
        label_source="dialogue",
        sample_rate_hz=16000,
        channels=1,
        session_id="s_test",
        utterance_id="utt_empty",
    )
    assert not (directory / "manifest.jsonl").exists()
