"""
Captures utterances as labelled training data for a future on-device intent model.

Each finalised utterance is written as a WAV file plus one JSON line in a manifest,
giving audio paired with its transcript and the command it turned out to be. That is
exactly the shape needed to train a closed-set intent classifier with a reject class:
`label` is the training target, and `none` is the reject class.

Disabled by default. Recording captures everything said near the robot, so it is opt-in
via EVA_DATASET_CAPTURE_ENABLED and writes only to a local directory.
"""

from __future__ import annotations

import json
import os
import threading
import wave
from dataclasses import dataclass
from typing import Optional

from log import logger

_log = logger("eva.dataset_recorder")

MANIFEST_NAME = "manifest.jsonl"
AUDIO_DIRNAME = "audio"


@dataclass(frozen=True)
class DatasetSettings:
    enabled: bool
    directory: str
    max_bytes: int


class DatasetRecorder:
    """No-op base: used when capture is disabled, so callers need no conditionals."""

    def record(
        self,
        *,
        audio: bytes,
        transcript: str,
        label: str,
        label_source: str,
        sample_rate_hz: int,
        channels: int,
        session_id: str,
        utterance_id: str,
    ) -> None:
        return None


class FileDatasetRecorder(DatasetRecorder):
    """
    Writes `<directory>/audio/<utterance_id>.wav` and appends a row to the manifest.

    Stops recording once the directory exceeds `max_bytes` so a long-running server
    cannot fill the disk. Recording failures are logged and swallowed: losing a
    training sample must never break a conversation.
    """

    def __init__(self, directory: str, max_bytes: int) -> None:
        self._directory = os.path.abspath(directory)
        self._audio_directory = os.path.join(self._directory, AUDIO_DIRNAME)
        self._manifest_path = os.path.join(self._directory, MANIFEST_NAME)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        self._bytes_written = 0
        self._full_warning_logged = False

        os.makedirs(self._audio_directory, exist_ok=True)
        self._bytes_written = self._existing_size()
        _log.info(
            "Dataset capture enabled: %s (%.1f MB already stored)",
            self._directory,
            self._bytes_written / 1e6,
        )

    def _existing_size(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self._directory):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
        return total

    def record(
        self,
        *,
        audio: bytes,
        transcript: str,
        label: str,
        label_source: str,
        sample_rate_hz: int,
        channels: int,
        session_id: str,
        utterance_id: str,
    ) -> None:
        if not audio:
            return

        with self._lock:
            if self._bytes_written >= self._max_bytes:
                if not self._full_warning_logged:
                    _log.warning(
                        "Dataset directory reached %.0f MB; capture paused. "
                        "Move or delete %s to resume.",
                        self._max_bytes / 1e6,
                        self._directory,
                    )
                    self._full_warning_logged = True
                return

            try:
                filename = f"{utterance_id}.wav"
                audio_path = os.path.join(self._audio_directory, filename)
                with wave.open(audio_path, "wb") as wav_file:
                    wav_file.setnchannels(channels)
                    wav_file.setsampwidth(2)  # pcm_s16le
                    wav_file.setframerate(sample_rate_hz)
                    wav_file.writeframes(audio)

                frames = len(audio) // (2 * max(1, channels))
                row = {
                    "audio": os.path.join(AUDIO_DIRNAME, filename),
                    "transcript": transcript,
                    "label": label,
                    "label_source": label_source,
                    "duration_ms": int(frames * 1000 / sample_rate_hz) if sample_rate_hz else 0,
                    "sample_rate_hz": sample_rate_hz,
                    "channels": channels,
                    "session_id": session_id,
                    "utterance_id": utterance_id,
                }
                line = json.dumps(row, ensure_ascii=False) + "\n"
                with open(self._manifest_path, "a", encoding="utf-8") as manifest:
                    manifest.write(line)

                self._bytes_written += len(audio) + len(line)
                _log.debug("Recorded sample %s label=%s", utterance_id, label)
            except Exception as exc:
                _log.warning("Could not record training sample: %s", exc)


def build_dataset_recorder(settings: DatasetSettings) -> DatasetRecorder:
    if not settings.enabled:
        return DatasetRecorder()
    try:
        return FileDatasetRecorder(settings.directory, settings.max_bytes)
    except Exception as exc:
        _log.warning("Dataset capture could not start (%s); continuing without it", exc)
        return DatasetRecorder()
